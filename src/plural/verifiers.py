"""First-class Verifier definitions."""

from __future__ import annotations

import hashlib
import inspect
import math
import shlex
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    AliasChoices,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationInfo,
    field_serializer,
    model_validator,
)

from plural._deprecation import renamed_attribute, renamed_keys
from plural.apps.definition import SecretReference
from plural.catalog import ModelCatalog
from plural.common import FrozenModel, RoutingSpec, described
from plural.identity import revision_hash
from plural.metrics import MetricSpec, default_score
from plural.rewards import HindsightVerifier
from plural.sandbox.models import (
    RUNTIME_RENAMES,
    NetworkMode,
    ResourceRequirements,
    runtime_hash_payload,
)


class VerifierRuntime(FrozenModel):
    """Machine for a verifier that needs its own sandbox.

    The default runs in the Task Environment. Set a provider, image, network,
    resource limit, or timeout to use a different machine.
    """

    provider: str = Field(default="docker", min_length=1)
    image: str | None = None
    network: NetworkMode = NetworkMode.PUBLIC
    allowed_hosts: tuple[str, ...] = Field(
        default=(), validation_alias=AliasChoices("allowed_hosts", "network_allowlist")
    )
    compute: ResourceRequirements = Field(
        default_factory=ResourceRequirements,
        validation_alias=AliasChoices("compute", "resources"),
    )
    timeout_seconds: float = Field(default=60, gt=0)

    network_allowlist = renamed_attribute("network_allowlist", "allowed_hosts")
    resources = renamed_attribute("resources", "compute")

    @model_validator(mode="before")
    @classmethod
    def _renamed_fields(cls, value: Any) -> Any:
        return renamed_keys(value, RUNTIME_RENAMES, "VerifierRuntime")

    @model_validator(mode="after")
    def _network(self) -> VerifierRuntime:
        if self.allowed_hosts and self.network is not NetworkMode.ALLOWLIST:
            raise ValueError(
                "Cannot create VerifierRuntime.\n"
                f"allowed_hosts is set but network={self.network.value!r}.\n"
                "Set network='allowlist' or remove allowed_hosts."
            )
        return self


