"""Recording a local Job in the hosted project while it runs, and after."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fakes import FakeProvider
from project_fixtures import write_project
from test_concurrency_and_bootstrap import _spec, _task
from typer.testing import CliRunner

from plural.cli.main import app
from plural.execution import JobRunner, JobStore
from plural.execution.report import (
    HostedTracker,
    agent_pins,
    execution_key,
    publish_job,
)
from plural.jobs import JobSpec


class _Hosted:
    """The hosted API calls a tracker makes, recorded against one client Job."""

    project = "prj_test"

    def __init__(self, spec: JobSpec, *, fail: bool = False) -> None:
        plan = spec.plan()
        self._trials = {f"hosted-{trial.trial_id}": trial for trial in plan.trials}
        self.fail = fail
        self.executions: dict[str, dict[str, Any]] = {}
        self.transitions: list[tuple[str, str]] = []
        self.heartbeats: list[list[str]] = []
        self.cancelled: list[str] = []

    def get(self, trial_id: str) -> dict[str, Any]:
        trial = self._trials[trial_id]
        return {
            "pins": {
                "verifiers": [
                    {"content_hash": digest, "revision_id": f"vr-{index}"}
                    for index, digest in enumerate(trial.verifier_digests)
                ]
            }
        }

    def create_execution(
        self, trial_id: str, *, idempotency_key: str, worker_id: str | None = None
    ) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("hosted service unavailable")
        record = self.executions.setdefault(
            idempotency_key,
            {"id": f"ex-{len(self.executions)}", "status": "queued", "trial": trial_id},
        )
        return dict(record)

    def cancel(self, job_id: str) -> dict[str, Any]:
        self.cancelled.append(job_id)
        return {}

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        body = kwargs.get("json") or {}
        if path == "/workers/heartbeat":
            self.heartbeats.append(list(body["execution_ids"]))
        elif path.endswith("/transition"):
            execution_id = path.split("/")[2]
            record = next(item for item in self.executions.values() if item["id"] == execution_id)
            record["status"] = body["status"]
            self.transitions.append((execution_id, body["status"]))
        return {"status": body.get("status")}


def _job_trials(hosted: _Hosted) -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "task_name": trial.task_pin.name,
            "agent_name": trial.agent_name,
            "attempt": trial.attempt,
        }
        for key, trial in hosted._trials.items()
    ]


def _studio(hosted: _Hosted) -> Any:
    class Jobs:
        def trials(self, job_id: str) -> list[dict[str, Any]]:
            return _job_trials(hosted)

        def cancel(self, job_id: str) -> dict[str, Any]:
            return hosted.cancel(job_id)

    class Trials:
        get = staticmethod(hosted.get)
        create_execution = staticmethod(hosted.create_execution)

    class Studio:
        project = hosted.project
        jobs = Jobs()
        trials = Trials()
        request = staticmethod(hosted.request)

    return Studio()


async def _tracked_run(
    tmp_path: Path, hosted: _Hosted, spec: JobSpec
) -> tuple[JobStore, list[str]]:
    store = JobStore(tmp_path / "jobs")
    tracker = HostedTracker(
        _studio(hosted),
        store,
        spec,
        spec.plan(),
        "hosted-job",
        agents=agent_pins(spec),
        heartbeat_seconds=0.01,
    )
    store.on_event = tracker.observe
    result = await JobRunner(spec, provider=FakeProvider("docker", delay=0.05), store=store).run()
    assert result.status == "succeeded"
    return store, tracker.close()


async def test_each_execution_is_opened_as_it_starts_and_finished_as_it_ends(
    tmp_path: Path,
) -> None:
    spec = _spec([_task(f"case-{index}") for index in range(3)], concurrency=3)
    hosted = _Hosted(spec)

    store, errors = await _tracked_run(tmp_path, hosted, spec)

    assert errors == []
    keys = {execution_key(spec.job_id, trial.trial_id, 0) for trial in spec.plan().trials}
    assert set(hosted.executions) == keys
    for record in hosted.executions.values():
        steps = [status for execution, status in hosted.transitions if execution == record["id"]]
        assert steps == ["provisioning", "running", "verifying", "succeeded"]
    # Running executions reported liveness while the Job ran.
    assert any(hosted.heartbeats)


async def test_pushing_a_tracked_job_records_nothing_twice(tmp_path: Path) -> None:
    spec = _spec([_task("case-0"), _task("case-1")])
    hosted = _Hosted(spec)
    store, _ = await _tracked_run(tmp_path, hosted, spec)
    before = len(hosted.transitions)

    published = publish_job(_studio(hosted), store, spec.job_id, "hosted-job")

    assert {item.status for item in published} == {"succeeded"}
    assert len(hosted.executions) == 2
    assert len(hosted.transitions) == before


async def test_reporting_failures_never_stop_the_local_run(tmp_path: Path) -> None:
    spec = _spec([_task("case-0")])
    hosted = _Hosted(spec, fail=True)

    _, errors = await _tracked_run(tmp_path, hosted, spec)

    assert errors == ["hosted service unavailable"]


def test_an_interrupted_run_cancels_its_hosted_job(tmp_path: Path) -> None:
    spec = _spec([_task("case-0")])
    hosted = _Hosted(spec)
    tracker = HostedTracker(
        _studio(hosted),
        JobStore(tmp_path / "jobs"),
        spec,
        spec.plan(),
        "hosted-job",
        agents=agent_pins(spec),
    )

    assert tracker.close(cancelled=True) == []
    assert hosted.cancelled == ["hosted-job"]


def test_track_and_hosted_are_different_ways_to_record_a_job() -> None:
    result = CliRunner().invoke(
        app, ["run", "--benchmark", "b", "--agent", "a", "--hosted", "--track"]
    )
    assert result.exit_code == 1
    assert "Use --track to run here and record it" in result.output


def test_only_a_finished_local_job_can_be_pushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = write_project(tmp_path / "support-desk")
    job = project.root / ".plural" / "jobs" / "job_running"
    job.mkdir(parents=True)
    (job / "run.json").write_text(
        '{"job_id": "job_running", "created_at": "", "source": "task/t", "agent": "agent/a", '
        '"model": "m", "harness": "native"}'
    )
    monkeypatch.chdir(project.root)

    unknown = CliRunner().invoke(app, ["job", "push", "job_missing"])
    running = CliRunner().invoke(app, ["job", "push", "job_running"])

    assert unknown.exit_code == 1
    assert "No local Job 'job_missing'" in unknown.output
    assert running.exit_code == 1
    assert "has not finished" in running.output
