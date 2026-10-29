"""Recording a local Job in the hosted project while it runs, and after."""

from __future__ import annotations

import json
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
from plural.local_models import LocalModelIdentity


class _Hosted:
    """The hosted API calls a tracker makes, recorded against one client Job."""

    project = "prj_test"

    def __init__(self, spec: JobSpec, *, fail: bool = False) -> None:
        plan = spec.plan()
        self.spec = spec
        self._trials = {f"hosted-{trial.trial_id}": trial for trial in plan.trials}
        self.fail = fail
        self.executions: dict[str, dict[str, Any]] = {}
        self.transitions: list[tuple[str, str]] = []
        self.heartbeats: list[list[str]] = []
        self.cancelled: list[str] = []
        self.gateway_keys: list[str] = []
        self.results: list[dict[str, Any]] = []

    def gateway_key(self, execution_id: str, *, ttl_seconds: int) -> str:
        self.gateway_keys.append(execution_id)
        return f"plural_gateway_{execution_id}"

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
            if "result" in body:
                self.results.append(body["result"])
        return {"status": body.get("status")}


def _job_trials(hosted: _Hosted) -> list[dict[str, Any]]:
    """Hosted Trials as the server lists them: display titles, plus the pins."""
    agents = {binding.agent_id: binding.agent.content_hash for binding in hosted.spec.agents}
    return [
        {
            "id": key,
            "task_name": f"Title of {trial.task_pin.name}",
            "agent_name": f"Title of {trial.agent_name}",
            "attempt": trial.attempt,
            "pins": {
                "task": trial.task_pin.model_dump(mode="json"),
                "agent": agents[trial.agent_id],
            },
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
        gateway_key = staticmethod(hosted.gateway_key)

    class Studio:
        project = hosted.project
        jobs = Jobs()
        trials = Trials()
        request = staticmethod(hosted.request)

    return Studio()


async def _tracked_run(
    tmp_path: Path,
    hosted: _Hosted,
    spec: JobSpec,
    *,
    environ: dict[str, str] | None = None,
    model_identities: dict[str, LocalModelIdentity] | None = None,
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
    result = await JobRunner(
        spec,
        provider=FakeProvider("docker", delay=0.05),
        store=store,
        environ=environ or {},
        gateway_keys=tracker.gateway_key,
        model_identities=model_identities,
    ).run()
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


async def test_each_recorded_execution_gets_its_own_gateway_key(tmp_path: Path) -> None:
    spec = _spec([_task("case-0"), _task("case-1")], concurrency=2)
    hosted = _Hosted(spec)

    _, errors = await _tracked_run(tmp_path, hosted, spec, environ={"PLURAL_API_KEY": "own"})

    assert errors == []
    assert sorted(hosted.gateway_keys) == sorted(
        record["id"] for record in hosted.executions.values()
    )


async def test_a_recorded_trial_carries_the_local_model_it_ran(tmp_path: Path) -> None:
    spec = _spec([_task("case-0")])
    identity = LocalModelIdentity(
        endpoint="http://localhost:2080/v1",
        requested="mlx-community/Qwen3-8B-4bit",
        server="mlx-lm",
        method="behavior",
        fingerprint="SHA256:abc",
        trust="confirmed",
    )
    hosted = _Hosted(spec)

    _, errors = await _tracked_run(
        tmp_path, hosted, spec, model_identities={spec.agents[0].name: identity}
    )

    assert errors == []
    assert [item["model_identity"]["fingerprint"] for item in hosted.results] == ["SHA256:abc"]
    assert hosted.results[0]["model_identity"]["trust"] == "confirmed"


async def test_pushing_a_tracked_job_records_nothing_twice(tmp_path: Path) -> None:
    spec = _spec([_task("case-0"), _task("case-1")])
    hosted = _Hosted(spec)
    store, _ = await _tracked_run(tmp_path, hosted, spec)
    before = len(hosted.transitions)

    published = publish_job(_studio(hosted), store, spec.job_id, "hosted-job")

    assert {item.status for item in published} == {"succeeded"}
    assert len(hosted.executions) == 2
    assert len(hosted.transitions) == before


async def test_a_job_run_before_an_upgrade_is_recorded_with_each_attempts_time(
    tmp_path: Path,
) -> None:
    spec = _spec([_task("case-0"), _task("case-1")])
    store, errors = await _tracked_run(tmp_path, _Hosted(spec, fail=True), spec)
    assert errors == ["hosted service unavailable"]
    ran: list[float] = []
    for path in sorted((store.job_path(spec.job_id) / "trials").glob("*/executions/*/result.json")):
        result = json.loads(path.read_text())
        # An older Plural hashed the binding's Harness package without a newer field.
        result["receipt"]["agent_digest"] = "sha256:" + "0" * 64
        ran.append(result["receipt"]["timings"]["total_seconds"])
        path.write_text(json.dumps(result))
    hosted = _Hosted(spec)

    published = publish_job(_studio(hosted), store, spec.job_id, "hosted-job")

    assert {item.status for item in published} == {"succeeded"}
    assert sorted(item["timings"]["total_seconds"] for item in hosted.results) == sorted(ran)


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


@pytest.mark.parametrize("flag", ["--hosted", "--follow"])
def test_plural_never_runs_a_job_on_its_servers(flag: str) -> None:
    result = CliRunner().invoke(app, ["run", "--benchmark", "b", "--agent", "a", flag])
    assert result.exit_code == 1
    assert "does not run Jobs on its servers" in result.output
    assert "--record" in result.output


def test_an_evaluation_track_sets_and_checks_the_attempts() -> None:
    from plural import Benchmark, EvaluationTrack
    from plural.project import ProjectError
    from plural.project.runs import RunRequest, _track_attempts

    benchmark = Benchmark.model_construct(
        name="wordle",
        tracks=(
            EvaluationTrack(
                id="controlled", name="Controlled", kind="models", instructions="none", attempts=3
            ),
        ),
    )
    on_track = RunRequest(benchmark="wordle", evaluation_track="controlled")
    assert _track_attempts(benchmark, on_track) == 3
    assert _track_attempts(benchmark, RunRequest(benchmark="wordle")) is None
    with pytest.raises(ProjectError, match="no evaluation track 'open'"):
        _track_attempts(benchmark, RunRequest(benchmark="wordle", evaluation_track="open"))
    with pytest.raises(ProjectError, match="requires 3 attempt"):
        _track_attempts(
            benchmark,
            RunRequest(benchmark="wordle", evaluation_track="controlled", attempts=2),
        )
    with pytest.raises(ProjectError, match="needs --benchmark"):
        _track_attempts(object(), on_track)


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


def test_an_upload_that_still_fails_marks_the_hosted_job_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plural.errors import PluralError
    from plural.execution.report import PublishError
    from plural.project.runs import Tracking, _finish_recording

    transitions: list[tuple[str, str, dict[str, Any]]] = []

    class Jobs:
        def transition(self, job_id: str, status: str, **fields: Any) -> dict[str, Any]:
            transitions.append((job_id, status, fields))
            return {}

    class Studio:
        jobs = Jobs()

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise PublishError("No hosted Trial for Task t attempt 1 with Agent a")

    monkeypatch.setattr("plural.execution.report.publish_job", refuse)
    tracking = Tracking(studio=Studio(), hosted_job_id="job_1", errors=["first"])  # type: ignore[arg-type]
    _finish_recording(tracking, None, "local-1", {})
    assert tracking.retryable is False
    assert transitions[0][:2] == ("job_1", "failed")
    assert transitions[0][2]["error_code"] == "recording_incomplete"

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise PluralError("Service unavailable", status_code=503)

    monkeypatch.setattr("plural.execution.report.publish_job", unavailable)
    tracking = Tracking(studio=Studio(), hosted_job_id="job_2", errors=["first"])  # type: ignore[arg-type]
    _finish_recording(tracking, None, "local-2", {})
    assert tracking.retryable is True

    monkeypatch.setattr("plural.execution.report.publish_job", lambda *a, **k: [])
    tracking = Tracking(studio=Studio(), hosted_job_id="job_3", errors=["first"])  # type: ignore[arg-type]
    _finish_recording(tracking, None, "local-3", {})
    assert tracking.errors == []
