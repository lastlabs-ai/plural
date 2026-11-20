"""Detached runs: what may be detached, what is uploaded, and syncing a Job back."""

from __future__ import annotations

import asyncio
import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plural.inspector.run import INSPECTING_FILE, one_inspection
from plural.project import detach
from plural.project.layout import ProjectError


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8005",
        "http://127.0.0.1:8005",
        "http://10.0.0.4",
        "http://192.168.1.20:8000",
        "http://host.docker.internal:8005",
        "http://laptop.local",
        "",
    ],
)
def test_refuses_a_url_on_this_machine(url: str) -> None:
    with pytest.raises(ProjectError, match="never tunnels"):
        detach.refuse_unreachable(url)


def test_accepts_a_hosted_url() -> None:
    detach.refuse_unreachable("https://api.pluralintel.com")


def test_archive_leaves_out_jobs_history_and_caches(tmp_path: Path) -> None:
    for name in [
        "plural.yaml",
        "agents/a/agent.yaml",
        ".plural/jobs/job_1/result.json",
        ".git/HEAD",
        ".venv/bin/python",
        "apps/x/__pycache__/m.pyc",
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    with tarfile.open(fileobj=io.BytesIO(detach.project_archive(tmp_path))) as archive:
        names = sorted(archive.getnames())
    assert names == ["agents/a/agent.yaml", "plural.yaml"]


class _Provider:
    """A sandbox that holds one Job folder and a runner that is alive or done."""

    def __init__(self, job_id: str, *, alive: bool) -> None:
        self.job_id = job_id
        self.alive = alive
        self.commands: list[str] = []
        self.destroyed = False

    async def attach(self, sandbox_id: str) -> Any:
        return SimpleNamespace(sandbox_id=sandbox_id)

    async def exec(self, handle: Any, request: Any) -> Any:
        command = request.command[-1]
        self.commands.append(command)
        out = ""
        if "kill -0" in command:
            out = "alive" if self.alive else "done"
        return SimpleNamespace(exit_code=0, stdout=out.encode(), stderr=b"", timed_out=False)

    async def download_files(self, handle: Any, paths: list[str], *, root: str) -> list[Any]:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            data = json.dumps({"day": 140}).encode()
            info = tarfile.TarInfo(f"{self.job_id}/trials/trl_1/run/journal.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        return [SimpleNamespace(data=buffer.getvalue())]

    async def destroy(self, handle: Any) -> None:
        self.destroyed = True


def _workspace(tmp_path: Path, job_id: str) -> Any:
    jobs = tmp_path / "jobs"
    (jobs / job_id).mkdir(parents=True)
    record = detach.Detached(
        job_id=job_id,
        provider="daytona",
        sandbox_id="sbx",
        pid=290,
        project="/p",
        started_at="2026-11-20T00:00:00+00:00",
        key_expires_at="2026-11-21T00:00:00+00:00",
        synced_at=None,
        finished=False,
    )
    (jobs / job_id / detach.DETACHED_FILE).write_text(json.dumps(record.to_json()))
    return SimpleNamespace(project=SimpleNamespace(jobs_dir=jobs, root=tmp_path))


@pytest.mark.parametrize("alive", [True, False])
def test_sync_copies_the_job_back_and_ends_it_once_finished(tmp_path: Path, alive: bool) -> None:
    job_id = "job_" + "a" * 24
    workspace = _workspace(tmp_path, job_id)
    provider = _Provider(job_id, alive=alive)
    ended: list[str] = []

    record = asyncio.run(
        detach.sync(
            workspace, job_id, provider=provider, on_finish=lambda r: ended.append(r.job_id)
        )
    )

    journal = workspace.project.jobs_dir / job_id / "trials/trl_1/run/journal.json"
    assert json.loads(journal.read_text()) == {"day": 140}
    assert record is not None and record.synced_at
    assert record.finished is (not alive)
    assert provider.destroyed is (not alive)
    assert ended == ([] if alive else [job_id])
    again = asyncio.run(detach.sync(workspace, job_id, provider=provider))
    assert again is not None and len(provider.commands) == (4 if alive else 2)


def test_a_second_inspection_of_a_job_is_refused_while_one_runs(tmp_path: Path) -> None:
    job = tmp_path / "job_x"
    job.mkdir()
    (job / INSPECTING_FILE).write_text(json.dumps({"pid": os.getppid()}))
    with pytest.raises(ProjectError, match="already being inspected"), one_inspection(job):
        pass

    (job / INSPECTING_FILE).write_text(json.dumps({"pid": 2**22 + 12345}))
    with one_inspection(job):
        assert json.loads((job / INSPECTING_FILE).read_text())["pid"] == os.getpid()
    assert not (job / INSPECTING_FILE).exists()
