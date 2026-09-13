from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from plural.domain import (
    AgentBinding,
    AgentDefinition,
    BenchmarkDefinition,
    BenchmarkJobSource,
    DeterministicVerifier,
    EnvironmentDefinition,
    EnvironmentRuntime,
    ErrorCode,
    ExecutionTarget,
    FileDeclaration,
    HarnessBinding,
    HarnessDefinition,
    HarnessPackage,
    HumanVerifier,
    JobMode,
    JobSpec,
    PackageSource,
    RetryPolicy,
    RubricCriterion,
    TaskDefinition,
    TaskJobSource,
    VerifierRuntime,
    WeightedVerifier,
)
from plural.execution import JobRunner as Job
from plural.execution import JobStore
from plural.sandbox import (
    Capability,
    DownloadedFile,
    ExecRequest,
    ExecResult,
    FileUpload,
    ProviderCapabilities,
    ProviderDoctor,
    SandboxHandle,
    SandboxProvider,
    SandboxRequirements,
)


class FakeProvider(SandboxProvider):
    def __init__(self, name: str, *, delay: float = 0, fail_first: bool = False) -> None:
        self.name = name
        self.delay = delay
        self.fail_first = fail_first
        self.created: list[SandboxRequirements] = []
        self.files: dict[str, dict[str, bytes]] = {}
        self.active = 0
        self.max_active = 0
        self.harness_runs = 0

    async def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.name,
            available=True,
            capabilities=frozenset(Capability),
        )

    async def doctor(self) -> ProviderDoctor:
        return ProviderDoctor(
            name=self.name,
            available=True,
            healthy=True,
            capabilities=tuple(item.value for item in Capability),
        )

    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        identifier = f"{self.name}-{len(self.created)}"
        self.created.append(requirements)
        self.files[identifier] = {}
        return SandboxHandle(sandbox_id=identifier, provider=self.name, image_identity="fake")

    async def upload_files(
        self,
        handle: SandboxHandle,
        files: Sequence[FileUpload],
        *,
        root: str = "/workspace",
    ) -> None:
        for item in files:
            self.files[handle.sandbox_id][item.path] = item.data

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        if request.stdin is None:
            self.files[handle.sandbox_id]["verifier-result.json"] = json.dumps(
                {
                    "reward": 1,
                    "scores": {"correct": 1},
                    "evidence": ["result.json"],
                }
            ).encode()
            return ExecResult(exit_code=0, duration_seconds=0.001)
        self.harness_runs += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_first and self.harness_runs == 1:
                return ExecResult(exit_code=2, stderr=b"temporary secret", duration_seconds=0.001)
            payload = json.loads(request.stdin)
            self.files[handle.sandbox_id]["result.json"] = b'{"answer": 42}'
            self.files[handle.sandbox_id]["trajectory.jsonl"] = (
                b'{"turn": 1}\n{"type": "cost", "cost_usd": 0.01}\n'
            )
            self.files[handle.sandbox_id]["state.json"] = b'{"step": 1}'
            self.files[handle.sandbox_id]["observation.json"] = b'{"text": "done"}'
            self.files[handle.sandbox_id]["view.json"] = b'{"kind": "text", "text": "done"}'
            if "mode" in payload["environment"]:
                raise AssertionError("mode must not be injected into Environment payload")
            artifact_paths = ["trajectory.jsonl"]
            if payload["capture_tito"]:
                self.files[handle.sandbox_id]["tito.jsonl"] = (
                    json.dumps(
                        {
                            "schema_version": "1",
                            "step": 0,
                            "tokenizer": "test",
                            "model": "test/model",
                            "input_token_ids": [1],
                            "output_token_ids": [2],
                            "observation_token_ids": [3],
                            "output_logprobs": [-0.1],
                            "output_top_logprobs": [{"ok": -0.1}],
                            "output_text": "ok",
                            "assistant_message": {
                                "role": "assistant",
                                "content": "ok",
                            },
                            "input_len": 1,
                            "output_len": 1,
                            "observation_len": 1,
                        }
                    )
                    + "\n"
                ).encode()
                artifact_paths = ["tito.jsonl"]
            event = {
                "protocol": "plural-harness-v1",
                "type": "result",
                "status": "succeeded",
                "outputs": ["result.json"],
                "artifacts": artifact_paths,
                "trace_id": "trace-1",
            }
            return ExecResult(
                exit_code=0,
                stdout=(json.dumps(event) + "\n").encode(),
                duration_seconds=0.001,
            )
        finally:
            self.active -= 1

    async def download_files(
        self,
        handle: SandboxHandle,
        paths: Sequence[str],
        *,
        root: str = "/workspace",
    ) -> tuple[DownloadedFile, ...]:
        return tuple(
            DownloadedFile(path=path, data=self.files[handle.sandbox_id][path]) for path in paths
        )

    async def cancel(self, handle: SandboxHandle) -> None:
        return

    async def destroy(self, handle: SandboxHandle) -> None:
        return


def exact_verifier(provider: str) -> DeterministicVerifier:
    return DeterministicVerifier(
        name=f"exact-{provider}",
        command=("python", "verify.py"),
        required_artifacts=("result.json",),
        runtime=VerifierRuntime(provider=provider),
    )


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
    result = await Job(
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
    assert result.aggregates[0].mean_reward == 1
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
    job = Job(
        spec,
        provider=FakeProvider("docker"),
        store=JobStore(tmp_path / "jobs"),
    )
    result = await job.run()
    assert result.status == "awaiting_review"
    assert result.trials[0].status == "awaiting_review"
    assert result.trials[0].verifier_results[0].kind == "human"
    resolved = job.submit_review(
        result.trials[0].receipt.trial_id,
        "human",
        {"quality": 1},
        feedback="approved",
    )
    assert resolved.status == "succeeded"
    assert resolved.trials[0].reward == 1
    trial = spec.plan().trials[0]
    assert job.store.successful_result(trial) == resolved.trials[0]


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
        await Job(spec, provider=FakeProvider("docker"), store=store).run()
    assert not tuple(store.events(spec.job_id, after=1))


async def test_train_persists_validated_tito_as_hashed_artifact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "harness"
    source.mkdir()
    (source / "run.py").write_text("pass\n", encoding="utf-8")
    package = HarnessPackage(
        definition=HarnessDefinition(
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
    result = await Job(
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
    result = await Job(spec, provider=provider, store=store).run()
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
    resumed = await Job(spec, provider=provider, store=store).run(resume=True)
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
