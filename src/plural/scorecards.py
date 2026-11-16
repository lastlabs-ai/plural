"""Scorecards: a written, versioned definition of what good work is for one workflow.

A :class:`Scorecard` names the metrics that matter and gives each a **role**:
a **gate** must pass, an **objective** is something to maximize or minimize,
and a **guardrail** is reported but never ranked on. It records the plain
words of what good means (``good``), the **decisions** that settled
disagreements, and the settings for checking the graders against people.

A :class:`Label` is one person's judgment of one Trial against the
Scorecard's metrics, with a reason. :func:`calibrate` compares labelers with
each other (does the team agree on what good is?) and the graders with the
team's consensus (do the graders measure it?). Labels check graders; they
never change a score.

Examples:
    >>> card = Scorecard(
    ...     name="steel-quoting",
    ...     metrics=[
    ...         {"name": "price_correct", "role": "gate"},
    ...         {"name": "margin_usd", "role": "objective", "target": ">= 150"},
    ...     ],
    ...     primary="margin_usd",
    ... )
    >>> card.reference
    'steel-quoting@1.0.0'
    >>> card.evaluate({"price_correct": 1.0, "margin_usd": 90.0}).passed
    True
    >>> card.evaluate({"price_correct": None, "margin_usd": None}).gates
    {}
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from plural.common import FrozenModel
from plural.identity import revision_hash
from plural.metrics import BUILTIN_METRICS, MetricSpec

Role = Literal["gate", "objective", "guardrail"]
Verdict = Literal["good", "bad", "unsure"]
Status = Literal["trusted", "needs_work", "undefined", "not_calibrated"]

LABELS_DIR = Path(".plural") / "labels"
"""Where labels live in a project with no hosted project, one JSONL file per Scorecard."""
UNDEFINED_BELOW = 0.4
"""Team agreement under this means the metric needs a better definition, not a better grader."""

_TARGET = re.compile(
    r"^\s*(?:(?P<op>>=|<=|==)\s*(?P<value>-?\d+(?:\.\d+)?)"
    r"|between\s+(?P<low>-?\d+(?:\.\d+)?)\s+(?:and\s+)?(?P<high>-?\d+(?:\.\d+)?))\s*$"
)
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


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


class ScorecardMetric(FrozenModel):
    """One metric on a Scorecard, by name, with the role it plays.

    Its kind, unit, and direction come from the Verifier that declares it, or
    from the built-in of that name. ``applies_to`` limits it to some Tasks or
    Benchmark categories, when it is not produced on every Task.
    """

    name: str = Field(min_length=1, max_length=64)
    role: Role
    target: str | None = None
    weight: float = Field(default=1.0, gt=0)
    applies_to: tuple[str, ...] = ()
    description: str = ""

    @field_validator("target", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Any:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"== {value}"
        return value

    @model_validator(mode="after")
    def _valid(self) -> ScorecardMetric:
        if self.target is not None:
            parse_target(self.target)
        return self


class Decision(FrozenModel):
    """A question the team settled, and how.

    ``metric`` names the metric it changed, if any; ``trial_id`` the example
    that raised it.
    """

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    decided_by: str = ""
    date: str = Field(default_factory=lambda: date.today().isoformat())
    metric: str | None = None
    trial_id: str | None = None

    @field_validator("date", mode="before")
    @classmethod
    def _iso(cls, value: Any) -> Any:
        return value.isoformat() if isinstance(value, (date, datetime)) else value


class CalibrationSettings(FrozenModel):
    """When a metric's grader counts as trusted.

    ``min_labels`` is the examples a metric needs labeled; ``min_agreement``
    the agreement its grader needs with the team: Cohen's kappa for binary
    and rating metrics, Spearman's rho for numbers.
    """

    min_labels: int = Field(default=20, ge=1)
    min_agreement: float = Field(default=0.6, ge=-1, le=1)


class TrialGates(FrozenModel):
    """A Trial's gates under a Scorecard.

    ``gates`` holds each applicable gate's verdict; a gate whose metric is
    ``None`` does not apply and is left out. ``passed`` is true when every
    applicable gate passes.
    """

    gates: dict[str, bool] = Field(default_factory=dict)
    passed: bool


class Scorecard(FrozenModel):
    """What good work is for one workflow, in words and in metrics.

    Examples:
        >>> Scorecard(name="x", metrics=[{"name": "ok", "role": "gate"}]).version
        '1.0.0'
    """

    name: str = Field(min_length=1, max_length=64)
    version: str = "1.0.0"
    workflow: str = ""
    owner: str = ""
    good: str = ""
    metrics: tuple[ScorecardMetric, ...] = Field(min_length=1)
    primary: str | None = None
    inspector_lens: tuple[str, ...] = ()
    decisions: tuple[Decision, ...] = ()
    calibration: CalibrationSettings = Field(default_factory=CalibrationSettings)

    @model_validator(mode="after")
    def _valid(self) -> Scorecard:
        if not _SEMVER.match(self.version):
            raise ValueError(f"Scorecard version {self.version!r} must be MAJOR.MINOR.PATCH")
        names = [item.name for item in self.metrics]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(f"Scorecard lists metric {', '.join(repeated)} more than once")
        if self.primary is not None:
            role = self.metric(self.primary)
            if role is None:
                raise ValueError(f"primary {self.primary!r} is not one of the Scorecard's metrics")
            if role.role != "objective":
                raise ValueError(
                    f"primary {self.primary!r} is a {role.role}; the primary must be an objective"
                )
        return self

    @property
    def reference(self) -> str:
        """``name@version``, as a Benchmark names it."""
        return f"{self.name}@{self.version}"

    @property
    def content_hash(self) -> str:
        """Stable Scorecard revision digest. Labels and open questions are not part of it."""
        return revision_hash("scorecard", self.model_dump(mode="json"))

    @property
    def gates(self) -> tuple[ScorecardMetric, ...]:
        """The metrics that must pass."""
        return tuple(item for item in self.metrics if item.role == "gate")

    @property
    def objectives(self) -> tuple[ScorecardMetric, ...]:
        """The metrics to maximize or minimize."""
        return tuple(item for item in self.metrics if item.role == "objective")

    def metric(self, name: str) -> ScorecardMetric | None:
        """One of the Scorecard's metrics, by name.

        Returns:
            The metric, or ``None``.
        """
        return next((item for item in self.metrics if item.name == name), None)

    def problems(
        self,
        specs: Mapping[str, MetricSpec],
        produced: Mapping[str, Iterable[str]] | None = None,
        categories: Mapping[str, Iterable[str]] | None = None,
    ) -> list[str]:
        """What is wrong with this Scorecard against the metrics a project produces.

        Args:
            specs: Every metric the Verifiers declare, by name. Built-ins are added.
            produced: For a Benchmark, each Task's metric names, to check every
                metric is produced on every Task it applies to.
            categories: For a Benchmark, each category id's Task names, for
                ``applies_to``.

        Returns:
            One line per problem; empty when it is valid.
        """
        known = {**BUILTIN_METRICS, **specs}
        found: list[str] = []
        for item in self.metrics:
            spec = known.get(item.name)
            if spec is None:
                found.append(
                    f"metric {item.name!r} is not a built-in and no Verifier declares it. "
                    "Declare it in a Verifier's metrics list."
                )
                continue
            if item.role == "gate" and spec.kind != "binary" and item.target is None:
                found.append(
                    f"gate {item.name!r} is a {spec.kind} metric, so it needs a target, "
                    "such as '>= 0.8'"
                )
            if produced is None:
                continue
            groups = {key: set(value) for key, value in (categories or {}).items()}
            scope: set[str] = set()
            for entry in item.applies_to:
                scope |= groups.get(entry, {entry})
            missing = sorted(
                task
                for task, names in produced.items()
                if (not item.applies_to or task in scope)
                and item.name not in set(names)
                and item.name not in BUILTIN_METRICS
            )
            if missing:
                found.append(
                    f"metric {item.name!r} is not produced on Task {', '.join(missing)}. "
                    "Add its Verifier to those Tasks, or limit it with applies_to."
                )
        return found

    def applies(
        self, item: ScorecardMetric, task: str | None, categories: Iterable[str] = ()
    ) -> bool:
        """Whether a metric applies on one Task, by its ``applies_to``.

        Returns:
            True when it has no ``applies_to`` or names the Task or one of its categories.
        """
        if not item.applies_to:
            return True
        return task in item.applies_to or any(entry in item.applies_to for entry in categories)

    def evaluate(
        self,
        values: Mapping[str, float | None],
        *,
        task: str | None = None,
        categories: Iterable[str] = (),
    ) -> TrialGates:
        """Apply the gates to one Trial's metrics.

        A binary gate passes at 1 (or its target, if it has one); a number gate
        passes when it meets its target. A gate whose value is ``None`` or
        missing does not apply. A Trial passes when every applicable gate does.

        Returns:
            Each applicable gate's verdict, and whether the Trial passed.
        """
        verdicts: dict[str, bool] = {}
        categories = tuple(categories)
        for item in self.gates:
            if not self.applies(item, task, categories):
                continue
            value = values.get(item.name)
            if value is None:
                continue
            verdict = meets(item.target, value) if item.target else value >= 1
            verdicts[item.name] = bool(verdict)
        return TrialGates(gates=verdicts, passed=all(verdicts.values()))

    def bumped(self, part: Literal["major", "minor", "patch"] = "patch") -> Scorecard:
        """This Scorecard with its version bumped.

        Returns:
            A copy with the new version.

        Examples:
            >>> Scorecard(name="x", metrics=[{"name": "ok", "role": "gate"}]).bumped().version
            '1.0.1'
        """
        match = _SEMVER.match(self.version)
        assert match is not None
        major, minor, patch = (int(item) for item in match.groups())
        version = {
            "major": f"{major + 1}.0.0",
            "minor": f"{major}.{minor + 1}.0",
            "patch": f"{major}.{minor}.{patch + 1}",
        }[part]
        return self.model_copy(update={"version": version})


def parse_reference(reference: str) -> tuple[str, str | None]:
    """Split ``name@version`` into its parts.

    Returns:
        The name, and the version or ``None``.

    Examples:
        >>> parse_reference("steel-quoting@1.0.2"), parse_reference("steel-quoting")
        (('steel-quoting', '1.0.2'), ('steel-quoting', None))
    """
    name, _, version = reference.partition("@")
    return name, version or None


def resolve_primary(scorecard: Scorecard | None, primary_metric: str) -> str:
    """What a Benchmark ranks on: its own ``primary_metric``, or its Scorecard's primary.

    Returns:
        The metric name.

    Examples:
        >>> card = Scorecard(name="x", metrics=[{"name": "m", "role": "objective"}], primary="m")
        >>> resolve_primary(card, "score"), resolve_primary(None, "score")
        ('m', 'score')
    """
    if scorecard is not None and primary_metric == "score" and scorecard.primary:
        return scorecard.primary
    return primary_metric


# Labels.


class Label(FrozenModel):
    """One person's judgment of one Trial against a Scorecard's metrics.

    ``values`` gives each metric the labeler judged; ``None`` means unsure,
    or that it does not apply. ``reasons`` holds a reason per metric, and
    ``reason`` one for the overall verdict.

    Examples:
        >>> Label(
        ...     scorecard="steel-quoting",
        ...     trial_id="trl_1",
        ...     labeler="kb",
        ...     values={"price_correct": 1, "delivery_feasible": 0},
        ...     verdict="bad",
        ... ).values["delivery_feasible"]
        0.0
    """

    scorecard: str = Field(min_length=1)
    trial_id: str = Field(min_length=1)
    labeler: str = Field(min_length=1)
    values: dict[str, float | None] = Field(default_factory=dict)
    verdict: Verdict = "unsure"
    reason: str = ""
    reasons: dict[str, str] = Field(default_factory=dict)
    task: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("values", mode="before")
    @classmethod
    def _numbers(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, bool):
                item = float(item)
            elif isinstance(item, str):
                item = {"y": 1.0, "yes": 1.0, "n": 0.0, "no": 0.0, "?": None}.get(
                    item.strip().lower(), item
                )
            converted[key] = item
        return converted


def labels_path(root: Path, scorecard: str) -> Path:
    """The local label file for one Scorecard in a project.

    Returns:
        ``.plural/labels/<scorecard>.jsonl`` under ``root``.
    """
    return root / LABELS_DIR / f"{scorecard}.jsonl"


def read_labels(path: Path) -> list[Label]:
    """Read a label file; a later label from the same labeler on the same Trial wins.

    Returns:
        The labels, in the order first written.
    """
    if not path.is_file():
        return []
    latest: dict[tuple[str, str], Label] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        label = Label.model_validate_json(line)
        latest[(label.trial_id, label.labeler)] = label
    return list(latest.values())


def write_labels(path: Path, labels: Iterable[Label]) -> int:
    """Append labels to a label file.

    Returns:
        How many were written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for label in labels:
            handle.write(label.model_dump_json() + "\n")
            count += 1
    return count


