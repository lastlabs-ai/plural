"""Benchmark runner and report types.

Examples:
    >>> from plural.benchmarks.runner import Report, ModelStats
    >>> r = Report(environment="demo", models={})
    >>> r.environment
    'demo'
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from plural.client import Client
from plural.environments.dataset import TaskDataset, task_content_hash
from plural.environments.env import Environment
from plural.environments.policy import Policy
from plural.environments.rollout import Rollout
from plural.environments.runtime import LocalRuntime, Runtime, runtime_fingerprint
from plural.environments.task import TaskData
from plural.tracing.schema import Trace, TraceKind
from plural.tracing.writer import TraceWriter


class CaseKey(BaseModel):
    """Stable identity for one model, task, and repeat benchmark case."""

    model_config = ConfigDict(frozen=True)

    model: str
    task_id: str
    repeat: int


class CaseResult(BaseModel):
    """Outcome and trace provenance for one benchmark case."""

    key: CaseKey
    trace_id: str | None = None
    trace_kind: TraceKind | None = None
    episode_trace_id: str | None = None
    stop_reason: str | None = None
    reward: float | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    terminated: bool | None = None
    truncated: bool | None = None
    failure_type: str | None = None
    failure_message: str | None = None
    runtime_fingerprint: str | None = None


class WinRatePair(BaseModel):
    """Aligned comparison provenance for one unordered model pair."""

    model_a: str
    model_b: str
    wins: int = 0
    losses: int = 0
    ties: int = 0
    compared: int = 0
    excluded: int = 0
    win_rate: float | None = None


class ModelStats(BaseModel):
    """Aggregate stats for one model in a benchmark.

    Reward intervals are descriptive normal approximations for observed cases,
    not statistical significance tests.

    Attributes:
        model: Model id.
        n: Number of successful rollouts.
        failures: Number of failed rollouts.
        mean_reward: Mean reward.
        reward_stddev: Sample standard deviation of scored rewards.
        reward_ci95_lower: Descriptive normal-approximation 95% CI lower bound.
        reward_ci95_upper: Descriptive normal-approximation 95% CI upper bound.
        mean_scores: Per-scorer means.
        mean_latency_ms: Mean end-to-end latency.
        p50_latency_ms: Median latency.
        p95_latency_ms: 95th percentile latency.
        mean_cost: Mean USD cost.
        total_cost: Total USD cost.
        failure_reasons: Count of failure reason strings.
    """

    model: str
    n: int = 0
    failures: int = 0
    mean_reward: float | None = None
    reward_stddev: float | None = None
    reward_ci95_lower: float | None = None
    reward_ci95_upper: float | None = None
    mean_scores: dict[str, float] = Field(default_factory=dict)
    mean_latency_ms: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    mean_cost: float | None = None
    total_cost: float = 0.0
    failure_reasons: dict[str, int] = Field(default_factory=dict)


class TaskDatasetMetadata(BaseModel):
    """Identity of the task dataset used for a benchmark run."""

    name: str
    version: str
    content_hash: str


class TaskSetMetadata(BaseModel):
    """Identity of benchmark task inputs from any supported source."""

    name: str
    version: str
    source: Literal["task_dataset", "explicit", "environment"]
    content_hash: str


class RunManifest(BaseModel):
    """Reproducibility metadata for one benchmark invocation."""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    environment: str = ""
    environment_version: str = "0.1.0"
    environment_fingerprint: str = ""
    runtime_fingerprints: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    repeats: int = 1
    concurrency: int = 1
    task_set: TaskSetMetadata | None = None
    task_dataset: TaskDatasetMetadata | None = None
    package_version: str = Field(default_factory=lambda: _package_version())
    status: Literal["completed", "completed_with_failures"] = "completed"
    benchmark_name: str = ""
    primary_metric: str = "reward"


@dataclass(frozen=True)
class _EnvironmentIdentity:
    """Environment identity captured before a benchmark job executes."""

    name: str
    version: str
    fingerprint: str


@dataclass
class _JobOutcome:
    """One job result plus its pre-execution provenance."""

    item: Rollout | Exception
    environment_identity: _EnvironmentIdentity | None = None
    environment_produced: bool = False
    runtime_fingerprint: str | None = None
    failure_trace: Trace | None = None


class Report(BaseModel):
    """Benchmark report across models.

    Attributes:
        environment: Environment name.
        environment_version: Environment version.
        models: Per-model stats.
        win_rates: Pairwise win rates ``{model_a: {model_b: rate}}``.
        cases: Ordered per-case results with trace provenance.
        win_rate_pairs: Aligned pairwise comparison counts.
        manifest: Reproducibility metadata for this run.
        metadata: Arbitrary metadata.
    """

    environment: str
    environment_version: str = "0.1.0"
    name: str = ""
    description: str = ""
    primary_metric: str = "reward"
    models: dict[str, ModelStats] = Field(default_factory=dict)
    win_rates: dict[str, dict[str, float]] = Field(default_factory=dict)
    cases: list[CaseResult] = Field(default_factory=list)
    win_rate_pairs: list[WinRatePair] = Field(default_factory=list)
    manifest: RunManifest | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the report as JSON.

        Returns:
            JSON string.
        """
        return json.dumps(
            self.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )

    def to_markdown(self) -> str:
        """Render a markdown summary table.

        Returns:
            Markdown string.
        """
        lines = [
            f"# Benchmark: {self.environment} ({self.environment_version})",
            "",
            (
                "| Model | N | Failures | Mean reward | Mean cost "
                "| p50 latency (ms) | p95 latency (ms) |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for model, stats in sorted(self.models.items()):
            lines.append(
                f"| {model} | {stats.n} | {stats.failures} | {_fmt(stats.mean_reward)} "
                f"| {_fmt(stats.mean_cost)} | {_fmt(stats.p50_latency_ms)} "
                f"| {_fmt(stats.p95_latency_ms)} |"
            )
        if self.win_rates:
            lines.extend(["", "## Win rates", ""])
            for a, opponents in self.win_rates.items():
                for b, rate in opponents.items():
                    lines.append(f"- `{a}` vs `{b}`: {rate:.2%}")
        return "\n".join(lines) + "\n"

    def compare(
        self,
        other: Report,
        *,
        tolerance: float = 0.0,
        allow_incompatible: bool = False,
    ) -> dict[str, Any]:
        """Compare this report to another for CI regression checks.

        Args:
            other: Baseline report.
            tolerance: Allowed absolute reward decrease before a model is
                considered a regression.
            allow_incompatible: Compare even when run provenance differs.

        Returns:
            Dict with per-model reward deltas and regressions list.
        """
        if tolerance < 0:
            raise ValueError("tolerance must be non-negative")
        if not allow_incompatible:
            _validate_comparison_compatibility(self.manifest, other.manifest)
        deltas: dict[str, float | None] = {}
        regressions: list[str] = []
        for model, stats in self.models.items():
            base = other.models.get(model)
            if base is None or stats.mean_reward is None or base.mean_reward is None:
                deltas[model] = None
                continue
            delta = stats.mean_reward - base.mean_reward
            deltas[model] = delta
            if delta < -(tolerance + 1e-9):
                regressions.append(model)
        return {"deltas": deltas, "regressions": regressions}


class Benchmark:
    """Run an environment across models and aggregate a report.

    Args:
        env: Environment to evaluate.
        models: Model ids to compare.
        repeats: Times to run each task per model.
        concurrency: Max concurrent rollouts.
        client: Shared plural client.
    """

    def __init__(
        self,
        env: Environment[Any, Any],
        models: list[str],
        *,
        client: Client,
        repeats: int = 1,
        concurrency: int = 4,
        name: str = "",
        description: str = "",
        primary_metric: str = "reward",
        environment_factory: Callable[[], Environment[Any, Any]] | None = None,
        runtime_factory: Callable[[], Runtime] | None = None,
    ) -> None:
        if not models:
            raise ValueError("models must not be empty")
        if len(set(models)) != len(models):
            raise ValueError("models must not contain duplicates")
        if repeats < 1:
            raise ValueError("repeats must be at least 1")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if environment_factory is not None and not callable(environment_factory):
            raise TypeError("environment_factory must be callable")
        if runtime_factory is not None and not callable(runtime_factory):
            raise TypeError("runtime_factory must be callable")
        self.env = env
        self.models = list(models)
        self.client: Client | None = client
        self._policy_factories: dict[str, Callable[[], Policy]] | None = None
        self._environment_factory = environment_factory
        self._runtime_factory = runtime_factory
        self._trace_writer: TraceWriter | None = None
        self.repeats = repeats
        self.concurrency = concurrency
        self.name = name or env.name
        self.description = description
        self.primary_metric = primary_metric or "reward"
        self._traces: list[Trace] = []
        self.report: Report | None = None

    @classmethod
    def from_policies(
        cls,
        env: Environment[Any, Any],
        policies: Mapping[str, Callable[[], Policy]],
        *,
        repeats: int = 1,
        concurrency: int = 4,
        name: str = "",
        description: str = "",
        primary_metric: str = "reward",
        environment_factory: Callable[[], Environment[Any, Any]] | None = None,
        runtime_factory: Callable[[], Runtime] | None = None,
        trace_writer: TraceWriter | None = None,
    ) -> Benchmark:
        """Build a benchmark whose targets are arbitrary policy factories.

        Each benchmark job invokes its factory and therefore receives a fresh
        policy instance. A caller-owned ``trace_writer`` can persist successful
        policy episode traces.

        Args:
            env: Environment to evaluate.
            policies: Ordered mapping of target names to fresh-policy factories.
            repeats: Times to run each task per target.
            concurrency: Maximum concurrent episodes.
            name: Benchmark display name.
            description: What the benchmark measures.
            primary_metric: Reward, score, cost, or latency path used for comparison.
            environment_factory: Optional factory for a fresh environment per job.
            runtime_factory: Optional factory for a fresh tool runtime per job.
            trace_writer: Optional caller-owned writer for successful episode traces.

        Returns:
            A benchmark configured without a client.
        """
        if not policies:
            raise ValueError("policies must not be empty")
        targets = list(policies)
        for target in targets:
            if not isinstance(target, str) or not target.strip():
                raise ValueError("policy target names must be non-empty strings")
        for target, factory in policies.items():
            if not callable(factory):
                raise TypeError(f"policy factory for {target!r} must be callable")
        if repeats < 1:
            raise ValueError("repeats must be at least 1")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if environment_factory is not None and not callable(environment_factory):
            raise TypeError("environment_factory must be callable")
        if runtime_factory is not None and not callable(runtime_factory):
            raise TypeError("runtime_factory must be callable")
        if trace_writer is not None and not isinstance(trace_writer, TraceWriter):
            raise TypeError("trace_writer must be a TraceWriter")

        benchmark = cls.__new__(cls)
        benchmark.env = env
        benchmark.models = targets
        benchmark.client = None
        benchmark._policy_factories = dict(policies)
        benchmark._environment_factory = environment_factory
        benchmark._runtime_factory = runtime_factory
        benchmark._trace_writer = trace_writer
        benchmark.repeats = repeats
        benchmark.concurrency = concurrency
        benchmark.name = name or env.name
        benchmark.description = description
        benchmark.primary_metric = primary_metric or "reward"
        benchmark._traces = []
        benchmark.report = None
        return benchmark

    def run(
        self,
        tasks: list[TaskData] | None = None,
        *,
        dataset: TaskDataset | None = None,
    ) -> Report:
        """Execute the benchmark.

        Args:
            tasks: Optional explicit task list; defaults to ``env.iter_tasks()``.
            dataset: Optional versioned task dataset. Mutually exclusive with
                ``tasks``.

        Returns:
            Aggregated :class:`Report`.
        """
        if tasks is not None and dataset is not None:
            raise ValueError("tasks and dataset are mutually exclusive")
        if dataset is not None:
            source_tasks = dataset.tasks
            source: Literal["task_dataset", "explicit", "environment"] = "task_dataset"
        else:
            source_tasks = tasks if tasks is not None else list(self.env.iter_tasks())
            source = "explicit" if tasks is not None else "environment"
        task_list = [task.model_copy(deep=True) for task in source_tasks]
        if not task_list:
            raise ValueError("tasks must not be empty")
        task_ids = [task.task_id for task in task_list]
        seen_task_ids: set[str] = set()
        duplicate_task_ids: set[str] = set()
        for task_id in task_ids:
            if task_id in seen_task_ids:
                duplicate_task_ids.add(task_id)
            seen_task_ids.add(task_id)
        if duplicate_task_ids:
            duplicates = ", ".join(repr(task_id) for task_id in sorted(duplicate_task_ids))
            raise ValueError(f"task_id values must be unique; duplicates: {duplicates}")
        input_content_hash = task_content_hash(task_list)
        if dataset is not None and dataset.content_hash != input_content_hash:
            raise ValueError(
                "TaskDataset content_hash is stale: "
                f"stored {dataset.content_hash}, computed {input_content_hash}"
            )

        jobs: list[tuple[CaseKey, TaskData]] = []
        for model in self.models:
            for task in task_list:
                for repeat in range(self.repeats):
                    jobs.append(
                        (
                            CaseKey(model=model, task_id=task.task_id, repeat=repeat),
                            task.model_copy(deep=True),
                        )
                    )

        started_at = datetime.now(timezone.utc)
        dataset_metadata = (
            TaskDatasetMetadata(
                name=dataset.name,
                version=dataset.version,
                content_hash=dataset.content_hash,
            )
            if dataset is not None
            else None
        )
        task_set_metadata = TaskSetMetadata(
            name=(
                dataset.name
                if dataset is not None
                else ("explicit" if tasks is not None else f"{self.env.name}:tasks")
            ),
            version=dataset.version if dataset is not None else self.env.version,
            source=source,
            content_hash=input_content_hash,
        )
        results: dict[CaseKey, _JobOutcome] = {}

        def _run(job: tuple[CaseKey, TaskData]) -> tuple[CaseKey, _JobOutcome]:
            key, task = job
            worker: Environment[Any, Any] | None = None
            worker_produced = False
            environment_identity: _EnvironmentIdentity | None = None
            runtime_identity: str | None = None
            trace_persisted = False
            try:
                if self._environment_factory is None:
                    worker = self.env.spawn()
                else:
                    worker = self._environment_factory()
                    if not isinstance(worker, Environment):
                        raise TypeError("environment_factory did not return an Environment")
                worker_produced = True
                environment_identity = _environment_identity(worker)
                runtime = None
                if self._runtime_factory is not None:
                    runtime = self._runtime_factory()
                    if not isinstance(runtime, Runtime):
                        raise TypeError("runtime_factory did not return a Runtime")
                    runtime_identity = runtime_fingerprint(runtime)
                else:
                    runtime_identity = _local_runtime_fingerprint(worker)
                if self._policy_factories is not None:
                    policy = self._policy_factories[key.model]()
                    if not isinstance(policy, Policy):
                        raise TypeError(f"policy factory for {key.model!r} did not return a Policy")
                    if runtime is None:
                        rollout = worker.run_episode(task, policy, model=key.model)
                    else:
                        rollout = worker.run_episode(task, policy, model=key.model, runtime=runtime)
                    if self._trace_writer is not None:
                        trace_persisted = True
                        self._trace_writer.record(rollout.trace)
                    return key, _JobOutcome(
                        item=rollout,
                        environment_identity=environment_identity,
                        environment_produced=worker_produced,
                        runtime_fingerprint=runtime_identity,
                    )
                if self.client is None:  # pragma: no cover - constructor invariant
                    raise RuntimeError("model benchmark requires a client")
                if runtime is None:
                    rollout = worker.rollout(task, self.client, model=key.model)
                else:
                    rollout = worker.rollout(
                        task,
                        self.client,
                        model=key.model,
                        runtime=runtime,
                    )
                return key, _JobOutcome(
                    item=rollout,
                    environment_identity=environment_identity,
                    environment_produced=worker_produced,
                    runtime_fingerprint=runtime_identity,
                )
            except Exception as exc:  # noqa: BLE001
                failure_trace = (
                    worker.episode_trace
                    if (
                        worker_produced
                        and isinstance(worker, Environment)
                        and self._policy_factories is not None
                    )
                    else None
                )
                if (
                    failure_trace is not None
                    and self._trace_writer is not None
                    and not trace_persisted
                ):
                    trace_persisted = True
                    self._trace_writer.record(failure_trace)
                return key, _JobOutcome(
                    item=exc,
                    environment_identity=environment_identity,
                    environment_produced=worker_produced,
                    runtime_fingerprint=runtime_identity,
                    failure_trace=failure_trace,
                )

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(_run, job) for job in jobs]
            for fut in as_completed(futures):
                key, result = fut.result()
                results[key] = result

        produced_identities = {
            result.environment_identity
            for result in results.values()
            if result.environment_identity is not None
        }
        if any(
            result.environment_produced and result.environment_identity is None
            for result in results.values()
        ):
            raise ValueError(
                "a benchmark worker was produced but its environment identity "
                "could not be captured before execution"
            )
        if len(produced_identities) > 1:
            details = ", ".join(
                f"{identity.name}@{identity.version} ({identity.fingerprint})"
                for identity in sorted(
                    produced_identities,
                    key=lambda item: (item.name, item.version, item.fingerprint),
                )
            )
            raise ValueError(
                "environment_factory produced inconsistent environment identities across jobs: "
                + details
            )
        if produced_identities:
            environment_identity = next(iter(produced_identities))
        else:
            environment_identity = _environment_identity(self.env)

        runtime_fingerprints = sorted(
            {
                result.runtime_fingerprint
                for result in results.values()
                if result.runtime_fingerprint is not None
            }
        )
        if not runtime_fingerprints and self._runtime_factory is None:
            runtime_fingerprints = [_local_runtime_fingerprint(self.env)]

        cases = [_case_result(key, results[key]) for key, _task in jobs]
        self._traces = []
        for _key, result in results.items():
            item = result.item
            if isinstance(item, Rollout):
                self._traces.append(item.trace)
            elif result.failure_trace is not None:
                self._traces.append(result.failure_trace)
        model_stats = {
            model: _aggregate(model, [case for case in cases if case.key.model == model])
            for model in self.models
        }
        win_rates, win_rate_pairs = _win_rates(
            self.models, cases, primary_metric=self.primary_metric
        )
        completed_at = datetime.now(timezone.utc)
        status: Literal["completed", "completed_with_failures"] = (
            "completed_with_failures"
            if any(case.failure_type is not None for case in cases)
            else "completed"
        )
        metadata: dict[str, Any] = {
            "repeats": self.repeats,
            "tasks": len(task_list),
            "environment_fingerprint": environment_identity.fingerprint,
        }
        if dataset_metadata is not None:
            metadata["task_dataset"] = dataset_metadata.model_dump(mode="json")
        metadata["task_set"] = task_set_metadata.model_dump(mode="json")
        self.report = Report(
            environment=environment_identity.name,
            environment_version=environment_identity.version,
            name=self.name,
            description=self.description,
            primary_metric=self.primary_metric,
            models=model_stats,
            win_rates=win_rates,
            cases=cases,
            win_rate_pairs=win_rate_pairs,
            manifest=RunManifest(
                started_at=started_at,
                completed_at=completed_at,
                environment=environment_identity.name,
                environment_version=environment_identity.version,
                environment_fingerprint=environment_identity.fingerprint,
                runtime_fingerprints=runtime_fingerprints,
                targets=list(self.models),
                task_ids=task_ids,
                repeats=self.repeats,
                concurrency=self.concurrency,
                task_set=task_set_metadata,
                task_dataset=dataset_metadata,
                status=status,
                benchmark_name=self.name,
                primary_metric=self.primary_metric,
            ),
            metadata=metadata,
        )
        return self.report


def _environment_identity(environment: Any) -> _EnvironmentIdentity:
    """Capture canonical environment identity before job execution.

    Returns:
        Validated environment identity.
    """
    name = environment.name
    version_value = environment.version
    fingerprint = environment.fingerprint()
    if not isinstance(name, str) or not name:
        raise ValueError("environment name must be a non-empty string")
    if not isinstance(version_value, str) or not version_value:
        raise ValueError("environment version must be a non-empty string")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("environment fingerprint() must return a non-empty string")
    return _EnvironmentIdentity(name=name, version=version_value, fingerprint=fingerprint)


def _local_runtime_fingerprint(environment: Any) -> str:
    """Fingerprint the default in-process runtime for an environment.

    Returns:
        Stable runtime fingerprint.
    """
    tools = getattr(environment, "action_functions", {})
    configured_tools = dict(tools) if isinstance(tools, Mapping) else {}
    return runtime_fingerprint(LocalRuntime(configured_tools))


def _case_result(key: CaseKey, result: _JobOutcome) -> CaseResult:
    item = result.item
    if isinstance(item, Exception):
        trace = result.failure_trace
        return CaseResult(
            key=key,
            trace_id=trace.trace_id if trace is not None else None,
            trace_kind=trace.trace_kind if trace is not None else None,
            episode_trace_id=trace.episode_trace_id if trace is not None else None,
            stop_reason=trace.stop_reason if trace is not None else None,
            terminated=trace.terminated if trace is not None else None,
            truncated=trace.truncated if trace is not None else None,
            failure_type=type(item).__name__,
            failure_message=str(item),
            runtime_fingerprint=result.runtime_fingerprint,
        )
    outcome = item.trace.outcome
    nonfinite_path = _find_nonfinite(
        {
            "reward": outcome.reward if outcome is not None else None,
            "scores": outcome.scores if outcome is not None else {},
            "metrics": item.trace.metrics,
        }
    )
    if nonfinite_path is not None:
        return CaseResult(
            key=key,
            trace_id=item.trace.trace_id,
            trace_kind=item.trace.trace_kind,
            episode_trace_id=item.trace.episode_trace_id,
            stop_reason=item.trace.stop_reason,
            terminated=item.trace.terminated,
            truncated=item.trace.truncated,
            failure_type="NonFiniteResult",
            failure_message=f"non-finite numeric value at {nonfinite_path}",
            runtime_fingerprint=result.runtime_fingerprint,
        )
    return CaseResult(
        key=key,
        trace_id=item.trace.trace_id,
        trace_kind=item.trace.trace_kind,
        episode_trace_id=item.trace.episode_trace_id,
        stop_reason=item.trace.stop_reason,
        reward=outcome.reward if outcome is not None else None,
        scores=dict(sorted(outcome.scores.items())) if outcome is not None else {},
        metrics=dict(sorted(item.trace.metrics.items())),
        terminated=item.trace.terminated,
        truncated=item.trace.truncated,
        runtime_fingerprint=result.runtime_fingerprint,
    )


def _find_nonfinite(value: Any, path: str = "result") -> str | None:
    """Return the first path containing a non-finite float."""
    if isinstance(value, float):
        return path if not math.isfinite(value) else None
    if isinstance(value, Mapping):
        for key, item in value.items():
            found = _find_nonfinite(item, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _find_nonfinite(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _aggregate(model: str, items: list[CaseResult]) -> ModelStats:
    rewards: list[float] = []
    score_lists: dict[str, list[float]] = {}
    latencies: list[float] = []
    costs: list[float] = []
    failures = 0
    failure_reasons: dict[str, int] = {}

    for item in items:
        if item.failure_type is not None:
            failures += 1
            key = item.failure_type
            failure_reasons[key] = failure_reasons.get(key, 0) + 1
            continue
        if item.reward is not None:
            rewards.append(item.reward)
        for name, value in item.scores.items():
            score_lists.setdefault(name, []).append(value)
        latency = item.metrics.get("latency_ms")
        cost = item.metrics.get("cost")
        if latency is not None:
            latencies.append(float(latency))
        if cost is not None:
            costs.append(float(cost))

    mean_reward = statistics.fmean(rewards) if rewards else None
    reward_stddev = statistics.stdev(rewards) if len(rewards) >= 2 else None
    confidence_radius = (
        1.96 * reward_stddev / math.sqrt(len(rewards)) if reward_stddev is not None else None
    )
    return ModelStats(
        model=model,
        n=len(items) - failures,
        failures=failures,
        mean_reward=mean_reward,
        reward_stddev=reward_stddev,
        reward_ci95_lower=(
            mean_reward - confidence_radius
            if mean_reward is not None and confidence_radius is not None
            else None
        ),
        reward_ci95_upper=(
            mean_reward + confidence_radius
            if mean_reward is not None and confidence_radius is not None
            else None
        ),
        mean_scores={k: statistics.fmean(score_lists[k]) for k in sorted(score_lists)},
        mean_latency_ms=statistics.fmean(latencies) if latencies else None,
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        mean_cost=statistics.fmean(costs) if costs else None,
        total_cost=sum(costs),
        failure_reasons=dict(sorted(failure_reasons.items())),
    )


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = q * (len(ordered) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - idx) + ordered[hi] * (idx - lo)


def case_metric(case: CaseResult, primary_metric: str) -> float | None:
    """Return the comparable value for one case on the chosen metric."""
    path = (primary_metric or "reward").strip()
    if path in {"reward", "mean_reward"}:
        return case.reward
    if path in {"latency_ms", "mean_latency_ms"}:
        value = case.metrics.get("latency_ms")
        return float(value) if isinstance(value, (int, float)) else None
    if path in {"cost", "mean_cost"}:
        value = case.metrics.get("cost")
        return float(value) if isinstance(value, (int, float)) else None
    name = path.split(".", 1)[1] if path.startswith("scores.") else path
    value = case.scores.get(name)
    return float(value) if isinstance(value, (int, float)) else None


def _metric_lower_is_better(primary_metric: str) -> bool:
    tail = primary_metric.split(".")[-1]
    return tail in {"latency_ms", "mean_latency_ms", "cost", "mean_cost"}


def _win_rates(
    models: list[str],
    cases: list[CaseResult],
    *,
    primary_metric: str = "reward",
) -> tuple[dict[str, dict[str, float]], list[WinRatePair]]:
    result: dict[str, dict[str, float]] = {model: {} for model in models}
    pairs: list[WinRatePair] = []
    lower = _metric_lower_is_better(primary_metric)
    by_slot = {(case.key.model, case.key.task_id, case.key.repeat): case for case in cases}
    slots = [(case.key.task_id, case.key.repeat) for case in cases if case.key.model == models[0]]
    for i, a in enumerate(models):
        for b in models[i + 1 :]:
            wins = 0
            losses = 0
            ties = 0
            excluded = 0
            for task_id, repeat in slots:
                a_case = by_slot[(a, task_id, repeat)]
                b_case = by_slot[(b, task_id, repeat)]
                a_value = case_metric(a_case, primary_metric)
                b_value = case_metric(b_case, primary_metric)
                if a_value is None or b_value is None:
                    excluded += 1
                elif a_value == b_value:
                    ties += 1
                elif (a_value < b_value) if lower else (a_value > b_value):
                    wins += 1
                else:
                    losses += 1
            compared = wins + losses + ties
            rate = (wins + 0.5 * ties) / compared if compared else None
            pairs.append(
                WinRatePair(
                    model_a=a,
                    model_b=b,
                    wins=wins,
                    losses=losses,
                    ties=ties,
                    compared=compared,
                    excluded=excluded,
                    win_rate=rate,
                )
            )
            if rate is not None:
                result[a][b] = rate
                result[b][a] = 1.0 - rate
    return result, pairs


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4g}"


def _validate_comparison_compatibility(
    current: RunManifest | None,
    baseline: RunManifest | None,
) -> None:
    """Reject comparisons whose available run provenance is incompatible."""
    if current is None or baseline is None:
        return
    mismatches: list[str] = []
    if current.environment_fingerprint != baseline.environment_fingerprint:
        mismatches.append("environment fingerprint")
    if current.runtime_fingerprints != baseline.runtime_fingerprints:
        mismatches.append("runtime fingerprints")
    current_hash = (
        current.task_set.content_hash
        if current.task_set is not None
        else (current.task_dataset.content_hash if current.task_dataset is not None else None)
    )
    baseline_hash = (
        baseline.task_set.content_hash
        if baseline.task_set is not None
        else (baseline.task_dataset.content_hash if baseline.task_dataset is not None else None)
    )
    if current_hash is not None and baseline_hash is not None and current_hash != baseline_hash:
        mismatches.append("task set content hash")
    if current.task_ids != baseline.task_ids:
        mismatches.append("task IDs")
    if current.repeats != baseline.repeats:
        mismatches.append("repeats")
    if mismatches:
        raise ValueError(
            "cannot compare incompatible benchmark runs: "
            + ", ".join(mismatches)
            + "; pass allow_incompatible=True to override"
        )


def _package_version() -> str:
    """Return the installed package version without importing package exports."""
    try:
        return version("plural")
    except PackageNotFoundError:  # pragma: no cover
        return "0.0.0"
