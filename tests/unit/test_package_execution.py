from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeProvider

from plural.agents import AgentBinding, AgentDefinition
from plural.common import (
    ErrorCode,
    ExecutionTarget,
    FileDeclaration,
    HarnessBinding,
    HarnessPackage,
    HarnessProtocol,
    PackageSource,
)
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.execution import JobRunner, JobStore
from plural.execution.engine import _bounded_artifact_evidence
from plural.jobs import BenchmarkJobSource, JobMode, JobSpec, RetryPolicy, TaskJobSource
from plural.sandbox import (
    DownloadedFile,
    ExecRequest,
    ExecResult,
    NetworkMode,
    SandboxHandle,
)
from plural.tasks import BenchmarkDefinition, TaskDefinition
from plural.verifiers import (
    AgentVerifier,
    DeterministicVerifier,
    HumanVerifier,
    RubricCriterion,
    VerifierRuntime,
    WeightedVerifier,
)


class JudgeProvider(FakeProvider):
    """No-network provider that emulates an AgentVerifier model response."""

    def __init__(self) -> None:
        super().__init__("docker")
        self.judge_input: dict[str, Any] | None = None

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        if request.stdin is not None:
            return await super().exec(handle, request)
        payload = json.loads(self.files[handle.sandbox_id][".plural/verifier-input.json"])
        verifier = payload["agent_verifier"]
        self.judge_input = payload["judge_input"]
        assert verifier["criteria"] == [
            {
                "name": "quality",
                "description": "The answer is correct and concise.",
                "weight": 1.0,
                "min_score": 0.0,
                "max_score": 1.0,
            }
        ]
        assert self.judge_input["environment_view"] == {
            "observation": {"text": "done"},
            "state": {"step": 1},
        }
        requested = self.judge_input["requested_artifacts"]
        assert requested[0]["name"] == "result.json"
        assert json.loads(requested[0]["content"]) == {"answer": 42}
        assert self.judge_input["final"]["name"] == "result.json"
        self.files[handle.sandbox_id]["agent-verifier-result.json"] = json.dumps(
            {
                "score": 0.8,
                "scores": {"quality": 0.8},
                "evidence": ["result.json answer=42", "observation.text=done"],
                "feedback": "Correct and concise.",
            }
        ).encode()
        return ExecResult(
            exit_code=0,
            stdout=b"judge used judge-secret",
            duration_seconds=0.001,
        )


def exact_verifier(provider: str) -> DeterministicVerifier:
    return DeterministicVerifier(
        name=f"exact-{provider}",
        command=("python", "verify.py"),
        runtime=VerifierRuntime(provider=provider),
    )


def test_agent_verifier_artifact_evidence_is_requested_readable_and_bounded() -> None:
    evidence = _bounded_artifact_evidence(
        (
            DownloadedFile(path="requested.txt", data=b"x" * 40_000),
            DownloadedFile(path="unrequested.txt", data=b"do not disclose"),
            DownloadedFile(path="binary.bin", data=b"\xff\xfe"),
        ),
        ("requested.txt", "binary.bin", "missing.txt"),
    )

    assert [item["name"] for item in evidence] == [
        "requested.txt",
        "binary.bin",
        "missing.txt",
    ]
    assert len(evidence[0]["content"]) == 32_000
    assert evidence[0]["truncated"] is True
    assert evidence[1]["readable"] is False
    assert evidence[2] == {"name": "missing.txt", "available": False}


def make_task(name: str, provider: str) -> TaskDefinition:
    target = ExecutionTarget.REMOTE if provider == "remote" else ExecutionTarget.DOCKER
    environment = EnvironmentDefinition(
        name=f"env-{name}",
        runtime=EnvironmentRuntime(provider=provider, targets=frozenset({target})),
    )
    return TaskDefinition(
        task_id=name,
        instructions=f"Solve {name}",
        environment=environment,
        verifiers=(WeightedVerifier(verifier=exact_verifier(provider)),),
        info={"question": name},
    )


async def test_agent_verifier_scores_configured_criteria_with_contracted_evidence(
    tmp_path: Path,
) -> None:
    provider = JudgeProvider()
    environment = EnvironmentDefinition(
        name="judge-world",
        observation_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
        state_schema={
            "type": "object",
            "properties": {"step": {"type": "integer"}},
        },
        runtime=EnvironmentRuntime(
            provider="docker",
            targets=frozenset({ExecutionTarget.DOCKER}),
        ),
    )
    verifier = AgentVerifier(
        name="quality-judge",
        model="openai/gpt-5.6-luna",
        instructions="Judge only the supplied evidence.",
        criteria=(
            RubricCriterion(
                name="quality",
                description="The answer is correct and concise.",
            ),
        ),
        runtime=VerifierRuntime(provider="docker", network=NetworkMode.PUBLIC),
    )
    task = TaskDefinition(
        task_id="judge-me",
        instructions="Return the answer.",
        environment=environment,
        verifiers=(WeightedVerifier(verifier=verifier),),
    )
    spec = JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
    )
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(
        spec,
        provider=provider,
        store=store,
        environ={"OPENAI_API_KEY": "judge-secret"},
    ).run()

    assert result.status == "succeeded"
    judged = result.trials[0].verifier_results[0]
    assert judged.score == 0.8
    assert judged.scores == {"quality": 0.8}
    assert judged.evidence == ("result.json answer=42", "observation.text=done")
    execution = store.trial_path(spec.plan().trials[0]) / "executions/0"
    assert "judge-secret" not in (execution / "logs/verifier.stdout.log").read_text()
    assert "***" in (execution / "logs/verifier.stdout.log").read_text()