def label_digest(labels: Iterable[Label]) -> str:
    """A digest of a label set, so a calibration can cite exactly which labels it used.

    Returns:
        ``sha256:`` and the hex digest, independent of order.
    """
    lines = sorted(
        json.dumps(
            {
                "trial_id": item.trial_id,
                "labeler": item.labeler,
                "values": item.values,
                "verdict": item.verdict,
            },
            sort_keys=True,
        )
        for item in labels
    )
    return "sha256:" + hashlib.sha256("\n".join(lines).encode()).hexdigest()


# Agreement statistics.


def cohen_kappa(first: Sequence[Any], second: Sequence[Any]) -> float | None:
    """Cohen's kappa for two raters over the same items.

    When both raters use one category throughout, chance agreement is total
    and kappa is undefined; this returns 1.0 if they agree on every item and
    0.0 otherwise.

    Returns:
        Kappa, or ``None`` with no items.

    Examples:
        >>> cohen_kappa([1, 1, 0, 0], [1, 1, 0, 1])
        0.5
    """
    if len(first) != len(second):
        raise ValueError("both raters must rate the same items")
    if not first:
        return None
    total = len(first)
    observed: float = sum(a == b for a, b in zip(first, second, strict=True)) / total
    left, right = Counter(first), Counter(second)
    expected: float = sum(left[key] * right[key] for key in left) / (total * total)
    if math.isclose(expected, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else 0.0
    return (observed - expected) / (1 - expected)


def fleiss_kappa(ratings: Sequence[Sequence[Any]]) -> float | None:
    """Fleiss' kappa for any number of raters; each item lists its raters' categories.

    Items rated by fewer than two raters are left out.

    Returns:
        Kappa, or ``None`` with no usable items.

    Examples:
        >>> round(fleiss_kappa([[1, 1, 1], [0, 0, 0], [1, 0, 1], [0, 0, 0]]), 3)
        0.657
    """
    items = [list(item) for item in ratings if len(item) >= 2]
    if not items:
        return None
    categories = sorted({value for item in items for value in item}, key=str)
    agreement: list[float] = []
    shares: Counter[Any] = Counter()
    assignments = 0
    for item in items:
        count = len(item)
        tally = Counter(item)
        shares.update(tally)
        assignments += count
        agreement.append((sum(n * n for n in tally.values()) - count) / (count * (count - 1)))
    observed = sum(agreement) / len(agreement)
    expected = sum((shares[key] / assignments) ** 2 for key in categories)
    if math.isclose(expected, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else 0.0
    return (observed - expected) / (1 - expected)


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def spearman(first: Sequence[float], second: Sequence[float]) -> float | None:
    """Spearman's rank correlation, with ties given their average rank.

    Returns:
        Rho, or ``None`` with fewer than two items or a constant series.

    Examples:
        >>> spearman([1, 2, 3, 4], [10, 20, 30, 40])
        1.0
    """
    if len(first) != len(second):
        raise ValueError("both series must cover the same items")
    if len(first) < 2:
        return None
    left, right = _ranks(first), _ranks(second)
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    covariance = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right, strict=True))
    spread = math.sqrt(
        sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right)
    )
    if spread == 0:
        return None
    return covariance / spread