def _legacy_runtime_keys(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = payload.get("runtime")
    if isinstance(runtime, dict):
        payload["runtime"] = runtime_hash_payload(runtime)
    return payload


def runtime_is_custom(runtime: VerifierRuntime) -> bool:
    """Return whether this runtime names its own machine.

    Docker, public network, and a 60 second timeout, with no image or resource
    limits, is the default and runs in the Task Environment.

    Returns:
        True when any runtime field differs from that default.
    """
    return bool(
        runtime.image
        or runtime.network is not NetworkMode.PUBLIC
        or runtime.allowed_hosts
        or runtime.compute.configured
        or runtime.provider != "docker"
        or runtime.timeout_seconds != 60
    )


class EpisodeUsage(FrozenModel):
    """Token, turn, and cost totals captured for one completed episode."""

    turns: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


StopReason = Literal[
    # The Environment ended the episode.
    "environment_terminated",
    "environment_truncated",
    # The Agent ended the episode.
    "agent_finished",
    "agent_response",
    # A Harness budget cut the episode short.
    "max_turns",
    "max_seconds",
    "max_cost",
    # The episode did not finish.
    "error",
    # The Harness ran past its time and was killed.
    "harness_timeout",
]
STOP_REASONS: tuple[str, ...] = get_args(StopReason)


class EpisodeOutcome(FrozenModel):
    """How one episode ended.

    ``stop_reason`` is one of :data:`STOP_REASONS`. ``terminated`` means the
    Environment declared the episode over; ``truncated`` means it was cut short
    by the Environment or by a Harness budget. Neither is set when the Agent
    chose to stop, so read ``stop_reason`` to tell those cases apart.
    """

    stop_reason: Literal["", StopReason] = ""
    terminated: bool = False
    truncated: bool = False
    turns: int = 0
    total_reward: float = 0

    @property
    def completed(self) -> bool:
        """Whether the Environment itself ended the episode."""
        return self.terminated


class AppSnapshot(FrozenModel):
    """One App at the start and end of an episode, as a Verifier sees it.

    ``initial`` and ``check`` are the App's snapshots, or ``None`` when it has
    no ``snapshot()``. ``control`` says how far they can be trusted: an
    ``owned`` or ``sandboxed`` App started from the Task's state; a ``live``
    App is shared and may have changed for other reasons.
    """

    control: Literal["owned", "sandboxed", "live", "replayed"] = "owned"
    initial: Any = None
    final: Any = None

    _query: Callable[[str, dict[str, Any]], Any] | None = PrivateAttr(default=None)

    def query(self, action: str, /, **arguments: Any) -> Any:
        """Call one of this App's read-only actions, such as ``get_record``.

        Available to function Verifiers while the Trial's Runtime is still
        running. An action that can change state is refused.

        Returns:
            The action's observation.

        Raises:
            RuntimeError: When the episode's Apps are no longer running.
        """
        if self._query is None:
            raise RuntimeError(
                "App queries are only available to function Verifiers during a Trial. "
                "Read the App's final snapshot instead."
            )
        return self._query(action, arguments)


class Episode(FrozenModel):
    """Completed Agent episode handed to a Verifier.

    ``apps`` holds each App's initial and final snapshots and, for function
    Verifiers, read-only ``query`` access. ``state`` is a shortcut: the one
    App's final snapshot when the Environment has one App, otherwise a mapping
    of App name to final snapshot. Neither is ever shown to the Agent.
    ``observation`` is what the Agent last saw, and ``answer`` is the final
    answer it gave, which is all there is to check in an Environment with no
    Apps. ``expected`` is the Task's answer key, which the Agent never sees.
    ``rewards`` are the values this Verifier's ``reward`` gave each step, in
    order; :func:`total_reward` sums them. ``metric_series`` holds each running
    metric's points, and ``answer`` may be ``None``: an episode that runs a
    business for a simulated year has no final answer to check.

    When several Agents share the episode, ``seats`` names them, each step in
    ``trajectory`` carries the ``seat`` that took it, and ``seat_rewards`` holds
    this Verifier's rewards for each seat. Return each seat's score in
    :attr:`VerifierOutput.seats`.
    """

    observation: dict[str, Any] = Field(default_factory=dict)
    answer: Any = None
    expected: Any = None
    state: dict[str, Any] = Field(default_factory=dict)
    apps: dict[str, AppSnapshot] = Field(default_factory=dict)
    trajectory: list[Any] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    usage: EpisodeUsage = Field(default_factory=EpisodeUsage)
    outcome: EpisodeOutcome = Field(default_factory=EpisodeOutcome)
    rewards: tuple[float, ...] = ()
    seats: tuple[str, ...] = ()
    seat_rewards: dict[str, tuple[float, ...]] = Field(default_factory=dict)
    metric_series: dict[str, tuple[tuple[int, float], ...]] = Field(default_factory=dict)
    """Each running metric's points so far, ``(step, value)``, from every
    Verifier's ``measure`` hook, so ``check`` can use them."""

    @classmethod
    def from_apps(cls, report: Mapping[str, Any], **fields: Any) -> Episode:
        """Build an Episode from the App host's ``finish`` report.

        Returns:
            The Episode, with ``state`` derived from the App snapshots.
        """
        apps = {
            str(name): AppSnapshot.model_validate(entry)
            for name, entry in report.items()
            if isinstance(entry, Mapping)
        }
        if len(apps) == 1:
            final = next(iter(apps.values())).final
            state = dict(final) if isinstance(final, Mapping) else {}
        else:
            state = {name: entry.final for name, entry in apps.items()}
        return cls(apps=apps, state=state, **fields)


@dataclass(frozen=True)
class StepTask:
    """The Task an episode is working on, as a ``reward`` hook sees it.

    ``expected`` is the Task's answer key, which the Agent never sees.
    """

    name: str = ""
    info: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    expected: Any = None


@dataclass(frozen=True)
class Step:
    """One action the Agent took, as a Verifier's ``reward`` hook sees it.

    ``observation`` is what the Agent saw back; ``error`` is set instead when
    the action rejected its input. ``previous_state`` and ``current_state``
    are the acting App's snapshots around the action, or ``None`` when it does
    not snapshot on each step. ``apps`` reads any App, by name: ``state`` for
    a Python App, ``snapshot()``, and ``query(action, **arguments)`` for a
    read-only action. Nothing here reaches the Agent.

    When several Agents share the episode, ``seat`` is the one that acted and
    ``seats`` lists them all. A number a ``reward`` hook returns credits the
    acting seat; a mapping of seat to number credits each seat named, as in a
    zero-sum game.
    """

    task: StepTask
    turn: int
    app: str
    action: str
    arguments: Mapping[str, Any]
    observation: Any = None
    error: str | None = None
    previous_state: Any = None
    current_state: Any = None
    apps: Mapping[str, Any] = field(default_factory=dict)
    seat: str | None = None
    seats: tuple[str, ...] = ()
    source: Literal["agent", "environment"] = "agent"
    """What changed the State: the Agent's action, or the Environment itself."""


class VerifierOutput(FrozenModel):
    """What a Verifier's ``check`` hook returns for the finished episode.

    ``score`` is the headline number for the Task; ``scores`` holds any named
    sub-metrics behind it. Step rewards are separate: a ``reward`` hook returns a
    number per action, which goes to the reward ledger. It reaches a score only
    when ``check`` is :func:`total_reward`.

    For a Task with seats, ``seats`` gives each seat's score, and ``score`` the
    episode's, such as their mean. Each Agent is ranked by its seats' scores.

    ``metrics`` gives the value of each metric the Verifier declares, or
    ``None`` for one that does not apply to this episode, such as a price check
    on a correct handoff. A Verifier that declares metrics may leave ``score``
    out: it is the mean of its applicable ``binary`` and ``score`` metrics, or
    1.0 when it has none (see :func:`plural.metrics.default_score`).
    """

    score: float | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    feedback: str = ""
    seats: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _scored(self) -> VerifierOutput:
        if self.score is None and not self.metrics:
            raise ValueError(
                "a Verifier result needs a score, or metrics when the Verifier declares them"
            )
        return self

    def validated_finite(self) -> VerifierOutput:
        """Reject non-finite scores.

        Returns:
            This output when all scores are finite.
        """
        values = (
            *(() if self.score is None else (self.score,)),
            *self.scores.values(),
            *self.seats.values(),
            *(value for value in self.metrics.values() if value is not None),
        )
        if any(not math.isfinite(item) for item in values):
            raise ValueError("Verifier emitted non-finite scores")
        return self


class RubricCriterion(FrozenModel):
    """One Agent or Human rubric criterion."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    weight: float = Field(default=1, gt=0)
    min_score: float = 0
    max_score: float = 1

    @model_validator(mode="after")
    def _range(self) -> RubricCriterion:
        if self.max_score <= self.min_score:
            raise ValueError("max_score must exceed min_score")
        return self


def rubric_score(criteria: Sequence[RubricCriterion], scores: Mapping[str, float]) -> float:
    """The score a rubric gives: each criterion normalized to 0 to 1, then weight-averaged.

    A judge and a reviewer both score this way, so a rubric means the same thing
    whoever applies it.

    Returns:
        The weighted mean of the normalized criterion scores, from 0 to 1.

    Raises:
        ValueError: When ``scores`` does not name exactly the rubric's criteria, or a
            score is outside its criterion's range.
    """
    expected = {item.name: item for item in criteria}
    if set(scores) != set(expected):
        raise ValueError(f"scores must match rubric criteria: {sorted(expected)!r}")
    weighted = 0.0
    total_weight = 0.0
    for name, criterion in expected.items():
        value = float(scores[name])
        if not math.isfinite(value) or not criterion.min_score <= value <= criterion.max_score:
            raise ValueError(
                f"criterion {name!r} must be between "
                f"{criterion.min_score} and {criterion.max_score}"
            )
        normalized = (value - criterion.min_score) / (criterion.max_score - criterion.min_score)
        weighted += normalized * criterion.weight
        total_weight += criterion.weight
    return weighted / total_weight


@lru_cache(maxsize=1)
def _bundled_catalog() -> ModelCatalog:
    return ModelCatalog()


def criterion_metric(name: str) -> str:
    """The rating metric a rubric criterion becomes: its name as a metric slug.

    Returns:
        Lowercase letters, digits, and underscores.

    Examples:
        >>> criterion_metric("Tone of voice")
        'tone_of_voice'
    """
    slug = "".join(char if char.isalnum() else "_" for char in name.strip().lower())
    slug = "_".join(part for part in slug.split("_") if part) or "criterion"
    return slug if slug[0].isalpha() else f"m_{slug}"


def criterion_metric_names(
    criteria: Sequence[RubricCriterion], declared: Iterable[str] = ()
) -> dict[str, str]:
    """Each rubric criterion's rating metric name, unique within its Verifier.

    A criterion whose slug a declared metric already has is that metric.
    Criteria whose names slug the same, such as ``Tone`` and ``tone!``, get
    ``_2``, ``_3`` and so on, in the order they are listed.

    Returns:
        The metric name by criterion name.

    Examples:
        >>> rubric = [RubricCriterion(name=n, description="d") for n in ("Tone", "tone!")]
        >>> criterion_metric_names(rubric)
        {'Tone': 'tone', 'tone!': 'tone_2'}
    """
    own = set(declared)
    taken = set(own)
    names: dict[str, str] = {}
    for item in criteria:
        base = criterion_metric(item.name)
        if base in own and base not in names.values():
            names[item.name] = base
            continue
        name, number = base, 1
        while name in taken:
            number += 1
            name = f"{base}_{number}"
        taken.add(name)
        names[item.name] = name
    return names


def criterion_metrics(
    verifier: AgentVerifier | HumanVerifier, scores: Mapping[str, float]
) -> dict[str, float | None]:
    """A rubric's scores as rating metrics, one per criterion, named by :func:`criterion_metric`.

    A criterion with no score is ``None``.

    Returns:
        Each criterion's rating by metric name.
    """
    declared = {spec.name for spec in verifier.metrics}
    names = criterion_metric_names(verifier.criteria, declared)
    return {
        names[item.name]: (float(scores[item.name]) if scores.get(item.name) is not None else None)
        for item in verifier.criteria
    }


def resolve_metrics(
    output: VerifierOutput, specs: Sequence[MetricSpec], *, verifier_name: str
) -> VerifierOutput:
    """Check an output's metrics against what its Verifier declares, and fill in its score.

    With declared metrics, ``scores`` is an alias for ``metrics`` and is merged
    into it; a key in both is an error. Every value must be a declared metric
    that is not ``running`` (those come from ``measure``), within its range.
    A Verifier that declares nothing keeps today's behavior.

    Returns:
        The output, with ``metrics`` complete and ``score`` set.

    Raises:
        ValueError: When a metric is undeclared or invalid, or the output has
            no score and declares nothing to derive one from.
    """
    if not specs:
        if output.metrics:
            raise ValueError(
                f"Verifier {verifier_name!r} returned metrics "
                f"({', '.join(sorted(output.metrics))}) but declares none. Declare them in "
                "its metrics list."
            )
        return output
    declared = {spec.name: spec for spec in specs}
    metrics: dict[str, float | None] = dict(output.metrics)
    for key, number in output.scores.items():
        if key in declared:
            if key in metrics:
                raise ValueError(
                    f"Verifier {verifier_name!r} returned {key!r} in both scores and metrics."
                )
            metrics[key] = number
    for key, value in metrics.items():
        spec = declared.get(key)
        if spec is None or spec.kind == "running":
            known = ", ".join(sorted(n for n, s in declared.items() if s.kind != "running"))
            raise ValueError(
                f"Verifier {verifier_name!r} returned metric {key!r}, which it does not "
                + ("declare" if spec is None else "measure at the end: it is a running metric")
                + f". Its end-of-episode metrics are: {known or 'none'}."
            )
        metrics[key] = spec.check_value(value)
    scores = {key: number for key, number in output.scores.items() if key not in declared}
    score = output.score
    if score is None:
        score = default_score(specs, metrics)
    return output.model_copy(update={"metrics": metrics, "scores": scores, "score": score})


def coerce_verifier_output(
    value: Any, *, verifier_name: str, metrics: Sequence[MetricSpec] = ()
) -> VerifierOutput:
    """Accept a VerifierOutput, mapping, or object with the same fields.

    Args:
        value: What ``check`` returned.
        verifier_name: For error messages.
        metrics: The metrics the Verifier declares, to check its values against
            and to derive a missing score from.

    Returns:
        A validated VerifierOutput with a score.
    """
    if isinstance(value, VerifierOutput):
        return resolve_metrics(value, metrics, verifier_name=verifier_name)
    if isinstance(value, Mapping):
        declared = {spec.name for spec in metrics}
        if declared and value and all(key in declared for key in value):
            # A check that returns only its declared metrics, such as {"margin_usd": 12.5}.
            value = {"metrics": dict(value)}
        try:
            parsed = VerifierOutput.model_validate(value)
        except Exception as exc:
            raise ValueError(
                f"Verifier {verifier_name!r} returned an invalid result.\n"
                "Return VerifierOutput or a mapping with a finite 'score' and optional "
                "'scores', 'metrics', 'evidence', and 'feedback'. A Verifier that declares "
                "metrics may return just {metric: value}, and leave out the score.\n"
                f"Got: {value!r}\n"
                f"Cause: {exc}"
            ) from exc
        return resolve_metrics(parsed, metrics, verifier_name=verifier_name)
    raise ValueError(
        f"Verifier {verifier_name!r} must return VerifierOutput or a mapping.\n"
        f"Got {type(value).__name__}."
    )


def _file_digest(path: Path) -> str | None:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError:
        return None


def _accepts_episode(fn: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    parameters = [
        parameter for name, parameter in signature.parameters.items() if name not in {"self", "cls"}
    ]
    if not parameters:
        return False
    if any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters):
        return True
    first = parameters[0]
    return first.kind in {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }


class Verifier(FrozenModel):
    """Fields shared by every completed-Trial verifier."""

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    info: Any = None
    criteria: tuple[RubricCriterion, ...] = ()
    weight: float = Field(default=1, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    secrets: tuple[SecretReference, ...] = ()
    """Names the Job supplies to this Verifier, such as a key for a system it checks."""
    metrics: tuple[MetricSpec, ...] = ()
    """The metrics this Verifier produces, each optionally a ``gate`` with a ``target``."""

    @model_validator(mode="before")
    @classmethod
    def _compatibility_names(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        schema_version = payload.pop("schema_version", "2")
        if str(schema_version) != "2":
            raise ValueError("only verifier schema version 2 is supported")
        if "version" not in payload and "revision" in payload:
            payload["version"] = payload.pop("revision")
        if "criteria" not in payload and "rubric" in payload:
            payload["criteria"] = payload.pop("rubric")
        payload.pop("evidence", None)
        return payload

    @model_validator(mode="after")
    def _semantic_version(self) -> Verifier:
        from plural.common import semantic_version

        semantic_version(self.version)
        return self

    @property
    def scores(self) -> bool:
        """Whether this Verifier produces a score at the end of the episode."""
        return True

    @property
    def revision(self) -> str:
        """Compatibility name used by internal hosted code."""
        return self.version

    @property
    def rubric(self) -> tuple[RubricCriterion, ...]:
        """Compatibility name used by the execution engine."""
        return self.criteria

    @model_validator(mode="after")
    def _unique_metrics(self) -> Verifier:
        names = [spec.name for spec in self.metric_specs]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(
                f"Verifier {self.name!r} declares metric {', '.join(repeated)} more than once"
            )
        return self

    @property
    def metric_specs(self) -> tuple[MetricSpec, ...]:
        """Every metric this Verifier produces.

        Those it declares, then one ``rating`` per rubric criterion it does not
        already declare.
        """
        declared = {spec.name for spec in self.metrics}
        criteria = getattr(self, "criteria", ())
        names = criterion_metric_names(criteria, declared)
        rated = tuple(
            MetricSpec(
                name=names[item.name],
                kind="rating",
                range=(item.min_score, item.max_score),
                description=item.description,
            )
            for item in criteria
            if names[item.name] not in declared
        )
        return (*self.metrics, *rated)

    def _hash_payload(self) -> dict[str, Any]:
        return _without_empty_metrics(_legacy_runtime_keys(self.model_dump(mode="json")))

    @property
    def content_hash(self) -> str:
        """Stable Verifier version digest."""
        return revision_hash("verifier", self._hash_payload())


class DeterministicVerifier(Verifier):
    """Code that verifies an episode: it scores the end, rewards actions, or both.

    ``check`` scores the finished episode; that score is what Tasks and
    Benchmarks rank on. It is a function of the :class:`Episode`, a
    ``{"python": "verify.py:check"}`` reference, or a command argv.

    ``reward`` rewards each action while the episode runs. It is a function of
    one :class:`Step`, or a ``{"python": "verify.py:reward"}`` reference, and
    runs in the Runtime beside the Apps, so it can read every App. What it
    returns goes to the Trial's reward ledger. Rewards reach the score only
    when ``check`` is :func:`total_reward`.

    ``hindsight`` credits the finished trajectory as a whole: a function of a
    :class:`~plural.rewards.HindsightTrial` that returns
    :class:`~plural.rewards.Credit` values, or a ``{"python":
    "verify.py:efficiency"}`` reference. It runs after the score, and can also
    run later on stored Trials with ``plural verifier apply``.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra={
            "anyOf": [
                {"required": ["check"]},
                {"required": ["command"]},
                {"required": ["reward"]},
                {"required": ["hindsight"]},
            ]
        },
    )

    kind: Literal["deterministic"] = "deterministic"
    check: Any = None
    reward: Any = None
    hindsight: Any = None
    measure: Any = None
    """Running metrics after each action: a function of one :class:`Step`
    returning ``{metric: value}`` for metrics declared ``running``, or a
    ``{"python": "verify.py:measure"}`` reference. It runs in the App host,
    like ``reward``."""
    runtime: VerifierRuntime = Field(default_factory=VerifierRuntime)
    result_path: str = "verifier-result.json"
    evidence_required: bool = True

    _source_digest: str | None = PrivateAttr(default=None)
    _source_dir: Path | None = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def _normalize_hooks(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "check" not in payload and "command" in payload:
            payload["check"] = payload.pop("command")
        check = payload.get("check")
        if isinstance(check, dict) and "reward" in check:
            raise ValueError(
                f"Cannot create DeterministicVerifier {payload.get('name')!r}.\n"
                "check: {reward: ...} was removed. Score by this Verifier's own "
                "rewards with:\n"
                "  check: total_reward\n"
                "  reward: verify.py:progress"
            )
        if check == TOTAL_REWARD or check == {"builtin": TOTAL_REWARD}:
            payload["check"] = total_reward
        elif isinstance(check, str):
            payload["check"] = (
                {"python": check} if _looks_like_reference(check) else tuple(shlex.split(check))
            )
        elif isinstance(check, list):
            payload["check"] = tuple(str(item) for item in check)
        for hook in ("reward", "hindsight", "measure"):
            if isinstance(payload.get(hook), str):
                payload[hook] = {"python": payload[hook]}
        payload.pop("required_artifacts", None)
        payload.pop("evidence", None)
        return payload

    @model_validator(mode="after")
    def _valid_hooks(self) -> DeterministicVerifier:
        if (
            self.check is None
            and self.reward is None
            and self.hindsight is None
            and self.measure is None
        ):
            raise ValueError(
                f"Cannot create DeterministicVerifier {self.name!r}.\n"
                "Give it check, to score the finished episode, reward, to reward each "
                "action, hindsight, to credit the finished trajectory, or several:\n"
                "  DeterministicVerifier(name='solved', check=solved, reward=progress)"
            )
        check = self.check
        if check is not None and not (
            (callable(check) and _accepts_episode(check))
            or (isinstance(check, dict) and check.get("python"))
            or (isinstance(check, tuple) and check and all(isinstance(i, str) for i in check))
        ):
            raise ValueError(
                f"Cannot create DeterministicVerifier {self.name!r}.\n"
                "check must be a function that accepts the finished Episode, a "
                "'verify.py:check' reference, a command, or total_reward.\n"
                "Define it like:\n"
                "  def check(episode: Episode) -> VerifierOutput: ...\n"
                f"Got {type(check).__name__}: {check!r}."
            )
        if check is total_reward and self.reward is None:
            raise ValueError(
                f"Cannot create DeterministicVerifier {self.name!r}.\n"
                "check=total_reward scores the episode by this Verifier's own rewards, "
                "so it needs a reward function too."
            )
        reward = self.reward
        if reward is not None and not (
            (callable(reward) and _accepts_episode(reward))
            or (isinstance(reward, dict) and reward.get("python"))
        ):
            raise ValueError(
                f"Cannot create DeterministicVerifier {self.name!r}.\n"
                "reward must be a function that accepts one Step, or a "
                "'verify.py:reward' reference. Define it like:\n"
                "  def reward(step: Step) -> float | None: ...\n"
                f"Got {type(reward).__name__}: {reward!r}."
            )
        measure = self.measure
        if measure is not None and not (
            (callable(measure) and _accepts_episode(measure))
            or (isinstance(measure, dict) and measure.get("python"))
        ):
            raise ValueError(
                f"Cannot create DeterministicVerifier {self.name!r}.\n"
                "measure must be a function that accepts one Step, or a "
                "'verify.py:measure' reference. Define it like:\n"
                "  def measure(step: Step) -> dict[str, float]: ...\n"
                f"Got {type(measure).__name__}: {measure!r}."
            )
        if measure is not None and not any(spec.kind == "running" for spec in self.metrics):
            raise ValueError(
                f"Cannot create DeterministicVerifier {self.name!r}.\n"
                "measure samples running metrics, so declare at least one:\n"
                "  metrics: [{name: cash_on_hand, kind: running, aggregate: final}]"
            )
        hindsight = self.hindsight
        if hindsight is not None and not (
            (callable(hindsight) and _accepts_episode(hindsight))
            or (isinstance(hindsight, dict) and hindsight.get("python"))
        ):
            raise ValueError(
                f"Cannot create DeterministicVerifier {self.name!r}.\n"
                "hindsight must be a function that accepts one HindsightTrial, or a "
                "'verify.py:efficiency' reference. Define it like:\n"
                "  def efficiency(trial: HindsightTrial): yield trial.credit(...)\n"
                f"Got {type(hindsight).__name__}: {hindsight!r}."
            )
        return self

    @field_serializer("check", "reward", "hindsight", "measure")
    def _serialize_hook(self, hook: Any) -> Any:
        if hook is total_reward:
            return {"builtin": TOTAL_REWARD}
        if callable(hook):
            return self._callable_reference(hook)
        if isinstance(hook, tuple):
            return list(hook)
        return hook

    def _hash_payload(self) -> dict[str, Any]:
        payload = _legacy_runtime_keys(self.model_dump(mode="json"))
        # A Verifier without a hook hashes as it did before that hook existed.
        for hook in ("reward", "hindsight", "measure"):
            if payload.get(hook) is None:
                payload.pop(hook, None)
        return _without_empty_metrics(payload)

    def _callable_reference(self, hook: Callable[..., Any]) -> dict[str, str]:
        """Name a callable hook and fingerprint the code behind it.

        The digest makes an edit to the hook's source a new Verifier version
        rather than a silent change under an old one. A project Verifier binds
        the digest of its whole directory; otherwise it is the source file's.

        Returns:
            The ``python`` reference and, when known, its source ``digest``.
        """
        source = inspect.getsourcefile(hook)
        qualname = getattr(hook, "__qualname__", getattr(hook, "__name__", "hook"))
        reference = {"python": f"{Path(source).name}:{qualname}" if source else qualname}
        digest = self._source_digest or (_file_digest(Path(source)) if source else None)
        if digest:
            reference["digest"] = digest
        return reference

    @property
    def scores(self) -> bool:
        """Whether this Verifier produces a score: it has ``check``."""
        return self.check is not None

    @property
    def command(self) -> tuple[str, ...]:
        """``check`` as a command argv, if it is one."""
        check = self.check
        if isinstance(check, tuple) and check and all(isinstance(item, str) for item in check):
            return check
        return ()

    @property
    def python_ref(self) -> str | None:
        """``check`` as a ``file.py:function`` reference, if it is one."""
        return _reference(self.check)

    @property
    def reward_ref(self) -> str | None:
        """``reward`` as a ``file.py:function`` reference, if it is one."""
        return _reference(self.reward)

    @property
    def measure_ref(self) -> str | None:
        """``measure`` as a ``file.py:function`` reference, if it is one."""
        return _reference(self.measure)

    @property
    def measure_fn(self) -> Callable[..., Any] | None:
        """``measure`` as an in-process function, if it is one."""
        return self.measure if callable(self.measure) else None

    @property
    def hindsight_ref(self) -> str | None:
        """``hindsight`` as a ``file.py:function`` reference, if it is one."""
        return _reference(self.hindsight)

    @property
    def check_fn(self) -> Callable[[Episode], Any] | None:
        """``check`` as an in-process function, if it is one."""
        return self.check if callable(self.check) else None

    @property
    def reward_fn(self) -> Callable[..., Any] | None:
        """``reward`` as an in-process function, if it is one."""
        return self.reward if callable(self.reward) else None

    @property
    def hindsight_fn(self) -> Callable[..., Any] | None:
        """``hindsight`` as an in-process function, if it is one."""
        return self.hindsight if callable(self.hindsight) else None

    @property
    def source_dir(self) -> Path | None:
        """The folder the hooks were imported from, for a project Verifier."""
        return self._source_dir

    def bind_source(self, digest: str, directory: Path | None = None) -> None:
        """Fingerprint callable hooks by the package that ships them."""
        self._source_digest = digest
        self._source_dir = directory

    def bind_source_digest(self, digest: str) -> None:
        """Fingerprint callable hooks by the package that ships them."""
        self._source_digest = digest

    def invoke(self, episode: Episode) -> VerifierOutput:
        """Run ``check`` in-process on the finished Episode.

        Returns:
            A validated VerifierOutput.
        """
        fn = self.check_fn
        if fn is None:
            raise ValueError(
                f"Verifier {self.name!r} cannot be invoked in-process.\n"
                "Its check is a command or Python reference that has not been resolved."
            )
        try:
            output = fn(episode)
        except Exception as exc:
            raise ValueError(f"Verifier {self.name!r} check raised {described(exc)}") from exc
        return coerce_verifier_output(output, verifier_name=self.name, metrics=self.metric_specs)


def hindsight_hooks(verifiers: Iterable[Any]) -> list[HindsightVerifier]:
    """The ``hindsight`` hooks of these Verifiers that can run in this process.

    Accepts Verifiers or a Task's weighted Verifiers. A hook still named only by
    reference, such as one pulled from a hosted project without its source, is
    left out.

    Returns:
        One runner per hook, recording under the Verifier's name and version.
    """
    hooks: list[HindsightVerifier] = []
    for item in verifiers:
        verifier = getattr(item, "verifier", item)
        if isinstance(verifier, DeterministicVerifier) and verifier.hindsight_fn is not None:
            hooks.append(
                HindsightVerifier(
                    verifier.hindsight_fn, name=verifier.name, version=verifier.version
                )
            )
    return hooks


TOTAL_REWARD = "total_reward"


def _without_empty_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    # A Verifier with no metrics hashes as it did before metrics existed, and a
    # metric with no gate or target as it did before those fields existed.
    if not payload.get("metrics"):
        payload.pop("metrics", None)
        return payload
    metrics = []
    for item in payload["metrics"]:
        item = dict(item)
        if not item.get("gate"):
            item.pop("gate", None)
        if item.get("target") is None:
            item.pop("target", None)
        metrics.append(item)
    payload["metrics"] = metrics
    return payload


def total_reward(episode: Episode) -> VerifierOutput:
    """Score an episode by the sum of its Verifier's own rewards.

    Use it as a Verifier's ``check`` to make the reward the score:
    ``DeterministicVerifier(name="return", check=total_reward, reward=progress)``,
    or ``check: total_reward`` in ``verifier.yaml``.

    With seats, each seat scores the total of its own rewards, and the
    episode the mean of those.

    Returns:
        The total of ``episode.rewards`` as the score.
    """
    if episode.seats:
        seats = {seat: math.fsum(episode.seat_rewards.get(seat, ())) for seat in episode.seats}
        mean = math.fsum(seats.values()) / len(seats)
        return VerifierOutput(
            score=mean,
            seats=seats,
            evidence=tuple(f"{seat}: rewards totalling {value:g}" for seat, value in seats.items()),
        )
    total = float(sum(episode.rewards))
    return VerifierOutput(
        score=total, evidence=(f"{len(episode.rewards)} step rewards totalling {total:g}",)
    )


def _looks_like_reference(value: str) -> bool:
    file, separator, function = value.partition(":")
    return bool(separator and file.endswith(".py") and function and " " not in value)


def _reference(hook: Any) -> str | None:
    if isinstance(hook, dict):
        value = hook.get("python")
        return str(value) if value else None
    return None


class AgentVerifier(Verifier):
    """Model-judge verifier with its own runtime and connectivity policy."""

    kind: Literal["agent"] = "agent"
    model: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    provider: str | None = None
    fallback_models: tuple[str, ...] = ()
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1)
    runtime: VerifierRuntime = Field(default_factory=VerifierRuntime)

    @model_validator(mode="after")
    def _catalog_model(self, info: ValidationInfo) -> AgentVerifier:
        context = info.context if isinstance(info.context, dict) else {}
        catalog = context.get("catalog") or _bundled_catalog()
        if not isinstance(catalog, ModelCatalog):
            raise TypeError("catalog validation context must be a ModelCatalog")
        selected = catalog.get(self.model)
        if selected is None:
            nearby = catalog.suggest(self.model) if hasattr(catalog, "suggest") else []
            hint = f" Did you mean {', '.join(nearby)}?" if nearby else ""
            raise ValueError(
                f"Verifier {self.name!r}: unknown model {self.model!r}.{hint} "
                "`plural model list` shows every model id."
            )
        if self.provider is not None and self.provider not in selected.host_providers():
            raise ValueError(
                f"Cannot create AgentVerifier {self.name!r}.\n"
                f"provider {self.provider!r} is not a catalog endpoint for model {self.model!r}."
            )
        unknown = [model for model in self.fallback_models if catalog.get(model) is None]
        if unknown:
            raise ValueError(
                f"Cannot create AgentVerifier {self.name!r}.\n"
                "unknown fallback models: " + ", ".join(repr(model) for model in unknown)
            )
        return self

    @classmethod
    def from_catalog(cls, catalog: ModelCatalog, **fields: Any) -> AgentVerifier:
        """Create a model judge against an explicit effective catalog.

        Returns:
            A validated AgentVerifier without global registration.
        """
        return cls.model_validate(fields, context={"catalog": catalog})

    @property
    def routing(self) -> RoutingSpec:
        """Internal routing representation used by the judge harness."""
        return RoutingSpec(provider=self.provider, fallback_models=self.fallback_models)


class HumanVerifier(Verifier):
    """Human review verifier."""

    kind: Literal["human"] = "human"
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1)
    instructions: str = ""


VerifierDefinition = Annotated[
    DeterministicVerifier | AgentVerifier | HumanVerifier,
    Field(discriminator="kind"),
]


class WeightedVerifier(FrozenModel):
    """One pinned Verifier revision and aggregate weight."""

    verifier: VerifierDefinition
    weight: float = Field(default=1, gt=0)


__all__ = [
    "AgentVerifier",
    "AppSnapshot",
    "DeterministicVerifier",
    "Episode",
    "EpisodeUsage",
    "HumanVerifier",
    "RubricCriterion",
    "Step",
    "StepTask",
    "StopReason",
    "Verifier",
    "VerifierDefinition",
    "VerifierOutput",
    "VerifierRuntime",
    "WeightedVerifier",
    "coerce_verifier_output",
    "criterion_metric",
    "criterion_metric_names",
    "criterion_metrics",
    "resolve_metrics",
]
