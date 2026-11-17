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

A metric may be a **gate** (``gate: true``), which must pass, and may have a
``target``. A Trial **passes** when every applicable gate passes; with no
applicable gate it is not judged (``passed`` is ``None``). See :func:`judge`.

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

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
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
_TARGET = re.compile(
    r"^\s*(?:(?P<op>>=|<=|==)\s*(?P<value>-?\d+(?:\.\d+)?)"
    r"|between\s+(?P<low>-?\d+(?:\.\d+)?)\s+(?:and\s+)?(?P<high>-?\d+(?:\.\d+)?))\s*$"
)


def parse_target(text: str) -> tuple[str, float, float | None]:
    """Read a target: ``>= 150``, ``<= 0.5``, ``== 1``, or ``between 1 5``.

    Returns:
        The operator, the value (the low end for ``between``), and the high end.

    Raises:
        ValueError: When the text is not one of those forms.

    Examples:
        >>> parse_target(">= 150")
        ('>=', 150.0, None)
        >>> parse_target("between 3 and 5")
        ('between', 3.0, 5.0)
    """
    match = _TARGET.match(text)
    if match is None:
        raise ValueError(f"target {text!r} must be '>= N', '<= N', '== N', or 'between A B'")
    if match.group("op"):
        return match.group("op"), float(match.group("value")), None
    low, high = float(match.group("low")), float(match.group("high"))
    if low > high:
        raise ValueError(f"target {text!r}: the low end comes first")
    return "between", low, high


def meets(target: str, value: float | None) -> bool | None:
    """Whether a value meets a target.

    Returns:
        ``None`` when the value is ``None``: the metric does not apply.

    Examples:
        >>> meets("<= 0.50", 0.31), meets("between 1 5", 7), meets(">= 1", None)
        (True, False, None)
    """
    if value is None:
        return None
    op, low, high = parse_target(target)
    if op == ">=":
        return value >= low
    if op == "<=":
        return value <= low
    if op == "==":
        return math.isclose(value, low, abs_tol=1e-9)
    assert high is not None
    return low <= value <= high