# Calibration.


class MetricCalibration(FrozenModel):
    """How one metric's graders and labelers agree.

    ``labeled`` counts examples at least one labeler judged; ``consensus``
    those with a clear majority, which the grader is compared against.
    """

    metric: str
    kind: str
    labeled: int = 0
    consensus: int = 0
    labelers: int = 0
    team_agreement: float | None = None
    team_measure: Literal["cohen_kappa", "fleiss_kappa", "spearman"] | None = None
    grader_agreement: float | None = None
    grader_measure: Literal["cohen_kappa", "spearman"] | None = None
    grader_accuracy: float | None = None
    mean_absolute_error: float | None = None
    status: Status = "not_calibrated"
    note: str = ""


class Disagreement(FrozenModel):
    """One example that needs a decision.

    ``kind`` is ``labelers_split`` when the labelers disagree with no clear
    majority, or ``grader_disagrees`` when the grader contradicts a clear
    consensus.
    """

    trial_id: str
    metric: str
    kind: Literal["labelers_split", "grader_disagrees"]
    labels: dict[str, float | None] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    grader: float | None = None
    task: str | None = None


class Calibration(FrozenModel):
    """Graders against the team, for one Scorecard version and one label set."""

    scorecard: str
    label_digest: str
    labels: int
    labelers: tuple[str, ...] = ()
    metrics: tuple[MetricCalibration, ...] = ()
    needs_decision: tuple[Disagreement, ...] = ()
    computed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def metric(self, name: str) -> MetricCalibration | None:
        """One metric's calibration, by name.

        Returns:
            The calibration, or ``None``.
        """
        return next((item for item in self.metrics if item.metric == name), None)


