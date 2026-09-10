"""mypy --strict consumer smoke test for public exports."""

from __future__ import annotations

from typing import Any

from plural import (
    AgentBinding,
    AgentTemplate,
    Benchmark,
    BenchmarkDefinition,
    Client,
    Dataset,
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
    RuntimeSpec,
    SandboxProvider,
    TaskData,
    TaskDefinition,
    Trace,
    Trial,
    TrialReceipt,
    TrialResult,
    TrialSpec,
    Usage,
    VerifierManifest,
)


def main() -> None:
    catalog: ModelCatalog = ModelCatalog()
    _ = catalog.get("openai/gpt-4o-mini")
    usage: Usage = Usage.from_counts(1, 1)
    msg: Message = Message(role="user", content="hi")
    trace: Trace = Trace(trace_id="t")
    env: Environment[Any, Any] = Environment(name="x", version="0.1.0")
    task: TaskData = TaskData(task_id="1", input="hi")
    ds: Dataset = Dataset.from_traces("d", [trace])
    assert usage.total_tokens == 2
    assert msg.role == "user"
    assert env.name == "x"
    assert task.task_id == "1"
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
    manifest = EnvironmentManifest(
        name="x",
        tasks=(TaskDefinition(task_id="1", input="hi"),),
    )
    definition = BenchmarkDefinition(
        name="b",
        environment=manifest.identity,
        task_ids=("1",),
    )
    agent = AgentBinding(
        template=AgentTemplate(
            name="a",
            model="openai/model",
            environment=manifest.identity,
        )
    )
    plan: JobPlan = JobSpec(
        environment=manifest,
        benchmark=definition,
        agents=(agent,),
    ).plan()
    assert plan.trial_count == 1
    trial: TrialSpec = plan.trials[0]
    lock: JobLock = plan.lock
    runtime: RuntimeSpec = trial.runtime
    retry: RetryPolicy = RetryPolicy()
    verifier: VerifierManifest = VerifierManifest(command=("python", "-c", "pass"))
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
        runtime,
        retry,
        verifier,
    )
    _ = Client
    _ = Benchmark


if __name__ == "__main__":
    main()