async def test_cross_environment_scheduler_uses_each_runtime_and_bounds_concurrency(
    tmp_path: Path,
) -> None:
    docker = FakeProvider("docker", delay=0.01)
    remote = FakeProvider("remote", delay=0.01)
    tasks = (make_task("one", "docker"), make_task("two", "remote"))
    spec = JobSpec(
        source=BenchmarkJobSource(benchmark=BenchmarkDefinition(name="mixed", tasks=tasks)),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
        attempts=2,
        concurrency=4,
        per_runtime_concurrency=1,
    )
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(
        spec,
        providers={"docker": docker, "remote": remote},
        store=store,
    ).run()
    assert result.status == "succeeded"
    assert docker.harness_runs == remote.harness_runs == 2
    assert docker.max_active == remote.max_active == 1
    events = tuple(store.events(spec.job_id))
    assert [item.sequence for item in events] == list(range(1, len(events) + 1))
    assert events[-1].type == "completed"
    assert result.benchmark is not None
    assert result.benchmark.name == "mixed"
    assert result.aggregates[0].count == 4
    assert result.aggregates[0].successes == 4
    assert result.aggregates[0].mean_score == 1
    assert result.aggregates[0].total_cost == pytest.approx(0.04)
    assert result.aggregates[0].mean_latency_seconds is not None


async def test_human_verifier_yields_awaiting_review(tmp_path: Path) -> None:
    environment = EnvironmentDefinition(name="review")
    task = TaskDefinition(
        task_id="review-me",
        instructions="Write an answer",
        environment=environment,
        verifiers=(
            WeightedVerifier(
                verifier=HumanVerifier(
                    name="human",
                    rubric=(RubricCriterion(name="quality", description="Answer quality"),),
                )
            ),
        ),
    )
    spec = JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
    )
    job = JobRunner(
        spec,
        provider=FakeProvider("docker"),
        store=JobStore(tmp_path / "jobs"),
    )
    result = await job.run()
    assert result.status == "awaiting_review"
    assert result.trials[0].status == "awaiting_review"
    assert result.trials[0].verifier_results[0].kind == "human"
    trial = spec.plan().trials[0]
    execution = job.store.trial_path(trial) / "executions/0"
    immutable_before = {
        relative: (execution / relative).read_bytes()
        for relative in (
            "receipt.json",
            "logs/stdout.log",
            "logs/stderr.log",
            "artifacts/manifest.json",
            "artifacts/result.json",
        )
    }
    pending_projection = (execution / "result.json").read_bytes()
    resolved = job.submit_review(
        result.trials[0].receipt.trial_id,
        "human",
        {"quality": 1},
        feedback="approved",
    )
    assert resolved.status == "succeeded"
    assert resolved.trials[0].score == 1
    assert job.store.successful_result(trial) == resolved.trials[0]
    assert pending_projection != (execution / "result.json").read_bytes()
    for relative, content in immutable_before.items():
        assert (execution / relative).read_bytes() == content
    with pytest.raises(ValueError, match="already submitted"):
        job.submit_review(
            result.trials[0].receipt.trial_id,
            "human",
            {"quality": 1},
        )


async def test_train_preflight_fails_when_exact_tito_is_unsupported(
    tmp_path: Path,
) -> None:
    task = make_task("one", "docker")
    spec = JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
        mode=JobMode.TRAIN,
    )
    store = JobStore(tmp_path / "jobs")
    with pytest.raises(Exception, match="exact TITO capture"):
        await JobRunner(spec, provider=FakeProvider("docker"), store=store).run()
    assert not tuple(store.events(spec.job_id, after=1))


