"""mypy --strict consumer smoke test for public exports."""

from __future__ import annotations

from typing import Any

from plural import (
    Agent,
    Benchmark,
    Client,
    DeterministicVerifier,
    Environment,
    ErrorCode,
    Harness,
    Job,
    JobPlan,
    JobResult,
    JobStore,
    Message,
    ModelCatalog,
    NetworkMode,
    RetryPolicy,
    SandboxProvider,
    Task,
    Trace,
    TraceDataset,
    Trial,
    TrialReceipt,
    TrialResult,
    Usage,
)


def main() -> None:
    catalog: ModelCatalog = ModelCatalog()
    _ = catalog.get("openai/gpt-4o-mini")
    usage: Usage = Usage.from_counts(1, 1)
    msg: Message = Message(role="user", content="hi")
    trace: Trace = Trace(trace_id="t")
    env: Environment[Any, Any] = Environment(name="x", version="0.1.0")
    ds: TraceDataset = TraceDataset.from_traces("d", [trace])
    assert usage.total_tokens == 2
    assert msg.role == "user"
    assert env.name == "x"
    assert len(ds) == 1
    harness = Harness(name="custom", command=("python", "runner.py"))
    verifier = DeterministicVerifier(name="v", check=("python", "-c", "pass"))
    task = Task(
        name="1",
        instructions="Say hi.",
        environment=env,
        verifiers=(verifier,),
    )
    benchmark = Benchmark(
        name="b",
        version="1.0.0",
        tasks=(task,),
    )
    agent = Agent(
        name="a",
        model="openai/gpt-5.6-luna",
        harness=harness,
    )
    plan: JobPlan = Job(
        benchmark,
        agents=(agent,),
    ).plan
    assert plan.trial_count == 1
    runtime_provider: str = plan.trials[0].runtime_provider
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
        runtime_provider,
        retry,
        verifier_definition,
    )
    _ = Client


if __name__ == "__main__":
    main()
