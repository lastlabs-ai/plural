"""Deterministic hosted graph synchronization for ``plural run``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from plural.jobs import (
    BenchmarkJobSource,
    JobMode,
    JobSpec,
    TaskJobSource,
    resolve_trial_harness_grant,
)
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
) -> dict[str, Any]:
    record = api.publish(value, **references)
    _revision_id(record, kind)
    return record


def _stamp_compatible_harnesses(
    client: Any,
    spec: JobSpec,
    *,
    environment_records: dict[str, dict[str, Any]],
    harness_ids: dict[str, str],
) -> None:
    """Record a compatible stamp for each published Environment/Harness pair."""
    seen: set[tuple[str, str]] = set()
    for task in spec.tasks:
        environment = environment_records[task.environment.content_hash]
        environment_id = environment.get("environment_id")
        revision_id = environment.get("id")
        if not isinstance(environment_id, str) or not isinstance(revision_id, str):
            raise ValueError("published Environment revision omitted parent id")
        for binding in spec.agents:
            package = binding.agent.harness_package
            if package is None:
                continue
            pair = (revision_id, harness_ids[package.content_hash])
            if pair in seen:
                continue
            seen.add(pair)
            grant = resolve_trial_harness_grant(task.environment, binding.agent)
            client.environments.stamp_harness(
                environment_id=environment_id,
                revision_id=revision_id,
                harness_revision_id=pair[1],
                compatible=True,
                evidence=(
                    grant.model_dump(mode="json") if grant is not None else {"kind": "native"}
                ),
            )


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
            agent.harness_package is None or not agent.harness_package.definition.supports_tito
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

    harness_records = {
        package.content_hash: _publish(client.harnesses, package, "Harness")
        for package in harnesses
    }
    harness_ids = {
        digest: _revision_id(record, "Harness") for digest, record in harness_records.items()
    }
    environment_records = {
        environment.content_hash: _publish(
            client.environments,
            environment,
            "Environment",
        )
        for environment in environments
    }
    environment_ids = {
        digest: _revision_id(record, "Environment")
        for digest, record in environment_records.items()
    }
    verifier_ids = {
        verifier.content_hash: _revision_id(
            _publish(client.verifiers, verifier, "Verifier"),
            "Verifier",
        )
        for verifier in verifiers
    }
    task_ids = {
        task.content_hash: _revision_id(
            _publish(
                client.tasks,
                task,
                "Task",
                environment_revision_id=environment_ids[task.environment.content_hash],
                verifier_revision_ids=[
                    verifier_ids[weighted.verifier.content_hash] for weighted in task.verifiers
                ],
            ),
            "Task",
        )
        for task in unique_tasks
    }

    if isinstance(spec.source, BenchmarkJobSource):
        source_revision_id = _revision_id(
            _publish(
                client.benchmarks,
                spec.source.benchmark,
                "Benchmark",
                task_revision_ids=[
                    task_ids[task.content_hash] for task in spec.source.benchmark.tasks
                ],
            ),
            "Benchmark",
        )
    elif isinstance(spec.source, TaskJobSource):
        source_revision_id = task_ids[spec.source.task.content_hash]
    else:  # pragma: no cover - JobSource is a closed discriminated union.
        raise ValueError("unsupported hosted Job source")

    agent_ids = {
        agent.content_hash: _revision_id(
            _publish(
                client.agents,
                agent,
                "Agent",
                harness_revision_id=(
                    harness_ids[agent.harness_package.content_hash]
                    if agent.harness_package is not None
                    else None
                ),
            ),
            "Agent",
        )
        for agent in agents
    }
    exact_agent_ids = tuple(agent_ids[binding.agent.content_hash] for binding in spec.agents)
    _stamp_compatible_harnesses(
        client,
        spec,
        environment_records=environment_records,
        harness_ids=harness_ids,
    )
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