class MetricSpec(FrozenModel):
    """One metric a Verifier declares: what it measures and which way is better.

    ``range`` bounds a ``score`` (by default 0 to 1) or a ``rating`` (required).
    A ``running`` metric is sampled after every step and needs an
    ``aggregate`` to become one number per Trial; ``time_to`` also needs a
    ``threshold``, and counts the steps until the value first crosses it in the
    good direction.

    ``gate: true`` makes the metric one a Trial must pass: a binary gate passes
    at 1, any other gate when it meets its ``target`` (``>= 150``, ``<= 0.5``,
    ``== 1``, or ``between 1 5``), which a non-binary gate needs. A ``target``
    on a metric that is not a gate is reported, never judged.

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
    gate: bool = False
    target: str | None = None
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
        target = payload.get("target")
        if isinstance(target, (int, float)) and not isinstance(target, bool):
            payload["target"] = f"== {target}"
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
        if self.target is not None:
            try:
                parse_target(self.target)
            except ValueError as exc:
                raise ValueError(f"metric {self.name!r}: {exc}") from None
        if self.gate and self.kind != "binary" and self.target is None:
            raise ValueError(
                f"gate {self.name!r} is a {self.kind} metric, so it needs a target, "
                "such as '>= 0.8'"
            )
        return self

    def passes(self, value: float | None) -> bool | None:
        """Whether one Trial's value passes this metric as a gate.

        Returns:
            ``None`` when the value is ``None``: the gate does not apply.

        Examples:
            >>> MetricSpec(name="ok", kind="binary", gate=True).passes(1.0)
            True
            >>> MetricSpec(name="m", kind="number", gate=True, target=">= 150").passes(90)
            False
        """
        if value is None:
            return None
        return bool(meets(self.target, value)) if self.target else value >= 1

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
    ``number`` or ``running`` metrics, 1.0: a metric's ``gate`` and
    ``target``, not its score, decide whether the Trial passes.

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


class TrialGates(FrozenModel):
    """A Trial's gates: each applicable gate's verdict, and whether it passed.

    A gate whose value is ``None`` or missing does not apply and is left out.
    ``passed`` is ``True`` when every applicable gate passes, ``False`` when one
    fails, and ``None`` when no gate applies: the Trial is not judged.
    """

    gates: dict[str, bool] = Field(default_factory=dict)
    passed: bool | None = None


def judge(specs: Iterable[MetricSpec], values: Mapping[str, float | None]) -> TrialGates:
    """Apply the gates among ``specs`` to one Trial's metric values.

    Returns:
        Each applicable gate's verdict, and whether the Trial passed.

    Examples:
        >>> specs = [
        ...     MetricSpec(name="price_correct", kind="binary", gate=True),
        ...     MetricSpec(name="margin_usd", kind="number", target=">= 150"),
        ... ]
        >>> judge(specs, {"price_correct": 1.0, "margin_usd": 90.0}).passed
        True
        >>> judge(specs, {"price_correct": None}).passed is None
        True
    """
    verdicts: dict[str, bool] = {}
    for spec in specs:
        if not spec.gate:
            continue
        verdict = spec.passes(values.get(spec.name))
        if verdict is not None:
            verdicts[spec.name] = verdict
    return TrialGates(gates=verdicts, passed=all(verdicts.values()) if verdicts else None)


class MetricAggregate(FrozenModel):
    """One metric across a set of Trials, such as one Agent's on a Benchmark.

    ``n`` is how many Trials the metric applied to and ``total`` how many there
    were: a ``None`` value is left out, so read ``mean`` as "over n of total".
    For a ``binary`` metric, ``mean`` is the share of applicable Trials where it
    was 1; with several attempts per Task, ``pass_hat_k`` is the share of Tasks
    where it was 1 on every applicable attempt and ``pass_at_k`` on any.

    Examples:
        >>> spec = MetricSpec(name="ok", kind="binary")
        >>> row = aggregate_metric(spec, {"a": [1.0, 0.0], "b": [1.0, None], "c": [None]})
        >>> (row.n, row.total, row.mean, row.pass_hat_k, row.pass_at_k)
        (3, 5, 0.6666666666666666, 0.5, 1.0)
    """

    name: str
    kind: MetricKind
    direction: Direction = "higher"
    unit: str | None = None
    mean: float | None = None
    n: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
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
        metric its pass^k and pass@k.
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


def store_metric_points(
    path: Path, verifier: str, version: str, points: Sequence[Mapping[str, Any]]
) -> int:
    """Put one Verifier version's running metric points into a ``metrics.jsonl``.

    Points already there from this Verifier at this version are kept as they are,
    as ``plural verifier apply`` keeps rewards: bump the Verifier's version when its
    logic changes. Otherwise this Verifier's earlier points, from the live run or
    an older version, are replaced, so each running metric has one series. Other
    Verifiers' points are untouched.

    Returns:
        How many points were stored; 0 when this version's points were already there.

    Examples:
        >>> import tempfile
        >>> path = Path(tempfile.mkdtemp()) / METRICS_FILE
        >>> store_metric_points(path, "books", "1.1.0", [{"step": 1, "values": {"cash": 3}}])
        1
        >>> store_metric_points(path, "books", "1.1.0", [{"step": 1, "values": {"cash": 4}}])
        0
    """
    lines = (
        [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
        if path.is_file()
        else []
    )
    mine = [line for line in lines if line.get("verifier") == verifier]
    if any(line.get("version") == version for line in mine):
        return 0
    kept = [line for line in lines if line.get("verifier") != verifier]
    added = [{**point, "verifier": verifier, "version": version} for point in points]
    merged = sorted([*kept, *added], key=lambda line: int(line.get("step") or 0))
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        "".join(json.dumps(line, sort_keys=True) + "\n" for line in merged), encoding="utf-8"
    )
    temporary.replace(path)
    return len(added)


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
    "TrialGates",
    "aggregate_metric",
    "aggregate_series",
    "builtin_values",
    "default_score",
    "judge",
    "meets",
    "metric_failures",
    "parse_target",
    "series_by_metric",
    "store_metric_points",
]