def _category(value: float | None, kind: str) -> Any:
    if value is None:
        return None
    if kind == "binary":
        return int(value >= 0.5)
    if kind == "rating":
        return round(value)
    return value


def _consensus(values: Sequence[float], kind: str) -> float | None:
    """The labelers' consensus: the majority category, or the median of numbers.

    Returns:
        The consensus, or ``None`` when the top categories tie.
    """
    if not values:
        return None
    if kind in {"binary", "rating"}:
        tally = Counter(_category(value, kind) for value in values).most_common()
        if len(tally) > 1 and tally[0][1] == tally[1][1]:
            return None
        return float(tally[0][0])
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def calibrate(
    scorecard: Scorecard,
    labels: Iterable[Label],
    graders: Mapping[str, Mapping[str, float | None]],
    specs: Mapping[str, MetricSpec] | None = None,
) -> Calibration:
    """Check the graders against the team's labels, metric by metric.

    * **Team agreement**: Cohen's kappa for two labelers, Fleiss' kappa for
      more, on binary and rating metrics; Spearman's rho on numbers (the mean
      over each pair of labelers).
    * **Grader agreement**: the grader's value against the labelers'
      consensus, the majority (a tie is unsure and left out) or for a number
      the median: kappa and accuracy, or rho and mean absolute error.
    * **Status**: ``undefined`` when the team agrees under 0.4, so the metric
      needs a better definition; ``not_calibrated`` with too few labeled
      examples or no grader values; ``trusted`` when the grader agrees at
      least ``min_agreement``; otherwise ``needs_work``.

    Args:
        scorecard: The Scorecard whose metrics to calibrate.
        labels: The labels, from any number of labelers.
        graders: Each labeled Trial's metric values, as its graders produced them.
        specs: Each metric's spec, for its kind; built-ins are added.

    Returns:
        Each metric's calibration and the examples that need a decision.
    """
    labels = list(labels)
    known = {**BUILTIN_METRICS, **(specs or {})}
    labelers = tuple(sorted({item.labeler for item in labels}))
    by_trial: dict[str, dict[str, Label]] = {}
    for item in labels:
        by_trial.setdefault(item.trial_id, {})[item.labeler] = item
    rows: list[MetricCalibration] = []
    decisions: list[Disagreement] = []
    settings = scorecard.calibration
    for entry in scorecard.metrics:
        spec = known.get(entry.name)
        kind = spec.kind if spec is not None else "number"
        if kind == "running":
            kind = "number"
        labeled = 0
        consensus: dict[str, float] = {}
        matrix: dict[str, dict[str, float]] = {}
        for trial_id, judged in by_trial.items():
            given = {
                name: value
                for name, label in judged.items()
                if (value := label.values.get(entry.name)) is not None
            }
            if not given:
                continue
            labeled += 1
            matrix[trial_id] = given
            agreed = _consensus(list(given.values()), kind)
            grader = graders.get(trial_id, {}).get(entry.name)
            task = next((label.task for label in judged.values() if label.task), None)
            reasons = {
                name: label.reasons.get(entry.name) or label.reason
                for name, label in judged.items()
                if label.reasons.get(entry.name) or label.reason
            }
            if agreed is None:
                decisions.append(
                    Disagreement(
                        trial_id=trial_id,
                        metric=entry.name,
                        kind="labelers_split",
                        labels=dict(given),
                        reasons=reasons,
                        grader=grader,
                        task=task,
                    )
                )
                continue
            consensus[trial_id] = agreed
            if (
                grader is not None
                and kind in {"binary", "rating"}
                and _category(grader, kind) != _category(agreed, kind)
            ):
                decisions.append(
                    Disagreement(
                        trial_id=trial_id,
                        metric=entry.name,
                        kind="grader_disagrees",
                        labels=dict(given),
                        reasons=reasons,
                        grader=grader,
                        task=task,
                    )
                )
        row: dict[str, Any] = {
            "metric": entry.name,
            "kind": kind,
            "labeled": labeled,
            "consensus": len(consensus),
            "labelers": len({name for given in matrix.values() for name in given}),
        }
        row.update(_team(matrix, kind))
        row.update(_grader(consensus, graders, entry.name, kind))
        row["status"], row["note"] = _status(row, settings)
        rows.append(MetricCalibration(**row))
    return Calibration(
        scorecard=scorecard.reference,
        label_digest=label_digest(labels),
        labels=len(by_trial),
        labelers=labelers,
        metrics=tuple(rows),
        needs_decision=tuple(decisions),
    )


