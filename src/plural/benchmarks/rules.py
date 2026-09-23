"""What a Benchmark release declares about scoring and comparison.

A release pins its Tasks and, with them, each Task's Environment and Verifier
revisions. This module holds the rest of what makes two results comparable:
task categories, how scores are combined, and the evaluation tracks that fix
the conditions an Agent is run under.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import Field, field_validator, model_validator

from plural.common import FrozenModel, content_hash, semantic_version

_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TAXONOMY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}(:[a-z0-9][a-z0-9._/-]{0,127})?$")


def _slug(value: str, what: str) -> str:
    if _SLUG.fullmatch(value) is None:
        raise ValueError(
            f"{what} {value!r} must be lowercase letters, digits, '.', '_' or '-', "
            "starting with a letter or digit."
        )
    return value


class BenchmarkCategory(FrozenModel):
    """A named group of Tasks, scored together in results.

    ``id`` is stable across releases. A category is author-defined unless
    ``taxonomy`` names a shared classification, such as ``"plural:coding"``.
    Scores in author-defined categories are only comparable within this
    Benchmark; two Benchmarks that both say "reasoning" may measure different
    things.

    Attributes:
        id: Stable identifier within the Benchmark, such as ``"hard-words"``.
        name: Label shown to readers.
        description: What the Tasks in this category have in common.
        tasks: Names of the Tasks in this category. A Task may be in several.
        taxonomy: Optional shared classification identifier.
    """

    id: str
    name: str = Field(min_length=1)
    description: str = ""
    tasks: tuple[str, ...] = Field(min_length=1)
    taxonomy: str | None = None

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return _slug(value, "Category id")

    @field_validator("taxonomy")
    @classmethod
    def _valid_taxonomy(cls, value: str | None) -> str | None:
        if value is not None and _TAXONOMY_ID.fullmatch(value) is None:
            raise ValueError(f"taxonomy {value!r} must look like 'namespace:identifier'.")
        return value


class BenchmarkScoring(FrozenModel):
    """How a release turns attempts into one score per configuration.

    Repeated attempts of a Task are averaged first. Task scores are then
    combined with ``task_weights``; a Task without a weight counts once. Step
    rewards never contribute: only the Verifier score on each Trial does.

    Attributes:
        metric: Human-readable name of the success metric, such as
            ``"Resolution rate"``. It labels the Verifier score; it never
            selects a different value to rank on.
        description: What a score means, in words a reader can act on.
        aggregation: How Task scores combine. ``"weighted_mean"`` averages
            attempts per Task, then takes the ``task_weights`` mean.
        score_range: Lowest and highest possible Task score.
        success_threshold: A Task attempt at or above this score counts as a
            success. ``None`` means the Benchmark has no pass/fail notion.
        task_weights: Weight per Task name. Unlisted Tasks weigh 1.
        coverage_required: Weighted share of Tasks that must have a score
            before a result can be ranked officially.
        agent_failure: How an attempt that ended without a Verifier score
            because of the Agent (for example, a budget ran out) is scored.
            ``"zero"`` scores it at the bottom of the range.
        infrastructure_error: Attempts lost to the runtime or provider are
            excluded from scores and reported separately.
        min_tasks_for_interval: Fewest scored Tasks before an uncertainty
            interval is reported. Below this, uncertainty is shown as unknown.
    """

    metric: str = "Score"
    description: str = ""
    aggregation: Literal["weighted_mean"] = "weighted_mean"
    score_range: tuple[float, float] = (0.0, 1.0)
    success_threshold: float | None = 1.0
    task_weights: dict[str, float] = Field(default_factory=dict)
    coverage_required: float = Field(default=1.0, gt=0, le=1)
    agent_failure: Literal["zero", "exclude"] = "zero"
    infrastructure_error: Literal["exclude"] = "exclude"
    min_tasks_for_interval: int = Field(default=5, ge=2)

    @model_validator(mode="after")
    def _valid(self) -> BenchmarkScoring:
        low, high = self.score_range
        if high <= low:
            raise ValueError("score_range must be (low, high) with high above low.")
        if self.success_threshold is not None and not low <= self.success_threshold <= high:
            raise ValueError("success_threshold must be inside score_range.")
        for name, weight in self.task_weights.items():
            if weight <= 0:
                raise ValueError(f"task_weights[{name!r}] must be greater than 0.")
        return self

    def weight(self, task: str) -> float:
        """Return the declared weight for one Task name."""
        return float(self.task_weights.get(task, 1.0))


class EvaluationTrack(FrozenModel):
    """Versioned rules that make results on one track comparable.

    A ``models`` track holds the setup fixed so results compare models: one
    harness, no extra instructions, and fixed inference settings. An
    ``agents`` track compares complete systems, so harness, instructions,
    tools, and settings may differ within the declared limits.

    A track version is immutable within a Benchmark. Changing a rule needs a
    new track version, and results on different versions are not ranked
    together.

    Attributes:
        id: Stable track identifier, such as ``"controlled"``.
        version: Semantic version of these rules.
        name: Label shown to readers.
        kind: ``"models"`` or ``"agents"``.
        description: What the track holds constant, in plain words.
        attempts: Attempts per Task every ranked result must have.
        max_retries: Infrastructure retries allowed per attempt.
        harnesses: Allowed harness names. Empty allows any on an ``agents``
            track and means the built-in loop on a ``models`` track.
        instructions: ``"none"`` forbids Agent instructions beyond the Task.
        temperature: Required temperature, when fixed.
        max_tokens: Required output-token limit, when fixed.
        tools: How tools are provided, in words; tools come from the Task
            Environment and the allowed harnesses.
        max_turns: Highest turn limit an Environment in this release may set.
        max_seconds: Highest time limit an Environment may set.
        max_cost_usd: Highest cost limit an Environment may set.
    """

    id: str
    version: str = "1.0.0"
    name: str = Field(min_length=1)
    kind: Literal["models", "agents"]
    description: str = ""
    attempts: int = Field(default=1, ge=1, le=32)
    max_retries: int = Field(default=0, ge=0, le=10)
    harnesses: tuple[str, ...] = ()
    instructions: Literal["none", "any"] = "any"
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    tools: str = "Environment actions only."
    max_turns: int | None = Field(default=None, ge=1)
    max_seconds: float | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return _slug(value, "Track id")

    @field_validator("version")
    @classmethod
    def _valid_version(cls, value: str) -> str:
        return semantic_version(value)

    @model_validator(mode="after")
    def _valid(self) -> EvaluationTrack:
        if self.kind == "models" and len(self.harnesses) > 1:
            raise ValueError(
                f"Track {self.id!r} compares models, so it allows one harness at most."
            )
        if self.kind == "models" and self.instructions != "none":
            raise ValueError(f"Track {self.id!r} compares models, so instructions must be 'none'.")
        return self

    @property
    def rules_hash(self) -> str:
        """Digest of every rule, so identical versions can be proven identical."""
        return content_hash(self.model_dump(mode="json", exclude={"name", "description"}))

    @property
    def reference(self) -> str:
        """``id@version``, the form results and jobs use to name a track."""
        return f"{self.id}@{self.version}"


class TrackConformance(FrozenModel):
    """Configuration facts a track checks, independent of where they are stored.

    Attributes:
        model: Configured primary model.
        fallback_models: Models the configuration may fall back to.
        harness: Harness name, or ``None`` for the built-in loop.
        instructions: Agent instructions added to the Task.
        temperature: Configured temperature.
        max_tokens: Configured output-token limit.
    """

    model: str
    fallback_models: tuple[str, ...] = ()
    harness: str | None = None
    instructions: str = ""
    temperature: float | None = None
    max_tokens: int | None = None


def check_track_conformance(track: EvaluationTrack, facts: TrackConformance) -> list[str]:
    """Return every reason a configuration may not run on a track.

    An empty list means the configuration conforms. Each reason names the rule
    and the value that broke it.

    Returns:
        Human-readable conformance problems.
    """
    issues: list[str] = []
    if track.kind == "models":
        expected = track.harnesses[0] if track.harnesses else None
        if facts.harness != expected:
            issues.append(
                f"Track {track.reference} fixes the harness to "
                f"{expected or 'the built-in loop'}; this configuration uses "
                f"{facts.harness or 'the built-in loop'}."
            )
        if facts.fallback_models:
            issues.append(
                f"Track {track.reference} compares single models; this configuration "
                f"falls back to {', '.join(facts.fallback_models)}."
            )
    elif track.harnesses and (facts.harness or "") not in track.harnesses:
        issues.append(
            f"Track {track.reference} allows harnesses {', '.join(track.harnesses)}; "
            f"this configuration uses {facts.harness or 'the built-in loop'}."
        )
    if track.instructions == "none" and facts.instructions.strip():
        issues.append(f"Track {track.reference} does not allow Agent instructions.")
    if track.temperature is not None and facts.temperature != track.temperature:
        issues.append(
            f"Track {track.reference} requires temperature {track.temperature}; "
            f"this configuration uses {facts.temperature}."
        )
    if track.max_tokens is not None and facts.max_tokens != track.max_tokens:
        issues.append(
            f"Track {track.reference} requires max_tokens {track.max_tokens}; "
            f"this configuration uses {facts.max_tokens}."
        )
    return issues


def check_track_limits(
    track: EvaluationTrack,
    task: str,
    *,
    max_turns: int,
    max_seconds: float,
    max_cost_usd: float | None,
) -> list[str]:
    """Return every Environment limit on one Task that exceeds the track's caps.

    Returns:
        Human-readable limit problems.
    """
    issues: list[str] = []
    if track.max_turns is not None and max_turns > track.max_turns:
        issues.append(
            f"Task {task!r} allows {max_turns} turns; track {track.reference} caps "
            f"turns at {track.max_turns}."
        )
    if track.max_seconds is not None and max_seconds > track.max_seconds:
        issues.append(
            f"Task {task!r} allows {max_seconds:g} seconds; track {track.reference} caps "
            f"time at {track.max_seconds:g} seconds."
        )
    if track.max_cost_usd is not None and (
        max_cost_usd is None or max_cost_usd > track.max_cost_usd
    ):
        allowed = "no cost limit" if max_cost_usd is None else f"${max_cost_usd:g}"
        issues.append(
            f"Task {task!r} allows {allowed}; track {track.reference} caps cost at "
            f"${track.max_cost_usd:g} per attempt."
        )
    return issues


def validate_release_rules(
    task_names: Sequence[str],
    categories: Sequence[BenchmarkCategory],
    scoring: BenchmarkScoring,
    tracks: Sequence[EvaluationTrack],
    default_view: str,
) -> None:
    """Check that categories, weights, and tracks refer to this release's Tasks.

    Raises:
        ValueError: When a rule names a Task or track that does not exist.
    """
    names = set(task_names)
    seen: set[str] = set()
    for category in categories:
        if category.id in seen:
            raise ValueError(f"Category id {category.id!r} is used twice.")
        seen.add(category.id)
        unknown = [task for task in category.tasks if task not in names]
        if unknown:
            raise ValueError(
                f"Category {category.id!r} names Tasks that are not in the Benchmark: "
                f"{', '.join(unknown)}."
            )
    unknown_weights = sorted(set(scoring.task_weights) - names)
    if unknown_weights:
        raise ValueError(
            f"task_weights names Tasks that are not in the Benchmark: {', '.join(unknown_weights)}."
        )
    ids = [track.id for track in tracks]
    if len(ids) != len(set(ids)):
        raise ValueError("Each evaluation track id may appear once per release.")
    if tracks and not any(track.kind == default_view for track in tracks):
        raise ValueError(
            f"default_view is {default_view!r} but no track has kind {default_view!r}."
        )


__all__ = [
    "BenchmarkCategory",
    "BenchmarkScoring",
    "EvaluationTrack",
    "TrackConformance",
    "check_track_conformance",
    "check_track_limits",
    "validate_release_rules",
]
