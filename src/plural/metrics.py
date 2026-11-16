"""Metrics: named, declared measurements of an episode.

A Verifier declares the metrics it produces. Its ``check`` returns their
values at the end of the episode, and its ``measure`` hook returns values for
a **running** metric after each step, which the App host records and this
module reduces to one number with the metric's ``aggregate``. A value of
``None`` means the metric does not apply to this episode, such as a price
check on a correct handoff: it is left out of every aggregate, and an
aggregate says how many Trials it covers.

Metrics are measurements, not credit. They never enter the reward ledger, and
nothing here reaches the Agent.

Five built-in metrics need no Verifier: ``cost_usd``, ``latency_seconds``,
``turns``, ``total_tokens``, and ``succeeded``.

Examples:
    >>> from plural.metrics import MetricSpec, aggregate_series
    >>> cash = MetricSpec(name="cash_on_hand", kind="running", unit="USD", aggregate="final")
    >>> aggregate_series([(1, 100.0), (2, 140.0), (3, 120.0)], cash)
    120.0
    >>> aggregate_series([], cash) is None
    True
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, model_validator

from plural.common import FrozenModel

MetricKind = Literal["binary", "score", "number", "rating", "running"]
Aggregate = Literal["final", "mean", "min", "max", "auc", "time_to"]
Direction = Literal["higher", "lower"]
MetricSource = Literal["agent", "environment"]

METRICS_FILE = "metrics.jsonl"
"""The App host's record of every running metric point, in its private folder."""

_SLUG = re.compile(r"^[a-z][a-z0-9_]*$")


