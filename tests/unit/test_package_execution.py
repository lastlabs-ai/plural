from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from plural.domain import (
    AgentSpec,
    BenchmarkDefinition,
    EnvironmentManifest,
    ErrorCode,
    FileDeclaration,
    HarnessBinding,
    HarnessManifest,
    HarnessPackage,
    JobSpec,
    PackageSource,
    RetryPolicy,
    RuntimeSpec,
    TaskDefinition,
    VerifierManifest,
)
from plural.execution import Job, JobStore
from plural.harness import HarnessProtocolError, parse_events
from plural.sandbox import (
    Capability,
    CapabilityError,
    DownloadedFile,
    ExecRequest,
    ExecResult,
    FileUpload,
    NetworkMode,
    ProviderCapabilities,
    ProviderDoctor,
    SandboxHandle,
    SandboxProvider,
    SandboxRequirements,
)


class FakeProvider(SandboxProvider):
    name = "fake"

    def __init__(self, *, fail_first: bool = False, delay: float = 0) -> None:
        self.fail_first = fail_first
        self.delay = delay
        self.created: list[SandboxRequirements] = []
        self.destroyed: list[str] = []
        self.files: dict[str, dict[str, bytes]] = {}
        self.agent_requests: list[dict[str, object]] = []
        self.active_by_agent: dict[str, int] = {}
        self.max_by_agent: dict[str, int] = {}
        self.agent_execs = 0

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
        await self.preflight(requirements)
        sandbox_id = f"fake-{len(self.created)}"
        self.created.append(requirements)
        self.files[sandbox_id] = {}
        return SandboxHandle(sandbox_id=sandbox_id, provider=self.name, image_identity="fake:image")

    async def upload_files(
        self,
        handle: SandboxHandle,
        files: Sequence[FileUpload],
        *,
        root: str = "/workspace",
    ) -> None:
        for file in files:
            self.files[handle.sandbox_id][file.path] = file.data

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        if self.created[int(handle.sandbox_id.split("-")[1])].network is NetworkMode.NONE:
            hidden = json.loads(self.files[handle.sandbox_id][".plural/verifier-input.json"])
            assert hidden["expected"] == {"answer": 42}
            assert request.env == {}
            self.files[handle.sandbox_id]["verifier-result.json"] = json.dumps(
                {"reward": 1, "scores": {"correct": 1}, "evidence": ["answer.txt"]}
            ).encode()
            return ExecResult(exit_code=0, duration_seconds=0.001)

        self.agent_execs += 1
        payload = json.loads((request.stdin or b"{}").decode())
        self.agent_requests.append(payload)
        assert "expected" not in json.dumps(payload)
        assert "verifier_input" not in json.dumps(payload)
        agent = str(payload["agent"]["name"])
        self.active_by_agent[agent] = self.active_by_agent.get(agent, 0) + 1
        self.max_by_agent[agent] = max(self.max_by_agent.get(agent, 0), self.active_by_agent[agent])
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_first and self.agent_execs == 1:
                return ExecResult(
                    exit_code=2,
                    stderr=f"temporary {request.env.get('TEST_TOKEN', '')}".encode(),
                    duration_seconds=0.001,
                )
            self.files[handle.sandbox_id]["answer.txt"] = b"42\n"
            event = {
                "protocol": "plural-harness-v1",
                "type": "result",
                "status": "succeeded",
                "outputs": ["answer.txt"],
                "artifacts": [],
            }
            return ExecResult(
                exit_code=0,
                stdout=(json.dumps(event) + "\n").encode(),
                duration_seconds=0.001,
            )
        finally:
            self.active_by_agent[agent] -= 1

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
        self.destroyed.append(handle.sandbox_id)