def _team(matrix: Mapping[str, Mapping[str, float]], kind: str) -> dict[str, Any]:
    names = sorted({name for given in matrix.values() for name in given})
    if len(names) < 2:
        return {}
    if kind in {"binary", "rating"}:
        if len(names) == 2:
            first, second = names
            shared = [given for given in matrix.values() if first in given and second in given]
            value = cohen_kappa(
                [_category(item[first], kind) for item in shared],
                [_category(item[second], kind) for item in shared],
            )
            return {"team_agreement": value, "team_measure": "cohen_kappa"}
        value = fleiss_kappa(
            [[_category(value, kind) for value in given.values()] for given in matrix.values()]
        )
        return {"team_agreement": value, "team_measure": "fleiss_kappa"}
    pairs = []
    for first, second in combinations(names, 2):
        shared = [given for given in matrix.values() if first in given and second in given]
        rho = spearman([item[first] for item in shared], [item[second] for item in shared])
        if rho is not None:
            pairs.append(rho)
    return {
        "team_agreement": sum(pairs) / len(pairs) if pairs else None,
        "team_measure": "spearman",
    }


def _grader(
    consensus: Mapping[str, float],
    graders: Mapping[str, Mapping[str, float | None]],
    metric: str,
    kind: str,
) -> dict[str, Any]:
    pairs = [
        (agreed, grader)
        for trial_id, agreed in consensus.items()
        if (grader := graders.get(trial_id, {}).get(metric)) is not None
    ]
    if not pairs:
        return {}
    if kind in {"binary", "rating"}:
        team = [_category(agreed, kind) for agreed, _ in pairs]
        graded = [_category(grader, kind) for _, grader in pairs]
        return {
            "grader_agreement": cohen_kappa(team, graded),
            "grader_measure": "cohen_kappa",
            "grader_accuracy": sum(a == b for a, b in zip(team, graded, strict=True)) / len(pairs),
        }
    agreed_values, grader_values = [a for a, _ in pairs], [b for _, b in pairs]
    rho = spearman(agreed_values, grader_values)
    if rho is None and len(set(grader_values)) == 1 and len(set(agreed_values)) > 1:
        # A grader that gives every example the same value tracks nothing the team sees.
        rho = 0.0
    return {
        "grader_agreement": rho,
        "grader_measure": "spearman",
        "mean_absolute_error": sum(abs(a - b) for a, b in pairs) / len(pairs),
    }