class MetricSpec(FrozenModel):
    """One metric a Verifier declares: what it measures and which way is better.

    ``range`` bounds a ``score`` (by default 0 to 1) or a ``rating`` (required).
    A ``running`` metric is sampled after every step and needs an
    ``aggregate`` to become one number per Trial; ``time_to`` also needs a
    ``threshold``, and counts the steps until the value first crosses it in the
    good direction.

    Examples:
        >>> MetricSpec(name="price_correct", kind="binary").range
        (0.0, 1.0)
        >>> MetricSpec(name="tone", kind="rating", range=(1, 5)).direction
        'higher'
    """

    name: str = Field(min_length=1, max_length=64)
    kind: MetricKind = "score"
    unit: str | None = None
    direction: Direction = "higher"
    range: tuple[float, float] | None = None
    aggregate: Aggregate | None = None
    threshold: float | None = None
    description: str = ""

    @model_validator(mode="before")
    @classmethod
    def _defaults(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        kind = payload.get("kind", "score")
        if payload.get("range") is None and kind in {"score", "binary"}:
            payload["range"] = (0.0, 1.0)
        if kind == "running" and payload.get("aggregate") == "time_to":
            # Steps until a threshold: fewer is better, whatever the series' direction.
            payload.setdefault("unit", "steps")
        return payload

    @model_validator(mode="after")
    def _valid(self) -> MetricSpec:
        if not _SLUG.match(self.name):
            raise ValueError(
                f"metric name {self.name!r} must be lowercase letters, digits, and "
                "underscores, starting with a letter"
            )
        if self.kind == "rating" and self.range is None:
            raise ValueError(f"rating metric {self.name!r} needs a range, such as [1, 5]")
        if self.range is not None and not self.range[0] < self.range[1]:
            raise ValueError(f"metric {self.name!r}: range must run from low to high")
        if self.kind == "running" and self.aggregate is None:
            raise ValueError(
                f"running metric {self.name!r} needs an aggregate: final, mean, min, max, "
                "auc, or time_to"
            )
        if self.kind != "running" and self.aggregate is not None:
            raise ValueError(
                f"only a running metric has an aggregate; {self.name!r} is {self.kind}"
            )
        if self.aggregate == "time_to" and self.threshold is None:
            raise ValueError(
                f"running metric {self.name!r} with aggregate time_to needs a threshold"
            )
        return self

    @property
    def trial_direction(self) -> Direction:
        """Which way is better for the metric's per-Trial value.

        A ``time_to`` aggregate counts steps, so fewer is better whatever the
        series' own direction.
        """
        return "lower" if self.aggregate == "time_to" else self.direction

    def check_value(self, value: float | None) -> float | None:
        """Validate one value of this metric.

        Returns:
            The value as a float, or ``None`` when it does not apply.

        Raises:
            ValueError: When it is not finite, a binary value is not 0 or 1, or
                a ``score`` or ``rating`` is outside its range.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            value = float(value)
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"metric {self.name!r} must be a finite number, not {value!r}")
        if self.kind == "binary" and number not in {0.0, 1.0}:
            raise ValueError(f"binary metric {self.name!r} must be 0 or 1, not {value!r}")
        if self.kind in {"score", "rating"} and self.range is not None:
            low, high = self.range
            if not low <= number <= high:
                raise ValueError(
                    f"metric {self.name!r} must be between {low:g} and {high:g}, not {number:g}"
                )
        return number


BUILTIN_METRICS: dict[str, MetricSpec] = {
    spec.name: spec
    for spec in (
        MetricSpec(
            name="cost_usd",
            kind="number",
            unit="USD",
            direction="lower",
            description="What the Trial's model calls cost.",
        ),
        MetricSpec(
            name="latency_seconds",
            kind="number",
            unit="s",
            direction="lower",
            description="Wall time from the start of the Trial to its end.",
        ),
        MetricSpec(
            name="turns",
            kind="number",
            direction="lower",
            description="Actions the Agent took.",
        ),
        MetricSpec(
            name="total_tokens",
            kind="number",
            unit="tokens",
            direction="lower",
            description="Prompt and completion tokens across every model call.",
        ),
        MetricSpec(
            name="succeeded",
            kind="binary",
            description="The episode reached a terminal state without an error or a limit.",
        ),
    )
}
"""Metrics every Trial has, without a Verifier, by name."""


class MetricFailure(FrozenModel):
    """A Verifier whose ``measure`` hook raised or returned something invalid.

    Those steps have no point for its metrics. It never fails the Trial.
    """

    verifier: str
    steps: int = Field(ge=1)
    """How many steps it failed on."""
    error: str
    """The first error."""


def metric_failures(lines: Iterable[Mapping[str, Any]]) -> tuple[MetricFailure, ...]:
    """Group the App host's ``measure`` failures by Verifier.

    Returns:
        One entry per Verifier, with its step count and first error.

    Examples:
        >>> metric_failures([{"verifier": "cash", "error": "boom"}] * 2)
        (MetricFailure(verifier='cash', steps=2, error='boom'),)
    """
    grouped: dict[str, MetricFailure] = {}
    for line in lines:
        name = str(line.get("verifier") or "")
        if not name:
            continue
        seen = grouped.get(name)
        grouped[name] = (
            MetricFailure(verifier=name, steps=1, error=str(line.get("error") or "")[:500])
            if seen is None
            else seen.model_copy(update={"steps": seen.steps + 1})
        )
    return tuple(grouped.values())


def aggregate_series(
    series: Sequence[tuple[int, float]] | Iterable[tuple[int, float]],
    spec: MetricSpec,
    *,
    steps: int | None = None,
) -> float | None:
    """Reduce a running metric's points, ``(step, value)`` in step order, to one number.

    * ``final``: the last value.
    * ``mean``, ``min``, ``max``: over the points.
    * ``auc``: the area under the series by the trapezoid rule over step index,
      divided by the steps it spans, so it is a step-weighted mean that does not
      grow with episode length. One point is its own value.
    * ``time_to``: the first step whose value reaches ``threshold`` in the
      metric's direction (``>=`` for higher, ``<=`` for lower). When it never
      does, the episode's step count plus one, so a miss is always worse than
      the slowest hit.

    Args:
        series: The points, as recorded.
        spec: The metric, with its ``aggregate``.
        steps: The episode's step count, for a ``time_to`` that is never reached.
            By default, the last point's step.

    Returns:
        The aggregate, or ``None`` when there are no points.

    Examples:
        >>> spec = MetricSpec(name="cash", kind="running", aggregate="auc")
        >>> aggregate_series([(0, 0.0), (2, 2.0)], spec)
        1.0
        >>> hit = MetricSpec(name="cash", kind="running", aggregate="time_to", threshold=10)
        >>> aggregate_series([(1, 5.0), (2, 12.0)], hit), aggregate_series([(1, 5.0)], hit)
        (2.0, 2.0)
    """
    points = sorted(((int(step), float(value)) for step, value in series), key=lambda p: p[0])
    if not points:
        return None
    values = [value for _, value in points]
    aggregate = spec.aggregate or "final"
    if aggregate == "final":
        return values[-1]
    if aggregate == "mean":
        return sum(values) / len(values)
    if aggregate == "min":
        return min(values)
    if aggregate == "max":
        return max(values)
    if aggregate == "auc":
        if len(points) == 1:
            return values[0]
        area = sum(
            (right - left) * (low + high) / 2
            for (left, low), (right, high) in zip(points, points[1:], strict=False)
        )
        span = points[-1][0] - points[0][0]
        return area / span if span else sum(values) / len(values)
    threshold = float(spec.threshold if spec.threshold is not None else 0)
    for step, value in points:
        if (value >= threshold) if spec.direction == "higher" else (value <= threshold):
            return float(step)
    return float((steps if steps is not None else points[-1][0]) + 1)


def default_score(specs: Iterable[MetricSpec], values: Mapping[str, float | None]) -> float:
    """The score a Verifier that declares metrics gets when its ``check`` gives none.

    The mean of its applicable ``binary`` and ``score`` metrics, each scaled to
    0 to 1 by its range. With none applicable, as for a Verifier with only
    ``number`` or ``running`` metrics, 1.0: gates and targets live on the
    Scorecard, which decides whether the Trial passes.

    Returns:
        A score from 0 to 1.

    Examples:
        >>> specs = [MetricSpec(name="a", kind="binary"), MetricSpec(name="b", kind="number")]
        >>> default_score(specs, {"a": 0.0, "b": 12.0})
        0.0
        >>> default_score(specs, {"a": None, "b": 12.0})
        1.0
    """
    scaled: list[float] = []
    for spec in specs:
        if spec.kind not in {"binary", "score"}:
            continue
        value = values.get(spec.name)
        if value is None:
            continue
        low, high = spec.range or (0.0, 1.0)
        scaled.append((float(value) - low) / (high - low))
    return sum(scaled) / len(scaled) if scaled else 1.0


class MetricAggregate(FrozenModel):
    """One metric across a set of Trials, such as one Agent's on a Benchmark.

    ``n`` is how many Trials the metric applied to and ``total`` how many there
    were: a ``None`` value is left out, so read ``mean`` as "over n of total".
    For a ``binary`` metric, ``pass_rate`` is the share of applicable Trials
    that passed; with several attempts per Task, ``pass_hat_k`` is the share of
    Tasks where every applicable attempt passed and ``pass_at_k`` where any did.

    Examples:
        >>> spec = MetricSpec(name="ok", kind="binary")
        >>> row = aggregate_metric(spec, {"a": [1.0, 0.0], "b": [1.0, None], "c": [None]})
        >>> (row.n, row.total, row.pass_rate, row.pass_hat_k, row.pass_at_k)
        (3, 5, 0.6666666666666666, 0.5, 1.0)
    """

    name: str
    kind: MetricKind
    direction: Direction = "higher"
    unit: str | None = None
    mean: float | None = None
    n: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    pass_rate: float | None = None
    pass_hat_k: float | None = None
    pass_at_k: float | None = None
    k: int | None = None


def aggregate_metric(
    spec: MetricSpec, values_by_task: Mapping[str, Sequence[float | None]]
) -> MetricAggregate:
    """Aggregate one metric over Trials grouped by Task, leaving out ``None``.

    Args:
        spec: The metric.
        values_by_task: Each Task's attempts' values, ``None`` where it did not apply.

    Returns:
        The mean over applicable Trials, ``n`` of ``total``, and for a binary
        metric its pass rate, pass^k, and pass@k.
    """
    applicable = [
        float(value) for values in values_by_task.values() for value in values if value is not None
    ]
    total = sum(len(values) for values in values_by_task.values())
    mean = sum(applicable) / len(applicable) if applicable else None
    row: dict[str, Any] = {
        "name": spec.name,
        "kind": spec.kind,
        "direction": spec.trial_direction,
        "unit": spec.unit,
        "mean": mean,
        "n": len(applicable),
        "total": total,
    }
    if spec.kind == "binary":
        per_task = [
            [value for value in values if value is not None] for values in values_by_task.values()
        ]
        per_task = [values for values in per_task if values]
        row["pass_rate"] = mean
        if per_task:
            row["k"] = max(len(values) for values in per_task)
            row["pass_hat_k"] = sum(all(v >= 1 for v in values) for values in per_task) / len(
                per_task
            )
            row["pass_at_k"] = sum(any(v >= 1 for v in values) for values in per_task) / len(
                per_task
            )
    return MetricAggregate(**row)


def builtin_values(
    *,
    cost_usd: float | None,
    latency_seconds: float | None,
    turns: int | None,
    total_tokens: int | None,
    succeeded: bool | None,
) -> dict[str, float | None]:
    """The built-in metrics' values for one Trial.

    Returns:
        Each built-in by name; ``None`` where the Trial does not know it.
    """
    return {
        "cost_usd": cost_usd,
        "latency_seconds": latency_seconds,
        "turns": None if turns is None else float(turns),
        "total_tokens": None if total_tokens is None else float(total_tokens),
        "succeeded": None if succeeded is None else float(succeeded),
    }


def series_by_metric(
    points: Iterable[Mapping[str, Any]],
) -> dict[str, list[tuple[int, float]]]:
    """Group ``metrics.jsonl`` lines into one ``(step, value)`` series per metric.

    A point whose value is ``None`` is left out.

    Returns:
        Each metric's series, in step order.

    Examples:
        >>> lines = [{"step": 1, "values": {"cash": 3}}, {"step": 2, "values": {"cash": 5}}]
        >>> series_by_metric(lines)
        {'cash': [(1, 3.0), (2, 5.0)]}
    """
    grouped: dict[str, list[tuple[int, float]]] = {}
    for line in points:
        values = line.get("values")
        if not isinstance(values, Mapping):
            continue
        for name, value in values.items():
            if value is None:
                continue
            try:
                grouped.setdefault(str(name), []).append((int(line.get("step") or 0), float(value)))
            except (TypeError, ValueError):
                continue
    return {name: sorted(items, key=lambda item: item[0]) for name, items in grouped.items()}


__all__ = [
    "BUILTIN_METRICS",
    "METRICS_FILE",
    "Aggregate",
    "Direction",
    "MetricAggregate",
    "MetricFailure",
    "MetricKind",
    "MetricSource",
    "MetricSpec",
    "aggregate_metric",
    "aggregate_series",
    "builtin_values",
    "default_score",
    "metric_failures",
    "series_by_metric",
]