async def test_train_persists_validated_tito_as_hashed_artifact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "harness"
    source.mkdir()
    (source / "run.py").write_text("pass\n", encoding="utf-8")
    package = HarnessPackage(
        definition=HarnessProtocol(
            name="tito",
            implementation="runnable",
            command=("python", "run.py"),
            outputs=(FileDeclaration(path="result.json"),),
            artifacts=(FileDeclaration(path="tito.jsonl"),),
            supports_tito=True,
            tito_path="tito.jsonl",
        ),
        source=PackageSource(kind="local", uri=str(source), unsafe_local=True),
    )
    agent = AgentDefinition(
        name="agent",
        model="test/model",
        harness=HarnessBinding.from_package(package),
        harness_package=package,
    )
    task = make_task("one", "docker")
    spec = JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=agent),),
        mode=JobMode.TRAIN,
    )
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(
        spec,
        provider=FakeProvider("docker"),
        store=store,
    ).run()
    reference = result.trials[0].receipt.tito_artifact
    assert reference is not None
    assert reference.digest.startswith("sha256:")
    assert reference.size_bytes > 0
    trial = spec.plan().trials[0]
    assert (store.trial_path(trial) / "executions/0/artifacts/tito.jsonl").exists()


async def test_agent_secret_grants_must_be_declared_by_selected_harness(
    tmp_path: Path,
) -> None:
    source = tmp_path / "harness"
    source.mkdir()
    (source / "run.py").write_text("pass\n", encoding="utf-8")
    package = HarnessPackage(
        definition=HarnessProtocol(
            name="restricted",
            implementation="runnable",
            command=("python", "run.py"),
            secret_names=("ALLOWED_API_KEY",),
            outputs=(FileDeclaration(path="result.json"),),
            artifacts=(FileDeclaration(path="trajectory.jsonl"),),
        ),
        source=PackageSource(kind="local", uri=str(source), unsafe_local=True),
    )
    agent = AgentDefinition(
        name="agent",
        model="test/model",
        secret_names=("UNDECLARED_API_KEY",),
        harness=HarnessBinding.from_package(package),
        harness_package=package,
    )
    spec = JobSpec(
        source=TaskJobSource(task=make_task("one", "docker")),
        agents=(AgentBinding(agent=agent),),
    )
    provider = FakeProvider("docker")
    result = await JobRunner(
        spec,
        provider=provider,
        store=JobStore(tmp_path / "jobs"),
        environ={"UNDECLARED_API_KEY": "must-not-forward"},
    ).run()

    assert result.status == "failed"
    assert result.trials[0].error_code == ErrorCode.CONFIGURATION
    assert "not declared by Harness" in result.trials[0].error_message
    assert provider.created == []


async def test_retries_append_trial_executions_without_new_trial_identity(
    tmp_path: Path,
) -> None:
    provider = FakeProvider("docker", fail_first=True)
    task = make_task("one", "docker")
    spec = JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
        retry=RetryPolicy(
            max_retries=1,
            initial_backoff_seconds=0,
            retryable_codes=(ErrorCode.PROTOCOL_FAILED,),
        ),
    )
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(spec, provider=provider, store=store).run()
    trial = spec.plan().trials[0]
    assert result.status == "succeeded"
    assert result.trials[0].receipt.execution_id == 1
    assert (store.trial_path(trial) / "executions/0/result.json").exists()
    assert (store.trial_path(trial) / "executions/1/result.json").exists()
    selected = json.loads((store.trial_path(trial) / "selected.json").read_text())
    assert selected == {
        "execution_id": 1,
        "receipt_hash": result.trials[0].receipt.receipt_hash,
    }
    execution = store.trial_path(trial) / "executions/1"
    manifest = json.loads((execution / "artifacts/manifest.json").read_text())
    entries = {item["path"]: item for item in manifest["artifacts"]}
    assert entries["trajectory.jsonl"]["role"] == "trajectory"
    assert entries["trajectory.normalized.json"]["role"] == "trajectory"
    assert entries["state.json"]["role"] == "state"
    assert entries["observation.json"]["role"] == "observation"
    assert entries["view.json"]["role"] == "rendering"
    assert entries["verifier-results.json"]["role"] == "verifier_evidence"
    assert entries["result.json"]["sha256"].startswith("sha256:")
    assert entries["result.json"]["size"] > 0
    assert (execution / "receipt.json").exists()
    assert (execution / "logs/stdout.log").exists()
    assert store.successful_result(trial) == result.trials[0]
    assert store.next_execution_id(trial) == 2
    harness_runs = provider.harness_runs
    resumed = await JobRunner(spec, provider=provider, store=store).run(resume=True)
    assert resumed.trials == result.trials
    assert provider.harness_runs == harness_runs
    retry_events = [item for item in store.events(spec.job_id) if item.type == "retrying"]
    assert retry_events[0].trial_id == trial.trial_id


def test_event_store_redacts_hidden_state_and_secrets(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    event = store.emit(
        "job_1",
        "log",
        "running",
        message="token=secret-value",
        data={"hidden_state": {"answer": 42}, "text": "secret-value"},
        secret_values=("secret-value",),
    )
    assert "secret-value" not in event.model_dump_json()
    assert event.data["hidden_state"] == "[redacted]"
