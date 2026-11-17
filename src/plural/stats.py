"""Honest statistics for results: intervals, paired comparisons, and reliability.

Every headline number carries an interval, and any two numbers that are
compared carry a verdict, never a bare difference:

- :func:`clustered_bootstrap` resamples Tasks with replacement, then attempts
  within each sampled Task, so both Task-to-Task and attempt-to-attempt
  variation reach the interval.
- :func:`compare_configurations` pairs two results on the Tasks they share and
  bootstraps the difference: ``better``, ``worse``, ``within_noise`` when the
  interval crosses zero, or ``not_enough_data`` below ten shared Tasks.
- :func:`pass_hat_k` and :func:`pass_at_k` report reliability: the share of
  Tasks where every attempt passed, and where at least one did.

Resampling is seeded from the Job, so the same results always give the same
interval.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal

from plural.common import FrozenModel

if TYPE_CHECKING:
    from plural.benchmarks.results import ConfigurationResult

BOOTSTRAP_RESAMPLES = 2_000
MIN_SHARED_TASKS = 10
"""Fewest Tasks two results must share before a comparison gives a verdict."""
BOOTSTRAP_METHOD = (
    "95% percentile interval from a clustered bootstrap: 2,000 resamples of Tasks with "
    "replacement, then of attempts within each sampled Task, seeded from the Job."
)
PAIRED_METHOD = (
    "95% percentile interval of the difference from a paired bootstrap over shared Tasks, "
    "2,000 resamples, attempts resampled within each Task, seeded from both results."
)

Verdict = Literal["better", "worse", "within_noise", "not_enough_data"]


class Interval(FrozenModel):
    """A bootstrap interval around a weighted mean.

    Attributes:
        estimate: The weighted mean of Task means on the data as observed.
        low: 2.5th percentile of the resampled means.
        high: 97.5th percentile of the resampled means.
        standard_error: Standard deviation of the resampled means.
        resamples: How many resamples were drawn.
        seed: The seed they were drawn with.
    """

    estimate: float
    low: float
    high: float
    standard_error: float
    resamples: int
    seed: int


class Comparison(FrozenModel):
    """Two configurations compared on the Tasks they share.

    ``a`` is the candidate and ``b`` the baseline, so a positive ``delta``
    means the candidate scored higher.

    Attributes:
        metric: The metric compared, such as ``"score"``.
        delta: Candidate minus baseline, over shared Tasks.
        low: Lower end of the 95% interval of ``delta``.
        high: Upper end of the 95% interval of ``delta``.
        probability_better: Share of resamples in which the candidate came out
            ahead, in the metric's direction.
        verdict: ``better``, ``worse``, ``within_noise``, or ``not_enough_data``.
        shared_tasks: Tasks both configurations have a valid attempt on.
        method: How the interval was computed.
    """

    metric: str = "score"
    delta: float | None = None
    low: float | None = None
    high: float | None = None
    probability_better: float | None = None
    verdict: Verdict
    shared_tasks: int = 0
    method: str = PAIRED_METHOD

    @property
    def summary(self) -> str:
        """One line for a person, with the verdict first.

        Examples:
            >>> Comparison(verdict="not_enough_data", shared_tasks=4).summary
            'not enough data: 4 shared Tasks, 10 needed'
        """
        if self.verdict == "not_enough_data":
            return f"not enough data: {self.shared_tasks} shared Tasks, {MIN_SHARED_TASKS} needed"
        label = self.verdict.replace("_", " ")
        return f"{label}: {self.delta:+.3f} (95% {self.low:+.3f} to {self.high:+.3f})"


def seed_for(*keys: str) -> int:
    """A stable 64-bit seed from identifiers such as a Job ID.

    Returns:
        The same seed for the same keys, in any process.

    Examples:
        >>> seed_for("job-1") == seed_for("job-1")
        True
    """
    digest = hashlib.sha256("\x1f".join(keys).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def clustered_bootstrap(
    tasks: Sequence[tuple[float, Sequence[float]]],
    *,
    seed: int,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> Interval | None:
    """Bootstrap a weighted mean of Task means, resampling Tasks then attempts.

    Args:
        tasks: One ``(weight, attempt values)`` pair per Task with at least one
            valid attempt.
        seed: The resampling seed; see :func:`seed_for`.
        resamples: How many resamples to draw.

    Returns:
        The interval, or ``None`` when no Task has a value.

    Examples:
        >>> interval = clustered_bootstrap([(1.0, [1.0, 1.0]), (1.0, [0.0, 1.0])], seed=7)
        >>> interval.estimate
        0.75
        >>> 0.0 <= interval.low <= interval.estimate <= interval.high <= 1.0
        True
    """
    clusters = [(float(weight), list(values)) for weight, values in tasks if values]
    if not clusters:
        return None
    estimate = _weighted_mean([(weight, _mean(values)) for weight, values in clusters])
    rng = random.Random(seed)
    means = sorted(_resample(clusters, rng) for _ in range(resamples))
    return Interval(
        estimate=estimate,
        low=_percentile(means, 0.025),
        high=_percentile(means, 0.975),
        standard_error=_stdev(means),
        resamples=resamples,
        seed=seed,
    )


def paired_bootstrap(
    a: Mapping[str, Sequence[float]],
    b: Mapping[str, Sequence[float]],
    *,
    weights: Mapping[str, float] | None = None,
    metric: str = "score",
    higher_is_better: bool = True,
    seed: int | None = None,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> Comparison:
    """Compare two sets of per-Task attempt values on the Tasks they share.

    Args:
        a: The candidate's attempt values per Task.
        b: The baseline's attempt values per Task.
        weights: Weight per Task; unlisted Tasks weigh 1.
        metric: The metric's name, for the result.
        higher_is_better: Whether a larger value is better.
        seed: The resampling seed; derived from the data when left out.
        resamples: How many resamples to draw.

    Returns:
        The comparison, with ``not_enough_data`` below ten shared Tasks.

    Examples:
        >>> same = {f"t{i}": [float(i % 2)] for i in range(12)}
        >>> paired_bootstrap(same, same).verdict
        'within_noise'
    """
    shared = sorted(name for name in a.keys() & b.keys() if a[name] and b[name])
    weights = weights or {}
    pairs = [(float(weights.get(name, 1.0)), list(a[name]), list(b[name])) for name in shared]
    if not pairs:
        return Comparison(metric=metric, verdict="not_enough_data", shared_tasks=0)
    sign = 1.0 if higher_is_better else -1.0
    delta = _weighted_mean([(w, _mean(x)) for w, x, _ in pairs]) - _weighted_mean(
        [(w, _mean(y)) for w, _, y in pairs]
    )
    if len(pairs) < MIN_SHARED_TASKS:
        return Comparison(
            metric=metric, delta=delta, verdict="not_enough_data", shared_tasks=len(pairs)
        )
    if seed is None:
        seed = seed_for(metric, *shared, repr(sorted(a.items())), repr(sorted(b.items())))
    rng = random.Random(seed)
    deltas = []
    for _ in range(resamples):
        picked = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        total = sum(w for w, _, _ in picked)
        if total <= 0:
            continue
        mean_a = sum(w * _mean(_draw(x, rng)) for w, x, _ in picked) / total
        mean_b = sum(w * _mean(_draw(y, rng)) for w, _, y in picked) / total
        deltas.append(mean_a - mean_b)
    deltas.sort()
    low, high = _percentile(deltas, 0.025), _percentile(deltas, 0.975)
    ahead = sum(1 for value in deltas if sign * value > 0) / len(deltas)
    if low <= 0 <= high:
        verdict: Verdict = "within_noise"
    elif sign * delta > 0:
        verdict = "better"
    else:
        verdict = "worse"
    return Comparison(
        metric=metric,
        delta=delta,
        low=low,
        high=high,
        probability_better=ahead,
        verdict=verdict,
        shared_tasks=len(pairs),
    )


def compare_configurations(
    a: ConfigurationResult,
    b: ConfigurationResult,
    metric: str = "score",
    *,
    seed: int | None = None,
) -> Comparison:
    """Compare a candidate configuration's result with a baseline's.

    Args:
        a: The candidate's result.
        b: The baseline's result.
        metric: The metric to compare. Only ``"score"`` today.
        seed: The resampling seed; derived from both results when left out.

    Returns:
        The paired comparison over the Tasks both results cover.

    Raises:
        ValueError: When ``metric`` is not one the results carry.

    Examples:
        >>> from plural.benchmarks import AttemptEvidence, BenchmarkScoring
        >>> from plural.benchmarks import aggregate_configuration
        >>> names = [f"t{i}" for i in range(10)]
        >>> attempts = [AttemptEvidence(task=name, status="succeeded", score=1.0) for name in names]
        >>> result = aggregate_configuration(names, attempts, scoring=BenchmarkScoring())
        >>> compare_configurations(result, result).verdict
        'within_noise'
    """
    if metric != "score":
        raise ValueError(
            f"Cannot compare on {metric!r}: results carry only the Verifier score today."
        )
    return paired_bootstrap(
        {task.task: task.attempt_scores for task in a.tasks},
        {task.task: task.attempt_scores for task in b.tasks},
        weights={task.task: task.weight for task in (*a.tasks, *b.tasks)},
        metric=metric,
        seed=seed,
    )


def pass_hat_k(outcomes: Sequence[Sequence[bool]]) -> float | None:
    """pass^k: the share of Tasks where every attempt passed.

    Returns:
        The share, or ``None`` with no Task attempted.

    Examples:
        >>> pass_hat_k([[True, True, True], [True, False, True]])
        0.5
    """
    tasks = [item for item in outcomes if item]
    return sum(all(item) for item in tasks) / len(tasks) if tasks else None


def pass_at_k(outcomes: Sequence[Sequence[bool]]) -> float | None:
    """pass@k: the share of Tasks where at least one attempt passed.

    Returns:
        The share, or ``None`` with no Task attempted.

    Examples:
        >>> pass_at_k([[False, False], [False, True]])
        0.5
    """
    tasks = [item for item in outcomes if item]
    return sum(any(item) for item in tasks) / len(tasks) if tasks else None


class ScoreSummary(FrozenModel):
    """A headline score with its interval and reliability, for one configuration.

    Attributes:
        estimate: The mean of Task means.
        interval: The 95% clustered-bootstrap interval, or ``None`` with fewer
            than two scored Tasks.
        success_rate: The share of attempts that reached the success threshold.
            This is not the pass rate, which counts Trials that passed every
            gate (``AgentAggregate.pass_rate``).
        pass_hat_k: pass^k: the share of Tasks where every attempt reached the
            success threshold.
        k: The most attempts any Task had.
        tasks: Scored Tasks.
        attempts: Scored attempts.
    """

    estimate: float
    interval: Interval | None = None
    success_rate: float
    pass_hat_k: float | None = None
    k: int
    tasks: int
    attempts: int

    @property
    def summary(self) -> str:
        """One line for a person: the score, its interval, and pass^k.

        Examples:
            >>> score_summary({"a": [1.0, 0.0], "b": [1.0, 1.0]}, seed=1).summary
            'score 0.75 (95% 0.25 to 1.00), success rate 75%, pass^2 50%, over 2 Tasks'
        """
        text = f"score {self.estimate:.2f}"
        if self.interval is not None:
            text += f" (95% {self.interval.low:.2f} to {self.interval.high:.2f})"
        text += f", success rate {self.success_rate:.0%}"
        if self.k > 1 and self.pass_hat_k is not None:
            text += f", pass^{self.k} {self.pass_hat_k:.0%}"
        return text + f", over {self.tasks} Task{'s' if self.tasks != 1 else ''}"


def score_summary(
    attempts: Mapping[str, Sequence[float | None]],
    *,
    threshold: float = 1.0,
    seed: int,
) -> ScoreSummary | None:
    """Summarize scores by Task: the mean, its interval, success rate, and pass^k.

    Args:
        attempts: Each Task's attempt scores; ``None`` attempts are left out.
        threshold: The score that counts as a success.
        seed: The bootstrap seed; see :func:`seed_for`.

    Returns:
        The summary, or ``None`` when no attempt has a score.

    Examples:
        >>> summary = score_summary({"a": [1.0, 1.0, 1.0], "b": [1.0, 0.0, None]}, seed=1)
        >>> summary.estimate, summary.pass_hat_k, summary.k
        (0.75, 0.5, 3)
    """
    scored = {
        task: [float(value) for value in values if value is not None]
        for task, values in sorted(attempts.items())
    }
    scored = {task: values for task, values in scored.items() if values}
    if not scored:
        return None
    flat = [value for values in scored.values() for value in values]
    outcomes = [[value >= threshold for value in values] for values in scored.values()]
    interval = (
        clustered_bootstrap([(1.0, values) for values in scored.values()], seed=seed)
        if len(scored) > 1
        else None
    )
    return ScoreSummary(
        estimate=_weighted_mean([(1.0, _mean(values)) for values in scored.values()]),
        interval=interval,
        success_rate=sum(value >= threshold for value in flat) / len(flat),
        pass_hat_k=pass_hat_k(outcomes),
        k=max(len(values) for values in scored.values()),
        tasks=len(scored),
        attempts=len(flat),
    )


def _resample(clusters: Sequence[tuple[float, list[float]]], rng: random.Random) -> float:
    picked = [clusters[rng.randrange(len(clusters))] for _ in clusters]
    return _weighted_mean([(weight, _mean(_draw(values, rng))) for weight, values in picked])


def _draw(values: Sequence[float], rng: random.Random) -> list[float]:
    if len(values) == 1:
        return [values[0]]
    return [values[rng.randrange(len(values))] for _ in values]


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _weighted_mean(items: Sequence[tuple[float, float]]) -> float:
    total = math.fsum(weight for weight, _ in items)
    if total <= 0:
        return 0.0
    return math.fsum(weight * value for weight, value in items) / total


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    if not ordered:
        return math.nan
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1))


__all__ = [
    "BOOTSTRAP_METHOD",
    "BOOTSTRAP_RESAMPLES",
    "MIN_SHARED_TASKS",
    "PAIRED_METHOD",
    "Comparison",
    "Interval",
    "ScoreSummary",
    "Verdict",
    "clustered_bootstrap",
    "compare_configurations",
    "paired_bootstrap",
    "pass_at_k",
    "pass_hat_k",
    "score_summary",
    "seed_for",
]
