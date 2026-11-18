"""Snapshots of the Agent's workspace, one per step, in a hidden git repository.

The App host keeps the repository in its own private folder, which the Agent
cannot read. After every step it commits the workspace as that step's snapshot
under ``refs/plural/steps/<k>``, so a checkpoint can put the files back exactly
as they stood after step *k*. The Environment's ``limits.workspace_snapshot_mib``
caps how much is kept; a file past the cap is recorded as skipped, and every
checkpoint says so. Running processes and anything outside the workspace are
never captured.

At the end of the episode the repository is written out as one git bundle,
which the Job stores with the Trial as ``workspace.bundle``.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from plural.snapshots import SnapshotEntry

BUNDLE_FILE = "workspace.bundle"
STEP_REF = "refs/plural/steps/"
FINAL_REF = "refs/plural/final"
IGNORED = frozenset({".git"})
"""Top-level names a snapshot never holds; any name starting ``.plural``, such as the
App host's private folder, is skipped too."""
_IDENTITY = {
    "GIT_AUTHOR_NAME": "plural",
    "GIT_AUTHOR_EMAIL": "plural@localhost",
    "GIT_COMMITTER_NAME": "plural",
    "GIT_COMMITTER_EMAIL": "plural@localhost",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
}


def git_available() -> bool:
    """Whether ``git`` can be run here.

    Returns:
        True when a ``git`` executable is on the path.
    """
    return shutil.which("git") is not None


