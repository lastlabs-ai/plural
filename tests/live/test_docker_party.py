"""A real party in Docker: one shared thread, and no seat can see another's side."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from plural import Agent, Environment, Job, JobStore, Party, Runtime, Task
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
