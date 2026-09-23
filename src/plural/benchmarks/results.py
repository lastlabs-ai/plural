"""Combine the attempts of one configuration into a release result.

The order is fixed. Each attempt is first classified: scored by a Verifier, an
Agent failure, an infrastructure error, cancelled, or still pending. Repeated
attempts of a Task are averaged. Tasks are then combined with the release's
declared weights. Nothing here picks a best attempt, and step rewards never
enter: only the Verifier score recorded on each attempt is read.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from pydantic import Field

from plural.benchmarks.rules import BenchmarkCategory, BenchmarkScoring
from plural.common import FrozenModel

AttemptOutcome = Literal["scored", "agent_failure", "infrastructure_error", "cancelled", "pending"]

_PENDING = {"queued", "provisioning", "running", "verifying", "awaiting_review"}
_BUDGET_STOPS = {"max_turns", "max_seconds", "max_cost"}
# The evaluated system produced no valid answer. On an agents track the harness
# is part of that system, so its failures count against it.
_AGENT_ERRORS = {"harness_failed", "protocol_failed", "evidence_missing"}

INTERVAL_METHOD = (
    "95% normal-approximation interval over Task scores, treating the release's "
    "Tasks as a sample. Attempt-to-attempt variation within a Task is not included."
)


class AttemptEvidence(FrozenModel):
    """One attempt of one Task, as recorded on a Trial.

    Attributes:
        task: Task name within the release.
        attempt: Attempt index, starting at 0.
        status: Trial status.
        score: Verifier-derived Trial score, when one was produced.
        error_code: Failure category, when the attempt failed.
        stop_reason: How the episode ended.
        cost_usd: Measured cost of the attempt in US dollars.
        latency_seconds: Measured wall time of the attempt in seconds.
        trial_id: Trial identifier, for evidence links.
        evaluation_id: Job identifier the attempt belongs to.
    """

    task: str
    attempt: int = 0
    status: str
    score: float | None = None
    error_code: str | None = None
    stop_reason: str | None = None
    cost_usd: float | None = None
    latency_seconds: float | None = None
    trial_id: str | None = None
    evaluation_id: str | None = None


class TaskSpec(FrozenModel):
    """A Task as the release declares it for scoring.

    Attributes:
        name: Task name within the release.
        weight: Declared weight.
        categories: Category ids the Task belongs to.
    """

    name: str
    weight: float = Field(default=1.0, gt=0)
    categories: tuple[str, ...] = ()


class Uncertainty(FrozenModel):
    """An interval around a score, or the reason there is none.

    Attributes:
        low: Lower bound, when reported.
        high: Upper bound, when reported.
        standard_error: Standard error, when reported.
        sample_size: Number of scored Tasks the interval uses.
        method: How the interval was computed.
        unavailable_reason: Why no interval is shown.
    """

    low: float | None = None
    high: float | None = None
    standard_error: float | None = None
    sample_size: int = 0
    method: str | None = None
    unavailable_reason: str | None = None


class MeasuredMean(FrozenModel):
    """A mean over the attempts that reported a measurement.

    Attributes:
        value: Mean per attempt, or ``None`` when nothing was measured.
        unit: Unit of ``value``, such as ``"USD per attempt"``.
        measured: Attempts that reported this measurement.
        attempts: Attempts that ran, the intended denominator.
    """

    value: float | None = None
    unit: str
    measured: int = 0
    attempts: int = 0

    @property
    def complete(self) -> bool:
        """Whether every attempt that ran reported this measurement."""
        return self.attempts > 0 and self.measured == self.attempts


class TaskResult(FrozenModel):
    """Every attempt of one Task, combined.

    Attributes:
        task: Task name.
        weight: Declared weight.
        categories: Category ids.
        attempts: Attempts recorded, in every outcome.
        scored: Attempts with a Verifier score.
        agent_failures: Attempts the Agent ended without a Verifier score.
        infrastructure_errors: Attempts lost to the runtime or provider.
        cancelled: Attempts cancelled before they finished.
        pending: Attempts still running or awaiting review.
        valid: Attempts that count toward the score.
        successes: Valid attempts at or above the success threshold.
        score: Mean valid score, or ``None`` when the Task has none.
        success_rate: ``successes / valid``, when a threshold is declared.
        score_min: Lowest valid score.
        score_max: Highest valid score.
        complete: Whether the Task has the attempts the track requires.
        trial_ids: Trials behind this result, in attempt order.
    """

    task: str
    weight: float
    categories: tuple[str, ...] = ()
    attempts: int = 0
    scored: int = 0
    agent_failures: int = 0
    infrastructure_errors: int = 0
    cancelled: int = 0
    pending: int = 0
    valid: int = 0
    successes: int = 0
    score: float | None = None
    success_rate: float | None = None
    score_min: float | None = None
    score_max: float | None = None
    complete: bool = False
    trial_ids: tuple[str, ...] = ()

    @property
    def covered(self) -> bool:
        """Whether the Task has at least one valid attempt."""
        return self.valid > 0


class CategoryResult(FrozenModel):
    """Tasks in one category, combined with the same rules as the whole release.

    Attributes:
        id: Category id.
        name: Category label.
        taxonomy: Shared classification, when declared.
        score: Weighted score over covered Tasks in the category.
        tasks_total: Tasks in the category.
        tasks_covered: Tasks in the category with a valid attempt.
        coverage: Weighted share of the category's Tasks that are covered.
        success_rate: Share of valid attempts that succeeded.
    """

    id: str
    name: str
    taxonomy: str | None = None
    score: float | None = None
    tasks_total: int = 0
    tasks_covered: int = 0
    coverage: float = 0
    success_rate: float | None = None


class ConfigurationResult(FrozenModel):
    """One exact configuration's result on one release and track.

    Attributes:
        score: Weighted score over covered Tasks.
        coverage: Weighted share of Tasks with at least one valid attempt.
        complete_coverage: Weighted share of Tasks with every required attempt.
        tasks_total: Tasks in the release.
        tasks_covered: Tasks with at least one valid attempt.
        success_rate: Share of valid attempts that succeeded.
        completion_rate: Share of attempts that ran to a Verifier score,
            separate from whether they succeeded.
        uncertainty: Interval around ``score``, or why there is none.
        cost: Mean measured cost per attempt.
        latency: Mean measured wall time per attempt.
        outcomes: Attempts by outcome.
        tasks: Per-Task results, in release order.
        categories: Per-category results, in release order.
        eligible: Whether the result may be ranked officially.
        ineligible_reasons: Why it may not be ranked, when it may not.
    """

    score: float | None = None
    coverage: float = 0
    complete_coverage: float = 0
    tasks_total: int = 0
    tasks_covered: int = 0
    success_rate: float | None = None
    completion_rate: float | None = None
    uncertainty: Uncertainty = Field(default_factory=Uncertainty)
    cost: MeasuredMean = Field(default_factory=lambda: MeasuredMean(unit="USD per attempt"))
    latency: MeasuredMean = Field(default_factory=lambda: MeasuredMean(unit="seconds per attempt"))
    outcomes: dict[str, int] = Field(default_factory=dict)
    tasks: tuple[TaskResult, ...] = ()
    categories: tuple[CategoryResult, ...] = ()
    eligible: bool = False
    ineligible_reasons: tuple[str, ...] = ()


def classify_attempt(attempt: AttemptEvidence) -> AttemptOutcome:
    """Decide which outcome one attempt had.

    A Verifier score always means ``"scored"``. A failure with no score is an
    Agent failure when the Agent's own system caused it (a budget ran out, or
    the harness produced no valid answer) and an infrastructure error when the
    runtime, provider, or Verifier did.

    Returns:
        The attempt's outcome.
    """
    if attempt.status in _PENDING:
        return "pending"
    if attempt.score is not None and math.isfinite(attempt.score):
        return "scored"
    if attempt.status == "cancelled" or attempt.error_code == "cancelled":
        return "cancelled"
    if attempt.stop_reason in _BUDGET_STOPS:
        return "agent_failure"
    if attempt.error_code in _AGENT_ERRORS:
        return "agent_failure"
    return "infrastructure_error"


def _weighted_mean(pairs: Iterable[tuple[float, float]]) -> float | None:
    items = list(pairs)
    total = sum(weight for _, weight in items)
    if not items or total <= 0:
        return None
    return sum(value * weight for value, weight in items) / total


def _task_result(
    spec: TaskSpec,
    attempts: Sequence[AttemptEvidence],
    scoring: BenchmarkScoring,
    required_attempts: int,
) -> TaskResult:
    low, _ = scoring.score_range
    counts: dict[str, int] = {}
    values: list[float] = []
    for attempt in attempts:
        outcome = classify_attempt(attempt)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome == "scored" and attempt.score is not None:
            values.append(float(attempt.score))
        elif outcome == "agent_failure" and scoring.agent_failure == "zero":
            values.append(low)
    threshold = scoring.success_threshold
    successes = sum(value >= threshold for value in values) if threshold is not None else 0
    return TaskResult(
        task=spec.name,
        weight=spec.weight,
        categories=spec.categories,
        attempts=len(attempts),
        scored=counts.get("scored", 0),
        agent_failures=counts.get("agent_failure", 0),
        infrastructure_errors=counts.get("infrastructure_error", 0),
        cancelled=counts.get("cancelled", 0),
        pending=counts.get("pending", 0),
        valid=len(values),
        successes=successes,
        score=sum(values) / len(values) if values else None,
        success_rate=(successes / len(values)) if values and threshold is not None else None,
        score_min=min(values) if values else None,
        score_max=max(values) if values else None,
        complete=len(values) >= required_attempts,
        trial_ids=tuple(
            attempt.trial_id
            for attempt in sorted(attempts, key=lambda item: item.attempt)
            if attempt.trial_id
        ),
    )


def _uncertainty(
    tasks: Sequence[TaskResult], score: float | None, scoring: BenchmarkScoring
) -> Uncertainty:
    scored = [task for task in tasks if task.score is not None]
    n = len(scored)
    if score is None or n < scoring.min_tasks_for_interval:
        return Uncertainty(
            sample_size=n,
            unavailable_reason=(
                f"Needs at least {scoring.min_tasks_for_interval} scored Tasks; "
                f"this result has {n}."
            ),
        )
    total = sum(task.weight for task in scored)
    variance = (
        n
        / (n - 1)
        * sum((task.weight / total) ** 2 * (float(task.score or 0) - score) ** 2 for task in scored)
    )
    error = math.sqrt(variance)
    low, high = scoring.score_range
    return Uncertainty(
        low=max(low, score - 1.96 * error),
        high=min(high, score + 1.96 * error),
        standard_error=error,
        sample_size=n,
        method=INTERVAL_METHOD,
    )


def _measured(values: Sequence[float | None], ran: int, unit: str) -> MeasuredMean:
    present = [float(value) for value in values if value is not None and math.isfinite(value)]
    return MeasuredMean(
        value=sum(present) / len(present) if present else None,
        unit=unit,
        measured=len(present),
        attempts=ran,
    )


def aggregate_configuration(
    task_names: Sequence[str],
    attempts: Sequence[AttemptEvidence],
    *,
    scoring: BenchmarkScoring,
    categories: Sequence[BenchmarkCategory] = (),
    required_attempts: int = 1,
    blocking_issues: Sequence[str] = (),
) -> ConfigurationResult:
    """Combine one configuration's attempts on one release and track.

    ``attempts`` must already be limited to the evaluations that contribute to
    this result. Attempts for Tasks outside the release are ignored. Weights
    come from ``scoring`` and membership from ``categories``, both declared by
    the release.

    Args:
        task_names: The release's Task names, in order.
        attempts: Every contributing attempt.
        scoring: The release's scoring rules.
        categories: The release's categories.
        required_attempts: Attempts per Task the track requires.
        blocking_issues: Reasons found elsewhere, such as a track conformance
            problem or missing provenance, that prevent official ranking.

    Returns:
        The combined result, with per-Task and per-category evidence.
    """
    tasks = task_specs(task_names, scoring, categories)
    by_task: dict[str, list[AttemptEvidence]] = {spec.name: [] for spec in tasks}
    for attempt in attempts:
        if attempt.task in by_task:
            by_task[attempt.task].append(attempt)
    task_results = tuple(
        _task_result(spec, by_task[spec.name], scoring, required_attempts) for spec in tasks
    )
    total_weight = sum(task.weight for task in task_results)
    covered = [task for task in task_results if task.covered]
    score = _weighted_mean((float(task.score or 0), task.weight) for task in covered)
    coverage = sum(task.weight for task in covered) / total_weight if total_weight else 0.0
    complete_coverage = (
        sum(task.weight for task in task_results if task.complete) / total_weight
        if total_weight
        else 0.0
    )

    outcomes: dict[str, int] = {}
    for attempt in attempts:
        if attempt.task in by_task:
            outcome = classify_attempt(attempt)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
    ran = outcomes.get("scored", 0) + outcomes.get("agent_failure", 0)
    finished = ran + outcomes.get("infrastructure_error", 0)
    valid = sum(task.valid for task in task_results)
    successes = sum(task.successes for task in task_results)
    counted = [
        attempt
        for attempt in attempts
        if attempt.task in by_task and classify_attempt(attempt) in {"scored", "agent_failure"}
    ]

    category_results: list[CategoryResult] = []
    for category in categories:
        members = [task for task in task_results if task.task in category.tasks]
        member_weight = sum(task.weight for task in members)
        members_covered = [task for task in members if task.covered]
        member_valid = sum(task.valid for task in members_covered)
        category_results.append(
            CategoryResult(
                id=category.id,
                name=category.name,
                taxonomy=category.taxonomy,
                score=_weighted_mean(
                    (float(task.score or 0), task.weight) for task in members_covered
                ),
                tasks_total=len(members),
                tasks_covered=len(members_covered),
                coverage=(
                    sum(task.weight for task in members_covered) / member_weight
                    if member_weight
                    else 0.0
                ),
                success_rate=(
                    sum(task.successes for task in members_covered) / member_valid
                    if member_valid and scoring.success_threshold is not None
                    else None
                ),
            )
        )

    reasons = list(blocking_issues)
    if complete_coverage + 1e-9 < scoring.coverage_required:
        missing = [task.task for task in task_results if not task.complete]
        reasons.append(
            f"Covers {complete_coverage:.0%} of Tasks with {required_attempts} "
            f"attempt{'s' if required_attempts != 1 else ''} each; the release requires "
            f"{scoring.coverage_required:.0%}. Missing: {', '.join(missing[:5])}"
            + ("…" if len(missing) > 5 else "")
            + "."
        )
    pending = outcomes.get("pending", 0)
    if pending:
        reasons.append(f"{pending} attempt{'s are' if pending != 1 else ' is'} still pending.")

    return ConfigurationResult(
        score=score,
        coverage=coverage,
        complete_coverage=complete_coverage,
        tasks_total=len(task_results),
        tasks_covered=len(covered),
        success_rate=(
            successes / valid if valid and scoring.success_threshold is not None else None
        ),
        completion_rate=(outcomes.get("scored", 0) / finished) if finished else None,
        uncertainty=_uncertainty(task_results, score, scoring),
        cost=_measured([item.cost_usd for item in counted], ran, "USD per attempt"),
        latency=_measured([item.latency_seconds for item in counted], ran, "seconds per attempt"),
        outcomes=outcomes,
        tasks=task_results,
        categories=tuple(category_results),
        eligible=not reasons,
        ineligible_reasons=tuple(reasons),
    )


def task_specs(
    task_names: Sequence[str],
    scoring: BenchmarkScoring,
    categories: Sequence[BenchmarkCategory],
) -> tuple[TaskSpec, ...]:
    """Build the scoring view of a release's Tasks from its declarations.

    Returns:
        One spec per Task, in release order.
    """
    membership: Mapping[str, tuple[str, ...]] = {
        name: tuple(category.id for category in categories if name in category.tasks)
        for name in task_names
    }
    return tuple(
        TaskSpec(name=name, weight=scoring.weight(name), categories=membership[name])
        for name in task_names
    )


__all__ = [
    "INTERVAL_METHOD",
    "AttemptEvidence",
    "AttemptOutcome",
    "CategoryResult",
    "ConfigurationResult",
    "MeasuredMean",
    "TaskResult",
    "TaskSpec",
    "Uncertainty",
    "aggregate_configuration",
    "classify_attempt",
    "task_specs",
]