def _status(row: Mapping[str, Any], settings: CalibrationSettings) -> tuple[Status, str]:
    team = row.get("team_agreement")
    grader = row.get("grader_agreement")
    if team is not None and team < UNDEFINED_BELOW:
        return "undefined", "The team disagrees on it: define it better, then label again."
    if row["labeled"] < settings.min_labels:
        return (
            "not_calibrated",
            f"{row['labeled']} of {settings.min_labels} examples labeled.",
        )
    if grader is None:
        return "not_calibrated", "No grader values on the labeled examples to compare."
    if grader >= settings.min_agreement:
        return "trusted", ""
    return (
        "needs_work",
        f"The grader agrees {grader:.2f} with the team, under {settings.min_agreement:g}.",
    )


def rescore(
    scorecard: Scorecard,
    trials: Iterable[Mapping[str, Any]],
    *,
    categories: Mapping[str, Iterable[str]] | None = None,
) -> list[dict[str, Any]]:
    """Apply a Scorecard's gates and targets to stored Trials' metrics, without running them.

    Each Trial is a mapping with ``trial_id``, ``task``, ``status``, and
    ``metrics``. A Trial that failed before its checks never passes.

    Args:
        scorecard: The Scorecard version to apply.
        trials: The stored Trials.
        categories: Each Task's Benchmark categories, for ``applies_to``.

    Returns:
        One row per Trial: its gates, whether it passed, and each targeted
        metric's verdict under ``targets``.
    """
    rows: list[dict[str, Any]] = []
    for trial in trials:
        task = trial.get("task")
        groups = tuple((categories or {}).get(str(task), ())) if task else ()
        values = dict(trial.get("metrics") or {})
        result = scorecard.evaluate(values, task=task, categories=groups)
        targets = {
            item.name: meets(item.target, values.get(item.name))
            for item in scorecard.metrics
            if item.target and item.role != "gate" and scorecard.applies(item, task, groups)
        }
        failed = trial.get("status") not in {"succeeded", None}
        rows.append(
            {
                "trial_id": trial.get("trial_id"),
                "task": task,
                "gates": result.gates,
                "passed": False if failed else result.passed,
                "targets": targets,
            }
        )
    return rows