def _spec(
    tmp_path: Path,
    *,
    tasks: int = 1,
    agents: int = 1,
    verifier: bool = False,
    retry: RetryPolicy | None = None,
    concurrency: int = 4,
    per_agent_concurrency: int = 1,
) -> JobSpec:
    source = tmp_path / "harness"
    source.mkdir(exist_ok=True)
    (source / "harness.py").write_text("pass\n", encoding="utf-8")
    package = HarnessPackage(
        manifest=HarnessManifest(
            name="test",
            command=("python", "harness.py"),
            secret_names=("TEST_TOKEN",),
            outputs=(FileDeclaration(path="answer.txt"),),
        ),
        source=PackageSource(kind="local", uri=str(source), unsafe_local=True),
    )
    binding = HarnessBinding.from_package(package)
    environment = EnvironmentManifest(
        name="test",
        tasks=tuple(
            TaskDefinition(
                task_id=f"task-{index}",
                input={"question": index},
                expected={"answer": 42},
                verifier_input={"private": True},
            )
            for index in range(tasks)
        ),
        allowed_harnesses=(binding,),
        verifier=(
            VerifierManifest(
                command=("python", "verify.py"),
                required_artifacts=("answer.txt",),
            )
            if verifier
            else None
        ),
    )
    benchmark = BenchmarkDefinition(
        name="test",
        environment=environment.identity,
        task_ids=tuple(task.task_id for task in environment.tasks),
    )
    agent_specs = tuple(
        AgentSpec(
            name=f"agent-{index}",
            model="test/model",
            environment=environment.identity,
            harness=binding,
            harness_package=package,
        )
        for index in range(agents)
    )
    return JobSpec(
        environment=environment,
        benchmark=benchmark,
        agents=agent_specs,
        concurrency=concurrency,
        per_agent_concurrency=per_agent_concurrency,
        runtime=RuntimeSpec(provider="fake", network=NetworkMode.FULL, unsafe_local=True),
        retry=retry or RetryPolicy(),
    )


def _replace_harness(spec: JobSpec, manifest: HarnessManifest) -> JobSpec:
    package = spec.agents[0].harness_package
    assert package is not None
    package = package.model_copy(update={"manifest": manifest})
    binding = HarnessBinding.from_package(package)
    environment = spec.environment.model_copy(update={"allowed_harnesses": (binding,)})
    benchmark = spec.benchmark.model_copy(update={"environment": environment.identity})
    agent = spec.agents[0].model_copy(
        update={
            "environment": environment.identity,
            "harness": binding,
            "harness_package": package,
        }
    )
    return spec.model_copy(
        update={"environment": environment, "benchmark": benchmark, "agents": (agent,)}
    )


def test_protocol_rejects_scores_and_path_traversal() -> None:
    bad_score = (
        b'{"protocol":"plural-harness-v1","type":"result","status":"succeeded",'
        b'"outputs":[],"artifacts":[],"reward":1}\n'
    )
    try:
        parse_events(bad_score)
    except HarnessProtocolError as exc:
        assert "reward" in str(exc)
    else:
        raise AssertionError("harness score was accepted")

    try:
        FileUpload(path="../secret", data=b"x")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal was accepted")


async def test_preflight_enforces_models_auth_and_harness_capabilities(tmp_path: Path) -> None:
    base = _spec(tmp_path)
    package = base.agents[0].harness_package
    assert package is not None
    provider = FakeProvider()
    unsupported_model = _replace_harness(
        base,
        package.manifest.model_copy(update={"supported_models": ("openai/*",)}),
    )
    with pytest.raises(CapabilityError, match="does not support model"):
        await Job(
            unsupported_model, provider=provider, store=JobStore(tmp_path / "one")
        ).preflight()

    unknown_capability = _replace_harness(
        base,
        package.manifest.model_copy(update={"capabilities": ("telepathy",)}),
    )
    with pytest.raises(CapabilityError, match="unknown harness capabilities"):
        await Job(
            unknown_capability, provider=provider, store=JobStore(tmp_path / "two")
        ).preflight()
    assert provider.created == []


async def test_hidden_data_and_secrets_stay_out_of_harness_and_verifier_is_isolated(
    tmp_path: Path,
) -> None:
    provider = FakeProvider()
    spec = _spec(tmp_path, verifier=True)
    runtime = Job(
        spec,
        provider=provider,
        store=JobStore(tmp_path / "jobs"),
    )
    result = await runtime.run()

    assert result.trials[0].reward == 1
    assert result.trials[0].scores == {"correct": 1}
    assert [item.network for item in provider.created] == [NetworkMode.FULL, NetworkMode.NONE]
    assert len(provider.destroyed) == 2
    assert result.trials[0].receipt.trust == "self_reported"
    assert result.trials[0].receipt.artifact_hashes["answer.txt"].startswith("sha256:")

    regraded = await runtime.regrade()
    assert regraded.trials[0].receipt.source_receipt_hash == result.trials[0].receipt.receipt_hash
    await runtime.regrade()
    regrade_root = runtime.store.trial_path(spec.plan().trials[0]) / "regrades"
    assert sorted(path.name for path in regrade_root.iterdir()) == ["0", "1"]
    assert [item.network for item in provider.created] == [
        NetworkMode.FULL,
        NetworkMode.NONE,
        NetworkMode.NONE,
        NetworkMode.NONE,
    ]