def _git(
    git_dir: Path,
    *args: str,
    work_tree: Path | None = None,
    index: Path | None = None,
    stdin: bytes | None = None,
) -> bytes:
    environ = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") and key not in {"HOME", "XDG_CONFIG_HOME"}
    }
    environ.update(_IDENTITY)
    environ.update(
        GIT_DIR=str(git_dir),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        HOME=str(git_dir),
    )
    if work_tree is not None:
        environ["GIT_WORK_TREE"] = str(work_tree)
    if index is not None:
        environ["GIT_INDEX_FILE"] = str(index)
    completed = subprocess.run(
        ["git", *args],
        input=stdin,
        capture_output=True,
        env=environ,
        cwd=str(work_tree or (git_dir if git_dir.is_dir() else git_dir.parent)),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {detail[:400]}")
    return completed.stdout


class WorkspaceSnapshots:
    """One Trial's workspace snapshots, kept where only the App host can read them.

    The :class:`plural.snapshots.Snapshotter` for the workspace; its archive is
    read back with :class:`plural.snapshots.GitBundle`.

    Args:
        workspace: The Agent's workspace, such as ``/workspace``.
        store: A private folder for the repository.
        cap_mib: How many MiB of files one snapshot keeps; 0 turns snapshots off.
    """

    def __init__(
        self,
        workspace: Path,
        store: Path,
        *,
        cap_mib: int = 512,
        ignore: Sequence[str] = (),
    ) -> None:
        self.workspace = workspace
        self.git_dir = store / "workspace.git"
        self.cap_bytes = max(0, cap_mib) * 1024 * 1024
        self.ignore = frozenset(ignore)
        self.snapshots: dict[int, str] = {}
        self.skipped: dict[str, tuple[int, str]] = {}
        self._indexed: set[str] = set()
        self._trees: list[str] = []
        self.problem: str | None = None
        if self.cap_bytes == 0:
            self.problem = "workspace snapshots are off (limits.workspace_snapshot_mib is 0)"
        elif not git_available():
            self.problem = "git is not installed in the Runtime; the workspace is not snapshotted"
        elif not workspace.is_dir():
            self.problem = f"the workspace {workspace} does not exist"
        else:
            store.mkdir(parents=True, exist_ok=True)
            if not self.git_dir.exists():
                _git(self.git_dir, "init", "--bare", "--quiet")

    @property
    def available(self) -> bool:
        """Whether snapshots are being taken."""
        return self.problem is None

    def _files(self) -> list[tuple[str, int]]:
        found: list[tuple[str, int]] = []
        for directory, folders, files in os.walk(self.workspace):
            here = Path(directory)
            top = here == self.workspace
            prefix = "" if top else f"{here.relative_to(self.workspace).as_posix()}/"
            folders[:] = sorted(
                item
                for item in folders
                if item != ".git"
                and not item.startswith(".plural")
                and not (top and item in IGNORED)
                and f"{prefix}{item}/" not in self.ignore
            )
            for name in sorted(files):
                if name.startswith(".plural") or (top and name in IGNORED):
                    continue
                path = here / name
                with contextlib.suppress(OSError):
                    if path.is_symlink() or path.is_file():
                        relative = path.relative_to(self.workspace).as_posix()
                        if relative in self.ignore:
                            continue
                        if not path.is_symlink() and not os.access(path, os.R_OK):
                            found.append((relative, -1))
                            continue
                        found.append((relative, path.lstat().st_size))
        return found

    def snapshot(self, step: int) -> str | None:
        """Commit the workspace as it stands now as step ``step``'s snapshot.

        Returns:
            The commit, or ``None`` when snapshots are off or failed.
        """
        commit = self._commit(f"{STEP_REF}{step}", step)
        if commit is not None:
            self.snapshots[step] = commit
        return commit

    def snapshot_final(self) -> str | None:
        """Commit the workspace as the Harness left it, after its last step.

        Returns:
            The commit, or ``None`` when snapshots are off or failed.
        """
        return self._commit(FINAL_REF, max(self.snapshots, default=0))

    def _commit(self, ref: str, step: int) -> str | None:
        if not self.available:
            return None
        kept: list[str] = []
        total = 0
        for relative, size in self._files():
            if size < 0:
                self.skipped.setdefault(relative, (step, "unreadable"))
                continue
            if total + size > self.cap_bytes:
                self.skipped.setdefault(relative, (step, "over the cap"))
                continue
            total += size
            kept.append(relative)
        # One index across steps, so git re-hashes only the files that changed.
        index = self.git_dir / "plural-index"
        try:
            dropped = sorted(self._indexed - set(kept))
            if dropped:
                _git(
                    self.git_dir,
                    "update-index",
                    "--force-remove",
                    "-z",
                    "--stdin",
                    work_tree=self.workspace,
                    index=index,
                    stdin=b"".join(item.encode() + b"\0" for item in dropped),
                )
            if kept:
                _git(
                    self.git_dir,
                    "update-index",
                    "--add",
                    "--remove",
                    "-z",
                    "--stdin",
                    work_tree=self.workspace,
                    index=index,
                    stdin=b"".join(item.encode() + b"\0" for item in kept),
                )
            self._indexed = set(kept)
            tree = _git(self.git_dir, "write-tree", work_tree=self.workspace, index=index)
            self._trees.append(tree.decode().strip())
            commit = (
                _git(self.git_dir, "commit-tree", self._trees[-1], "-m", f"step {step}")
                .decode()
                .strip()
            )
            _git(self.git_dir, "update-ref", ref, commit)
        except (OSError, RuntimeError) as exc:
            self.problem = f"the workspace snapshot failed at step {step}: {exc}"
            return None
        return commit

    def export(self, destination: Path) -> Path | None:
        """Write every snapshot to one git bundle.

        Returns:
            The bundle's path, or ``None`` when there are no snapshots.
        """
        if not self.available or not self.snapshots:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        _git(self.git_dir, "bundle", "create", str(destination), "--all")
        return destination

    def report(self) -> dict[str, Any]:
        """What the Job keeps about the snapshots.

        Returns:
            Whether they were taken, each step's commit, whether the files
            changed from the first snapshot to the last, the skipped files, and
            why there are none, if so.
        """
        return {
            "available": self.available,
            "cap_mib": self.cap_bytes // (1024 * 1024),
            "snapshots": {str(step): commit for step, commit in sorted(self.snapshots.items())},
            **({"changed": self._trees[0] != self._trees[-1]} if self._trees else {}),
            "skipped": [
                {"path": path, "step": step, "reason": reason}
                for path, (step, reason) in sorted(self.skipped.items())
            ],
            **({"problem": self.problem} if self.problem else {}),
        }


def checkout(bundle: Path, commit: str, destination: Path) -> list[str]:
    """Write the files of one snapshot from a bundle into an empty folder.

    Returns:
        The paths written, relative to ``destination``.

    Raises:
        RuntimeError: When git cannot read the bundle or the commit.
    """
    if not git_available():
        raise RuntimeError("git is not installed, so the workspace snapshot cannot be read")
    destination.mkdir(parents=True, exist_ok=True)
    scratch = destination.parent / f".{destination.name}.git"
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        _git(scratch, "init", "--bare", "--quiet")
        _git(
            scratch, "fetch", "--quiet", str(Path(bundle).resolve()), "refs/plural/*:refs/plural/*"
        )
        index = scratch / "index"
        _git(scratch, "read-tree", commit, index=index)
        _git(scratch, "checkout-index", "-a", "-f", work_tree=destination, index=index)
        listed = _git(scratch, "ls-tree", "-r", "-z", "--name-only", commit)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return [item for item in listed.decode().split("\0") if item]


def same_files(first: Mapping[str, bytes], second: Iterable[tuple[str, bytes]]) -> bool:
    """Whether two snapshots hold exactly the same files with the same bytes.

    Returns:
        True when they match byte for byte.
    """
    return dict(first) == dict(second)


__all__ = [
    "BUNDLE_FILE",
    "FINAL_REF",
    "IGNORED",
    "STEP_REF",
    "SnapshotEntry",
    "WorkspaceSnapshots",
    "checkout",
    "git_available",
    "same_files",
]