def task_categories(categories: Iterable[Any]) -> dict[str, tuple[str, ...]]:
    """Each Task's Benchmark category ids, from a Benchmark's categories.

    Returns:
        Task name to the ids of every category that lists it.

    Examples:
        >>> from types import SimpleNamespace as Group
        >>> task_categories([Group(id="rush", tasks=("q-1",)), Group(id="cwt", tasks=("q-1",))])
        {'q-1': ('rush', 'cwt')}
    """
    found: dict[str, tuple[str, ...]] = {}
    for group in categories:
        for task in group.tasks:
            found[task] = (*found.get(task, ()), group.id)
    return found


def pass_rate(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """The share of rescored Trials that passed.

    Returns:
        The rate, or ``None`` with no Trials.
    """
    return sum(bool(row["passed"]) for row in rows) / len(rows) if rows else None


__all__ = [
    "LABELS_DIR",
    "Calibration",
    "CalibrationSettings",
    "Decision",
    "Disagreement",
    "Label",
    "MetricCalibration",
    "Role",
    "Scorecard",
    "ScorecardMetric",
    "Status",
    "TrialGates",
    "Verdict",
    "calibrate",
    "cohen_kappa",
    "fleiss_kappa",
    "label_digest",
    "labels_path",
    "meets",
    "parse_reference",
    "parse_target",
    "pass_rate",
    "read_labels",
    "rescore",
    "resolve_primary",
    "spearman",
    "task_categories",
    "write_labels",
]
