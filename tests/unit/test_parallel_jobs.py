"""Bulk-evaluation concurrency: overlap, caps, cancel, and event integrity."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fakes import FakeProvider

from plural.agents import AgentBinding, AgentDefinition
from plural.common import ExecutionTarget
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.execution import JobRunner, JobStore
from plural.jobs import BenchmarkJobSource, JobSpec
from plural.tasks import BenchmarkDefinition, TaskDefinition
from plural.verifiers import DeterministicVerifier, VerifierRuntime, WeightedVerifier


def _task(name: str, provider: str = "docker") -> TaskDefinition:
    target = ExecutionTarget.REMOTE if provider == "remote" else ExecutionTarget.DOCKER
    return TaskDefinition(
        task_id=name,
        instructions=f"Solve {name}",
        environment=EnvironmentDefinition(
            name=f"env-{name}",
            runtime=EnvironmentRuntime(provider=provider, targets=frozenset({target})),
        ),
        verifiers=(
            WeightedVerifier(
                verifier=DeterministicVerifier(
                    name="exact",
                    command=("python", "verify.py"),
                    runtime=VerifierRuntime(provider=provider),
                )
            ),
        ),
    )


def _spec(
    names: list[str], *, attempts: int = 1, concurrency: int = 1, per_runtime_concurrency: int = 1
) -> JobSpec:
    return JobSpec(
        source=BenchmarkJobSource(
            benchmark=BenchmarkDefinition(
                name="parallel-suite",
                tasks=tuple(_task(name) for name in names),
            )
        ),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
        attempts=attempts,
        concurrency=concurrency,
        per_runtime_concurrency=per_runtime_concurrency,
    )


async def test_parallel_trials_overlap_and_respect_global_cap(tmp_path: Path) -> None:
    provider = FakeProvider("docker", delay=0.05)
    spec = _spec(
        [f"case-{index}" for index in range(4)],
        concurrency=2,
        per_runtime_concurrency=2,
    )
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(spec, provider=provider, store=store).run()

    assert result.status == "succeeded"
    assert len(result.trials) == 4
    assert provider.harness_runs == 4
    # Trials overlapped: more than one sandbox was ever active at once.
    assert provider.max_active >= 2
    # ...but never more than the global cap.
    assert provider.max_active <= 2


async def test_sequential_run_never_overlaps(tmp_path: Path) -> None:
    provider = FakeProvider("docker", delay=0.01)
    spec = _spec(["one", "two"], concurrency=1)
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(spec, provider=provider, store=store).run()

    assert result.status == "succeeded"
    assert provider.max_active == 1


async def test_per_runtime_cap_is_honored_across_providers(tmp_path: Path) -> None:
    docker = FakeProvider("docker", delay=0.03)
    remote = FakeProvider("remote", delay=0.03)
    tasks = tuple(_task(f"case-{index}", "docker" if index % 2 else "remote") for index in range(6))
    spec = JobSpec(
        source=BenchmarkJobSource(
            benchmark=BenchmarkDefinition(name="mixed", tasks=tasks),
        ),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
        concurrency=4,
        per_runtime_concurrency=1,
    )
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(
        spec, providers={"docker": docker, "remote": remote}, store=store
    ).run()

    assert result.status == "succeeded"
    assert len(result.trials) == 6
    assert docker.max_active == 1
    assert remote.max_active == 1


async def test_event_sequences_stay_unique_under_parallel_trials(tmp_path: Path) -> None:
    provider = FakeProvider("docker", delay=0.01)
    spec = _spec([f"case-{index}" for index in range(6)], attempts=2, concurrency=4)
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(spec, provider=provider, store=store).run()

    assert result.status == "succeeded"
    events = tuple(store.events(spec.job_id))
    sequences = [item.sequence for item in events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert sequences[0] == 1
    assert events[-1].type == "completed"


async def test_bulk_waves_complete_beyond_one_concurrency_window(tmp_path: Path) -> None:
    provider = FakeProvider("docker", delay=0.01)
    spec = _spec([f"case-{index}" for index in range(5)], concurrency=2)
    store = JobStore(tmp_path / "jobs")
    result = await JobRunner(spec, provider=provider, store=store).run()

    assert result.status == "succeeded"
    assert [trial.status for trial in result.trials] == ["succeeded"] * 5
    assert provider.harness_runs == 5


async def test_cancel_stops_a_parallel_job(tmp_path: Path) -> None:
    provider = FakeProvider("docker", delay=0.2)
    spec = _spec(
        [f"case-{index}" for index in range(8)],
        concurrency=2,
        per_runtime_concurrency=2,
    )
    store = JobStore(tmp_path / "jobs")
    runner = JobRunner(spec, provider=provider, store=store)

    async def cancel_soon() -> None:
        await asyncio.sleep(0.15)
        await runner.cancel()

    _, result = await asyncio.gather(cancel_soon(), runner.run())
    # Cancel is a flag: in-flight Trials finish, queued Trials never start.
    assert result.status == "cancelled"
    assert provider.harness_runs <= 2
    assert [trial.status for trial in result.trials].count("cancelled") >= 6
    assert all(trial.status in {"succeeded", "cancelled"} for trial in result.trials)
