"""Taking versions of a folder during an episode, and restoring them later.

Plural snapshots the Agent's workspace after every step so a Checkpoint can
put the files back as they stood after step *k*. A Volume's memory will be
versioned the same way. Both sides of that sit behind two interfaces, so the
code that takes, keeps, and restores snapshots never depends on how one is
stored:

- A :class:`Snapshotter` takes immutable versions of a live folder while the
  episode runs and exports them as one archive when it ends. The App host
  holds it, where the Harness cannot read it.
- A :class:`SnapshotArchive` reads versions back from an exported archive:
  every file of one version, or the version written into a folder.

:class:`plural.apps.workspace.WorkspaceSnapshots` and :class:`GitBundle` are
the implementations for the workspace, over a hidden git repository and the
git bundle it exports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SnapshotEntry:
    """One file of a snapshot, as it is restored."""

    path: str
    """Relative to the snapshotted folder."""
    data: bytes = b""
    mode: int = 0o644
    """``0o755`` for an executable file, else ``0o644``."""
    link: str | None = None
    """For a symbolic link, what it points to; it has no data then."""


@runtime_checkable
class Snapshotter(Protocol):
    """Takes immutable versions of one folder while an episode runs."""

    @property
    def available(self) -> bool:
        """Whether versions are being taken."""
        ...

    def snapshot(self, step: int) -> str | None:
        """Take the folder as it stands now as step ``step``'s version.

        Returns:
            The version id, or ``None`` when snapshots are off or failed.
        """
        ...

    def snapshot_final(self) -> str | None:
        """Take the folder as the episode left it.

        Returns:
            The version id, or ``None`` when snapshots are off or failed.
        """
        ...

    def export(self, destination: Path) -> Path | None:
        """Write every version to one archive at ``destination``.

        Returns:
            The archive, or ``None`` when there is nothing to export.
        """
        ...

    def report(self) -> dict[str, Any]:
        """What the Job keeps about the versions.

        Returns:
            At least ``available``, and ``snapshots``: each step's version id by step.
        """
        ...


@runtime_checkable
class SnapshotArchive(Protocol):
    """Reads the versions an exported archive holds."""

    def restore(self, version: str, destination: Path) -> list[str]:
        """Write one version's files into an empty folder.

        Returns:
            The paths written, relative to ``destination``.
        """
        ...

    def entries(self, version: str) -> list[SnapshotEntry]:
        """Every file and symbolic link of one version, as it is restored.

        Returns:
            One entry per file or link.
        """
        ...

    def files(self, version: str) -> dict[str, bytes]:
        """Every regular file of one version. A symbolic link is never followed.

        Returns:
            Each path with its bytes.
        """
        ...


class GitBundle:
    """A :class:`SnapshotArchive` over the git bundle a workspace exports.

    Args:
        path: The bundle, such as a Trial's ``workspace.bundle``.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def restore(self, version: str, destination: Path) -> list[str]:
        """Write one snapshot's files into an empty folder.

        Returns:
            The paths written, relative to ``destination``.
        """
        from plural.apps.workspace import checkout

        return checkout(self.path, version, destination)

    def entries(self, version: str) -> list[SnapshotEntry]:
        """Every file and symbolic link of one snapshot.

        Returns:
            One entry per file or link.
        """
        import os
        import tempfile

        with tempfile.TemporaryDirectory(prefix="plural-snapshot-") as folder:
            target = Path(folder) / "files"
            entries = []
            for name in self.restore(version, target):
                path = target / name
                if path.is_symlink():
                    entries.append(SnapshotEntry(path=name, link=os.readlink(path)))
                elif path.is_file():
                    mode = 0o755 if os.stat(path).st_mode & 0o111 else 0o644
                    entries.append(SnapshotEntry(path=name, data=path.read_bytes(), mode=mode))
            return entries

    def files(self, version: str) -> dict[str, bytes]:
        """Every regular file of one snapshot.

        Returns:
            Each path with its bytes.
        """
        return {item.path: item.data for item in self.entries(version) if item.link is None}


def version_at(report: Mapping[str, Any], step: int) -> str | None:
    """The version that covers ``step``, from a :meth:`Snapshotter.report`.

    A step that changed nothing still has its own version, so this is exact;
    older reports fall back to the latest earlier step.

    Returns:
        The version id, or ``None`` when no version covers the step.
    """
    versions = {
        int(key): str(value)
        for key, value in dict(report.get("snapshots") or {}).items()
        if str(key).isdigit()
    }
    earlier = [key for key in versions if key <= step]
    return versions[max(earlier)] if earlier else None


__all__ = [
    "GitBundle",
    "SnapshotArchive",
    "SnapshotEntry",
    "Snapshotter",
    "version_at",
]
