"""Deterministic hosted graph synchronization for ``plural run``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from plural.jobs import BenchmarkJobSource, JobMode, JobSpec, TaskJobSource
from plural.tasks import TaskDefinition

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from plural.client import Client


class _Publisher(Protocol):
    def publish(self, value: Any, **references: Any) -> dict[str, Any]: ...


T = TypeVar("T")


@dataclass(frozen=True)
class HostedSubmission:
    """Hosted Job plus the exact published source and Agent revisions."""

    job: dict[str, Any]
    source_revision_id: str
    agent_revision_ids: tuple[str, ...]


def _unique(values: Iterable[T], *, key: Any) -> tuple[T, ...]:
    seen: set[str] = set()
    result: list[T] = []
    for value in values:
        identity = str(key(value))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(value)
    return tuple(result)


def _revision_id(record: dict[str, Any], kind: str) -> str:
    revision_id = record.get("id")
    if not isinstance(revision_id, str) or not revision_id:
        raise ValueError(f"published {kind} revision response omitted id")
    return revision_id


def _publish(
    api: _Publisher,
    value: Any,
    kind: str,
    **references: Any,
) -> str:
    return _revision_id(api.publish(value, **references), kind)


def validate_hosted_graph(
    spec: JobSpec,
    *,
    idempotency_key: str | None = None,
    name: str = "Job",
) -> None:
    """Validate all local graph edges before the first hosted write."""
    spec.plan()
    effective_key = spec.job_id if idempotency_key is None else idempotency_key
    if not effective_key or len(effective_key) > 160:
        raise ValueError("hosted Job idempotency key must contain 1-160 characters")
    if not name or len(name) > 160:
        raise ValueError("hosted Job name must contain 1-160 characters")
    for binding in spec.agents:
        agent = binding.agent
        if agent.harness is not None and agent.harness_package is None:
            raise ValueError(
                f"Agent {agent.name!r} requires its exact harness_package for hosted sync"
            )
        if spec.mode is JobMode.TRAIN and (
            agent.harness_package is None or not agent.harness_package.manifest.supports_tito
        ):
            raise ValueError("Train mode requires every selected Agent harness to support TITO")


def sync_and_submit(
    client: Client,
    spec: JobSpec,
    *,
    idempotency_key: str | None = None,
    name: str = "Job",
) -> HostedSubmission:
    """Publish a complete canonical graph and submit its hosted Job.

    Publication order is stable and dependency-safe. Canonically identical
    dependencies are published once and their returned hosted revision IDs are
    reused for every graph edge.
    """
    validate_hosted_graph(spec, idempotency_key=idempotency_key, name=name)
    effective_key = spec.job_id if idempotency_key is None else idempotency_key

    tasks: Sequence[TaskDefinition] = spec.tasks
    harnesses = _unique(
        (
            binding.agent.harness_package
            for binding in spec.agents
            if binding.agent.harness_package is not None
        ),
        key=lambda package: package.content_hash,
    )
    environments = _unique(
        (task.environment for task in tasks),
        key=lambda environment: environment.content_hash,
    )
    verifiers = _unique(
        (weighted.verifier for task in tasks for weighted in task.verifiers),
        key=lambda verifier: verifier.content_hash,
    )
    unique_tasks = _unique(tasks, key=lambda task: task.content_hash)
    agents = _unique(
        (binding.agent for binding in spec.agents),
        key=lambda agent: agent.content_hash,
    )

    harness_ids = {
        package.content_hash: _publish(client.harnesses, package, "Harness")
        for package in harnesses
    }
    environment_ids = {
        environment.content_hash: _publish(
            client.environments,
            environment,
            "Environment",
        )
        for environment in environments
    }
    verifier_ids = {
        verifier.content_hash: _publish(client.verifiers, verifier, "Verifier")
        for verifier in verifiers
    }
    task_ids = {
        task.content_hash: _publish(
            client.tasks,
            task,
            "Task",
            environment_revision_id=environment_ids[task.environment.content_hash],
            verifier_revision_ids=[
                verifier_ids[weighted.verifier.content_hash] for weighted in task.verifiers
            ],
        )
        for task in unique_tasks
    }

    if isinstance(spec.source, BenchmarkJobSource):
        source_revision_id = _publish(
            client.benchmarks,
            spec.source.benchmark,
            "Benchmark",
            task_revision_ids=[task_ids[task.content_hash] for task in spec.source.benchmark.tasks],
        )
    elif isinstance(spec.source, TaskJobSource):
        source_revision_id = task_ids[spec.source.task.content_hash]
    else:  # pragma: no cover - JobSource is a closed discriminated union.
        raise ValueError("unsupported hosted Job source")

    agent_ids = {
        agent.content_hash: _publish(
            client.agents,
            agent,
            "Agent",
            harness_revision_id=(
                harness_ids[agent.harness_package.content_hash]
                if agent.harness_package is not None
                else None
            ),
        )
        for agent in agents
    }
    exact_agent_ids = tuple(agent_ids[binding.agent.content_hash] for binding in spec.agents)
    job = client.jobs.submit(
        spec,
        source_revision_id=source_revision_id,
        agent_revision_ids=exact_agent_ids,
        idempotency_key=effective_key,
        name=name,
    )
    return HostedSubmission(
        job=job,
        source_revision_id=source_revision_id,
        agent_revision_ids=exact_agent_ids,
    )


__all__ = ["HostedSubmission", "sync_and_submit", "validate_hosted_graph"]