async def test_retries_use_fresh_sandboxes_and_resume_skips_success(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(fail_first=True)
    spec = _spec(
        tmp_path,
        retry=RetryPolicy(
            max_retries=1,
            initial_backoff_seconds=0,
            retryable_codes=(ErrorCode.PROTOCOL_FAILED,),
        ),
    )
    store = JobStore(tmp_path / "jobs")
    result = await Job(spec, provider=provider, store=store).run()

    assert result.trials[0].status == "succeeded"
    assert result.trials[0].receipt.retry_count == 1
    assert len(provider.created) == 2
    assert (store.trial_path(spec.plan().trials[0]) / "attempts/0/receipt.json").exists()
    assert (store.trial_path(spec.plan().trials[0]) / "attempts/1/receipt.json").exists()

    await Job(spec, provider=provider, store=store).run(resume=True)
    assert len(provider.created) == 2


async def test_resume_appends_monotonic_execution_and_selects_its_artifacts(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(fail_first=True)
    spec = _spec(tmp_path)
    store = JobStore(tmp_path / "jobs")
    first = await Job(spec, provider=provider, store=store).run()
    assert first.trials[0].status == "failed"

    second = await Job(spec, provider=provider, store=store).run(resume=True)
    trial = spec.plan().trials[0]
    root = store.trial_path(trial)
    assert second.trials[0].status == "succeeded"
    assert (root / "attempts/0/receipt.json").exists()
    assert (root / "attempts/1/receipt.json").exists()
    assert (root / "attempts/1/artifacts/answer.txt").read_bytes() == b"42\n"
    assert json.loads((root / "selected.json").read_text())["execution_id"] == 1
    assert store.artifact_files(trial)[0].data == b"42\n"


async def test_successful_result_rejects_tampered_receipt_ownership(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    store = JobStore(tmp_path / "jobs")
    await Job(spec, provider=FakeProvider(), store=store).run()
    trial = spec.plan().trials[0]
    receipt_path = store.trial_path(trial) / "attempts/0/receipt.json"
    payload = json.loads(receipt_path.read_text())
    payload["job_id"] = "job_other"
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")
    result_path = receipt_path.parent / "result.json"
    result = json.loads(result_path.read_text())
    result["receipt"]["job_id"] = "job_other"
    result_path.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(ValueError, match="locked job"):
        store.successful_result(trial)


async def test_global_and_per_agent_concurrency_are_bounded(tmp_path: Path) -> None:
    provider = FakeProvider(delay=0.02)
    spec = _spec(
        tmp_path,
        tasks=4,
        agents=2,
        concurrency=3,
        per_agent_concurrency=1,
    )
    result = await Job(spec, provider=provider, store=JobStore(tmp_path / "jobs")).run()

    assert provider.max_by_agent == {"agent-0": 1, "agent-1": 1}
    assert [item.receipt.trial_id for item in result.trials] == [
        item.trial_id for item in spec.plan().trials
    ]


async def test_failed_logs_and_receipt_errors_are_redacted(tmp_path: Path) -> None:
    provider = FakeProvider(fail_first=True)
    base = _spec(tmp_path)
    agent = base.agents[0].model_copy(update={"secret_names": ("TEST_TOKEN",)})
    spec = base.model_copy(update={"agents": (agent,)})
    store = JobStore(tmp_path / "jobs")

    result = await Job(
        spec,
        provider=provider,
        store=store,
        environ={"TEST_TOKEN": "secret-token"},
    ).run()

    assert "secret-token" not in (result.trials[0].error_message or "")
    attempt = store.trial_path(spec.plan().trials[0]) / "attempts/0/logs/stderr.log"
    assert attempt.read_bytes() == b"temporary ***"
    assert "secret-token" not in (store.job_path(spec.job_id) / "result.json").read_text()
