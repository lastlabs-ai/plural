"""Restoring a workspace snapshot: symbolic links, and each seat's files as the seat's own."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from plural.apps.workspace import (
    WorkspaceSnapshots,
    git_available,
    snapshot_entries,
    snapshot_files,
)
from plural.execution.seats import restore_workspace
from plural.sandbox import ExecRequest, ExecResult, FileUpload

pytestmark = pytest.mark.skipif(not git_available(), reason="git is not installed")


class _Runtime:
    """Runs a Runtime's commands on this machine, with ``/workspace`` moved under ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.users: list[tuple[str | None, str]] = []

    def _here(self, value: str) -> str:
        return str(self.root) + value if value.startswith("/workspace") else value

    async def upload_files(self, handle: Any, files: list[FileUpload], *, root: str) -> None:
        for item in files:
            path = Path(self._here(root)) / item.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(item.data)
            path.chmod(item.mode)
            self.users.append((None, f"upload {root}/{item.path}"))

    async def exec(self, handle: Any, request: ExecRequest) -> ExecResult:
        command = [sys.executable, *(self._here(item) for item in request.command[1:])]
        done = subprocess.run(command, capture_output=True)
        self.users.append((request.user, request.command[2]))
        return ExecResult(
            exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr, duration_seconds=0
        )


def _snapshot(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "workspace"
    (workspace / "seats" / "north").mkdir(parents=True)
    (workspace / "notes.txt").write_text("shared\n")
    (workspace / "run.sh").write_text("#!/bin/sh\n")
    (workspace / "run.sh").chmod(0o755)
    (workspace / "latest").symlink_to("notes.txt")
    (workspace / "host-secret").symlink_to(tmp_path / "secret.txt")
    (tmp_path / "secret.txt").write_text("never read\n")
    (workspace / "seats" / "north" / "plan.md").write_text("north's plan\n")
    (workspace / "seats" / "north" / "current").symlink_to("plan.md")
    snapshots = WorkspaceSnapshots(workspace, tmp_path / "store")
    commit = snapshots.take(1)
    assert commit is not None
    bundle = snapshots.bundle(tmp_path / "workspace.bundle")
    assert bundle is not None
    return bundle, commit


def test_symbolic_links_are_restored_and_never_followed_on_the_host(tmp_path: Path) -> None:
    bundle, commit = _snapshot(tmp_path)
    entries = {item.path: item for item in snapshot_entries(bundle, commit)}
    assert entries["latest"].link == "notes.txt" and entries["latest"].data == b""
    assert entries["run.sh"].mode == 0o755 and entries["notes.txt"].mode == 0o644
    # A Verifier's view of the workspace holds the files, never what a link points to.
    files = snapshot_files(bundle, commit)
    assert files["notes.txt"] == b"shared\n"
    assert "host-secret" not in files and "latest" not in files

    runtime = _Runtime(tmp_path / "runtime")
    (runtime.root / "workspace").mkdir(parents=True)
    asyncio.run(restore_workspace(runtime, None, list(entries.values()), {}))  # type: ignore[arg-type]
    restored = runtime.root / "workspace"
    assert os.readlink(restored / "latest") == "notes.txt"
    assert (restored / "latest").read_text() == "shared\n"
    assert os.access(restored / "run.sh", os.X_OK)
    assert os.readlink(restored / "seats" / "north" / "current") == "plan.md"


def test_a_seats_files_are_restored_by_the_seats_own_user(tmp_path: Path) -> None:
    bundle, commit = _snapshot(tmp_path)
    runtime = _Runtime(tmp_path / "runtime")
    (runtime.root / "workspace" / "seats" / "north").mkdir(parents=True)
    entries = snapshot_entries(bundle, commit)
    asyncio.run(
        restore_workspace(runtime, None, entries, {"north": "plural-seat-north"})  # type: ignore[arg-type]
    )
    restored = runtime.root / "workspace" / "seats" / "north"
    assert (restored / "plan.md").read_text() == "north's plan\n"
    assert os.readlink(restored / "current") == "plan.md"
    # Shared files are uploaded in place; the seat's are staged, then placed by its user.
    uploads = [what for user, what in runtime.users if what.startswith("upload")]
    assert "upload /workspace/notes.txt" in uploads
    assert not any(what.startswith("upload /workspace/seats/") for what in uploads)
    placed = [user for user, what in runtime.users if "symlink" in what]
    assert "plural-seat-north" in placed
    assert not (runtime.root / "workspace" / ".restore-stage").exists()


def test_the_snapshot_report_says_whether_the_files_changed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("before\n")
    snapshots = WorkspaceSnapshots(workspace, tmp_path / "store")
    snapshots.take(0)
    snapshots.take(1)
    snapshots.take_final()
    assert snapshots.report()["changed"] is False
    (workspace / "notes.txt").write_text("after\n")
    snapshots.take_final()
    assert snapshots.report()["changed"] is True
