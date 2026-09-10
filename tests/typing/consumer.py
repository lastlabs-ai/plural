"""mypy --strict consumer smoke test for public exports."""

from __future__ import annotations

from typing import Any

from plural import (
    AgentBinding,
    AgentDefinition,
    BenchmarkDefinition,
    BenchmarkJobSource,
    Client,
    DeterministicVerifier,
    Environment,
    EnvironmentManifest,
    ErrorCode,
    HarnessBinding,
    HarnessManifest,
    HarnessPackage,
    Job,
    JobLock,
    JobPlan,
    JobResult,
    JobSpec,
    JobStore,
    Message,
    ModelCatalog,
    NetworkMode,
    PackageSource,
    RetryPolicy,
    SandboxProvider,
    TaskDefinition,
    Trace,
    TraceDataset,
    Trial,
    TrialReceipt,
    TrialResult,
    TrialSpec,
    Usage,
    WeightedVerifier,
)


def main() -> None:
    catalog: ModelCatalog = ModelCatalog()
    _ = catalog.get("openai/gpt-4o-mini")
    usage: Usage = Usage.from_counts(1, 1)
    msg: Message = Message(role="user", content="hi")
    trace: Trace = Trace(trace_id="t")
    env: Environment[Any, Any] = Environment(name="x", revision="0.1.0")
    ds: TraceDataset = TraceDataset.from_traces("d", [trace])
    assert usage.total_tokens == 2
    assert msg.role == "user"
    assert env.name == "x"
    assert len(ds) == 1
    package = HarnessPackage(
        manifest=HarnessManifest(
            name="h",
            implementation="runnable",
            command=("python", "harness.py"),
        ),
        source=PackageSource(kind="local", uri=".", unsafe_local=True),
    )
    binding = HarnessBinding.from_package(package)
    _ = binding
    manifest = EnvironmentManifest(name="x")
    verifier = DeterministicVerifier(name="v", command=("python", "-c", "pass"))
    task_definition = TaskDefinition(
        task_id="1",
        instructions="Say hi.",
        environment=manifest,
        verifiers=(WeightedVerifier(verifier=verifier),),
    )
    definition = BenchmarkDefinition(
        name="b",
        tasks=(task_definition,),
    )
    agent = AgentBinding(
        agent=AgentDefinition(
            name="a",
            model="openai/model",
        )
    )
    plan: JobPlan = JobSpec(
        source=BenchmarkJobSource(benchmark=definition),
        agents=(agent,),
    ).plan()
    assert plan.trial_count == 1
    trial: TrialSpec = plan.trials[0]
    lock: JobLock = plan.lock
    runtime_provider: str = trial.runtime_provider
    retry: RetryPolicy = RetryPolicy()
    verifier_definition: DeterministicVerifier = verifier
    _ = (
        Job,
        JobResult,
        JobStore,
        NetworkMode,
        SandboxProvider,
        Trial,
        TrialReceipt,
        TrialResult,
        ErrorCode,
        lock,
        runtime_provider,
        retry,
        verifier_definition,
    )
    _ = Client


if __name__ == "__main__":
    main()
