"""A real party in Docker: one shared thread, and no seat can see another's side."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from plural import Agent, Environment, Job, Party, Runtime, Task
from plural.execution import JobStore
from plural.verifiers import DeterministicVerifier, Episode, VerifierOutput

sys.path.insert(0, str(Path(__file__).parent / "party"))
from harness.spy import Spy  # noqa: E402
from thread_app import Thread  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("PLURAL_RUN_DOCKER_TESTS") != "1",
        reason="set PLURAL_RUN_DOCKER_TESTS=1 to opt in",
    ),
]


def _played(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1.0)


def test_seats_share_one_thread_and_nothing_else(tmp_path: Path) -> None:
    table = Environment(
        name="thread",
        apps=[Thread()],
        runtime=Runtime.docker(image="python:3.12-slim"),
        party=Party(min=2, max=2),
    )
    task = Task(
        name="chat",
        instructions="Post when it is your turn.",
        environment=table,
        verifiers=[DeterministicVerifier(name="played", check=_played)],
    )
    ada = Agent(name="ada", model="openai/gpt-5.6-luna", harness=Spy())
    bea = Agent(name="bea", model="openai/gpt-5.6-luna", harness=Spy())
    job = Job(task, agents=[ada, bea], store=JobStore(tmp_path / "store"), api_key="unused")
    (trial,) = job.run().trials
    assert trial.status == "succeeded", trial.error_message
    assert trial.seat_isolation == "os_user"
    assert trial.app_isolation == "os_user"
    for seat in ("seat_1", "seat_2"):
        found = list((tmp_path / "store").glob(f"**/artifacts/seats/{seat}/result.json"))
        report = json.loads(json.loads(found[0].read_text())["response"])
        assert not any(report["seen"].values()), (seat, report["seen"])
        assert report["last"]["note"] == f"secret-for-{seat}"
        assert [item["seat"] for item in report["last"]["thread"]] == [
            "seat_1",
            "seat_2",
            "seat_1",
            "seat_2",
        ]


async def test_a_seats_restored_files_belong_to_the_seats_user() -> None:
    from plural.apps.workspace import SnapshotEntry
    from plural.execution.policy import sandbox_requirements_for
    from plural.execution.seats import prepare_seats, restore_workspace, seat_workspace
    from plural.sandbox import DockerProvider, ExecRequest, FileUpload

    table = Environment(
        name="thread",
        apps=[Thread()],
        runtime=Runtime.docker(image="python:3.12-slim"),
        party=Party(min=2, max=2),
    )
    provider = DockerProvider()
    handle = await provider.create(sandbox_requirements_for(table.definition()))
    try:
        await provider.isolate_apps(handle)
        await provider.upload_files(
            handle, [FileUpload(path="task.json", data=b"{}")], root="/workspace"
        )
        users = await provider.isolate_seats(handle, ["north", "south"])
        assert await prepare_seats(provider, handle, users, shared=("/workspace/environment",))
        entries = [
            SnapshotEntry(path="seats/north/plan.md", data=b"north's plan\n"),
            SnapshotEntry(path="seats/north/current", link="plan.md"),
            SnapshotEntry(path="notes.txt", data=b"shared\n"),
        ]
        await restore_workspace(provider, handle, entries, users)
        north = seat_workspace("north")

        async def run(command: str, user: str | None = None) -> str:
            result = await provider.exec(
                handle,
                ExecRequest(command=("sh", "-c", command), timeout_seconds=30, user=user),
            )
            assert result.exit_code == 0, result.stderr
            return result.stdout.decode().strip()

        assert await run(f"stat -c %u:%g {north}/plan.md", users["north"]) == users["north"]
        assert await run(f"stat -c %u:%g {north}/current", users["north"]) == users["north"]
        assert await run(f"readlink {north}/current", users["north"]) == "plan.md"
        await run(f"echo more >> {north}/plan.md", user=users["north"])
        denied = await provider.exec(
            handle,
            ExecRequest(
                command=("cat", f"{north}/plan.md"), timeout_seconds=30, user=users["south"]
            ),
        )
        assert denied.exit_code != 0
    finally:
        await provider.destroy(handle)
