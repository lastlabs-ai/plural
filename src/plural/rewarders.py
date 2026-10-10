"""First-class Rewarder definitions."""

from __future__ import annotations

import hashlib
import inspect
import math
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, PrivateAttr, ValidationInfo, field_serializer, model_validator

from plural.apps.definition import SecretReference
from plural.catalog import ModelCatalog
from plural.common import FrozenModel, RoutingSpec
from plural.identity import revision_hash
from plural.sandbox.models import NetworkMode, ResourceRequirements


class RewarderRuntime(FrozenModel):
    """Machine for a rewarder that needs its own sandbox.

    The default runs in the Task Environment. Set a provider, image, network,
    resource limit, or timeout to use a different machine.
    """

    provider: str = Field(default="docker", min_length=1)
    image: str | None = None
    network: NetworkMode = NetworkMode.PUBLIC
    network_allowlist: tuple[str, ...] = ()
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    timeout_seconds: float = Field(default=60, gt=0)

    @model_validator(mode="after")
    def _network(self) -> RewarderRuntime:
        if self.network_allowlist and self.network is not NetworkMode.ALLOWLIST:
            raise ValueError(
                "Cannot create RewarderRuntime.\n"
                f"allowed_hosts is set but network={self.network.value!r}.\n"
                "Set network='allowlist' or remove allowed_hosts."
            )
        return self


def runtime_is_custom(runtime: RewarderRuntime) -> bool:
    """Return whether this runtime names its own machine.

    Docker, public network, and a 60 second timeout, with no image or resource
    limits, is the default and runs in the Task Environment.

    Returns:
        True when any runtime field differs from that default.
    """
    return bool(
        runtime.image
        or runtime.network is not NetworkMode.PUBLIC
        or runtime.network_allowlist
        or runtime.resources.configured
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


STOP_REASONS: tuple[str, ...] = (
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
)


class EpisodeOutcome(FrozenModel):
    """How one episode ended.

    ``stop_reason`` is one of :data:`STOP_REASONS`. ``terminated`` means the
    Environment declared the episode over; ``truncated`` means it was cut short
    by the Environment or by a Harness budget. Neither is set when the Agent
    chose to stop, so read ``stop_reason`` to tell those cases apart.
    """

    stop_reason: Literal[
        "",
        "environment_terminated",
        "environment_truncated",
        "agent_finished",
        "agent_response",
        "max_turns",
        "max_seconds",
        "max_cost",
        "error",
    ] = ""
    terminated: bool = False
    truncated: bool = False
    turns: int = 0
    total_reward: float = 0

    @property
    def completed(self) -> bool:
        """Whether the Environment itself ended the episode."""
        return self.terminated


class AppSnapshot(FrozenModel):
    """One App at the start and end of an episode, as a Rewarder sees it.

    ``initial`` and ``final`` are the App's snapshots, or ``None`` when it has
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

        Available to function Rewarders while the Trial's Runtime is still
        running. An action that can change state is refused.

        Returns:
            The action's observation.

        Raises:
            RuntimeError: When the episode's Apps are no longer running.
        """
        if self._query is None:
            raise RuntimeError(
                "App queries are only available to function Rewarders during a Trial. "
                "Read the App's final snapshot instead."
            )
        return self._query(action, arguments)


class Episode(FrozenModel):
    """Completed Agent episode handed to a Rewarder.

    ``apps`` holds each App's initial and final snapshots and, for function
    Rewarders, read-only ``query`` access. ``state`` is a shortcut: the one
    App's final snapshot when the Environment has one App, otherwise a mapping
    of App name to final snapshot. Neither is ever shown to the Agent.
    ``observation`` is what the Agent last saw. Rewards are not here: they
    live in the Trial's reward ledger and never feed a score.
    """

    observation: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    apps: dict[str, AppSnapshot] = Field(default_factory=dict)
    trajectory: list[Any] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    usage: EpisodeUsage = Field(default_factory=EpisodeUsage)
    outcome: EpisodeOutcome = Field(default_factory=EpisodeOutcome)

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
    """The Task an episode is working on, as a ``step`` hook sees it."""

    name: str = ""
    info: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    """One action the Agent took, as a Rewarder's ``step`` hook sees it.

    ``observation`` is what the Agent saw back; ``error`` is set instead when
    the action rejected its input. ``previous_state`` and ``current_state``
    are the acting App's snapshots around the action, or ``None`` when it does
    not snapshot on each step. ``apps`` reads any App, by name: ``state`` for
    a Python App, ``snapshot()``, and ``query(action, **arguments)`` for a
    read-only action. Nothing here reaches the Agent.
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


class RewarderOutput(FrozenModel):
    """What a Rewarder's ``final`` hook returns for the finished episode.

    ``score`` is the headline number for the Task; ``scores`` holds any named
    sub-metrics behind it. Step rewards are separate: a ``step`` hook returns a
    number per action, which goes to the reward ledger and never into a score.
    """

    score: float
    scores: dict[str, float] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    feedback: str = ""

    def validated_finite(self) -> RewarderOutput:
        """Reject non-finite scores.

        Returns:
            This output when all scores are finite.
        """
        if any(not math.isfinite(item) for item in (self.score, *self.scores.values())):
            raise ValueError("Rewarder emitted non-finite scores")
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


@lru_cache(maxsize=1)
def _bundled_catalog() -> ModelCatalog:
    return ModelCatalog()


def coerce_rewarder_output(value: Any, *, rewarder_name: str) -> RewarderOutput:
    """Accept a RewarderOutput, mapping, or object with the same fields.

    Returns:
        A validated RewarderOutput.
    """
    if isinstance(value, RewarderOutput):
        return value
    if isinstance(value, Mapping):
        try:
            return RewarderOutput.model_validate(value)
        except Exception as exc:
            raise ValueError(
                f"Rewarder {rewarder_name!r} returned an invalid result.\n"
                "Return RewarderOutput or a mapping with a finite 'score' and optional "
                "'scores', 'evidence', and 'feedback'.\n"
                f"Got: {value!r}\n"
                f"Cause: {exc}"
            ) from exc
    raise ValueError(
        f"Rewarder {rewarder_name!r} must return RewarderOutput or a mapping.\n"
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


class Rewarder(FrozenModel):
    """Fields shared by every completed-Trial rewarder."""

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    info: Any = None
    criteria: tuple[RubricCriterion, ...] = ()
    weight: float = Field(default=1, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    secrets: tuple[SecretReference, ...] = ()
    """Names the Job supplies to this Rewarder, such as a key for a system it checks."""

    @model_validator(mode="before")
    @classmethod
    def _compatibility_names(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        schema_version = payload.pop("schema_version", "2")
        if str(schema_version) != "2":
            raise ValueError("only rewarder schema version 2 is supported")
        if "version" not in payload and "revision" in payload:
            payload["version"] = payload.pop("revision")
        if "criteria" not in payload and "rubric" in payload:
            payload["criteria"] = payload.pop("rubric")
        payload.pop("evidence", None)
        return payload

    @model_validator(mode="after")
    def _semantic_version(self) -> Rewarder:
        from plural.common import semantic_version

        semantic_version(self.version)
        return self

    @property
    def scores(self) -> bool:
        """Whether this Rewarder produces a score at the end of the episode."""
        return True

    @property
    def revision(self) -> str:
        """Compatibility name used by internal hosted code."""
        return self.version

    @property
    def rubric(self) -> tuple[RubricCriterion, ...]:
        """Compatibility name used by the execution engine."""
        return self.criteria

    def _hash_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def content_hash(self) -> str:
        """Stable Rewarder version digest."""
        return revision_hash("rewarder", self._hash_payload())


class DeterministicRewarder(Rewarder):
    """Code that rewards an episode: per step, at the end, or both.

    ``final`` scores the finished episode; that score is what Tasks and
    Benchmarks rank on. It is a function of the :class:`Episode`, a
    ``{"python": "reward.py:final"}`` reference, or a command argv.

    ``step`` rewards each action while the episode runs. It is a function of
    one :class:`Step`, or a ``{"python": "reward.py:step"}`` reference, and
    runs in the Runtime beside the Apps, so it can read every App. What it
    returns goes to the Trial's reward ledger and never into the score.
    """

    kind: Literal["deterministic"] = "deterministic"
    final: Any = None
    step: Any = None
    runtime: RewarderRuntime = Field(default_factory=RewarderRuntime)
    result_path: str = "rewarder-result.json"
    evidence_required: bool = True

    _source_digest: str | None = PrivateAttr(default=None)
    _source_dir: Path | None = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def _normalize_hooks(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "check" in payload or "command" in payload:
            raise ValueError(
                "A Rewarder's check is now `final`: rename check: (or command:) to final:."
            )
        final = payload.get("final")
        if isinstance(final, str):
            payload["final"] = (
                {"python": final} if _looks_like_reference(final) else tuple(shlex.split(final))
            )
        elif isinstance(final, list):
            payload["final"] = tuple(str(item) for item in final)
        step = payload.get("step")
        if isinstance(step, str):
            payload["step"] = {"python": step}
        payload.pop("required_artifacts", None)
        payload.pop("evidence", None)
        return payload

    @model_validator(mode="after")
    def _valid_hooks(self) -> DeterministicRewarder:
        if self.final is None and self.step is None:
            raise ValueError(
                f"Cannot create DeterministicRewarder {self.name!r}.\n"
                "Give it final, to score the finished episode, step, to reward each "
                "action, or both:\n"
                "  DeterministicRewarder(name='solved', final=solved, step=progress)"
            )
        final = self.final
        if final is not None and not (
            (callable(final) and _accepts_episode(final))
            or (isinstance(final, dict) and final.get("python"))
            or (isinstance(final, tuple) and final and all(isinstance(i, str) for i in final))
        ):
            raise ValueError(
                f"Cannot create DeterministicRewarder {self.name!r}.\n"
                "final must be a function that accepts the finished Episode, a "
                "'reward.py:final' reference, or a command.\n"
                "Define it like:\n"
                "  def final(episode: Episode) -> RewarderOutput: ...\n"
                f"Got {type(final).__name__}: {final!r}."
            )
        step = self.step
        if step is not None and not (
            (callable(step) and _accepts_episode(step))
            or (isinstance(step, dict) and step.get("python"))
        ):
            raise ValueError(
                f"Cannot create DeterministicRewarder {self.name!r}.\n"
                "step must be a function that accepts one Step, or a 'reward.py:step' "
                "reference. Define it like:\n"
                "  def step(step: Step) -> float | None: ...\n"
                f"Got {type(step).__name__}: {step!r}."
            )
        return self

    @field_serializer("final", "step")
    def _serialize_hook(self, hook: Any) -> Any:
        if callable(hook):
            return self._callable_reference(hook)
        if isinstance(hook, tuple):
            return list(hook)
        return hook

    def _callable_reference(self, hook: Callable[..., Any]) -> dict[str, str]:
        """Name a callable hook and fingerprint the code behind it.

        The digest makes an edit to the hook's source a new Rewarder version
        rather than a silent change under an old one. A project Rewarder binds
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
        """Whether this Rewarder produces a score: it has ``final``."""
        return self.final is not None

    @property
    def command(self) -> tuple[str, ...]:
        """``final`` as a command argv, if it is one."""
        final = self.final
        if isinstance(final, tuple) and final and all(isinstance(item, str) for item in final):
            return final
        return ()

    @property
    def python_ref(self) -> str | None:
        """``final`` as a ``file.py:function`` reference, if it is one."""
        return _reference(self.final)

    @property
    def step_ref(self) -> str | None:
        """``step`` as a ``file.py:function`` reference, if it is one."""
        return _reference(self.step)

    @property
    def final_fn(self) -> Callable[[Episode], Any] | None:
        """``final`` as an in-process function, if it is one."""
        return self.final if callable(self.final) else None

    @property
    def step_fn(self) -> Callable[..., Any] | None:
        """``step`` as an in-process function, if it is one."""
        return self.step if callable(self.step) else None

    @property
    def source_dir(self) -> Path | None:
        """The folder the hooks were imported from, for a project Rewarder."""
        return self._source_dir

    def bind_source(self, digest: str, directory: Path | None = None) -> None:
        """Fingerprint callable hooks by the package that ships them."""
        self._source_digest = digest
        self._source_dir = directory

    def bind_source_digest(self, digest: str) -> None:
        """Fingerprint callable hooks by the package that ships them."""
        self._source_digest = digest

    def invoke(self, episode: Episode) -> RewarderOutput:
        """Run ``final`` in-process on the finished Episode.

        Returns:
            A validated RewarderOutput.
        """
        fn = self.final_fn
        if fn is None:
            raise ValueError(
                f"Rewarder {self.name!r} cannot be invoked in-process.\n"
                "Its final is a command or Python reference that has not been resolved."
            )
        try:
            return coerce_rewarder_output(fn(episode), rewarder_name=self.name)
        except TypeError as exc:
            raise ValueError(
                f"Rewarder {self.name!r} final failed to accept the Episode.\n"
                "The function must accept one argument: the finished Episode.\n"
                f"Cause: {exc}"
            ) from exc


def _looks_like_reference(value: str) -> bool:
    file, separator, function = value.partition(":")
    return bool(separator and file.endswith(".py") and function and " " not in value)


def _reference(hook: Any) -> str | None:
    if isinstance(hook, dict):
        value = hook.get("python")
        return str(value) if value else None
    return None


class AgentRewarder(Rewarder):
    """Model-judge rewarder with its own runtime and connectivity policy."""

    kind: Literal["agent"] = "agent"
    model: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    provider: str | None = None
    fallback_models: tuple[str, ...] = ()
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1)
    runtime: RewarderRuntime = Field(default_factory=RewarderRuntime)

    @model_validator(mode="after")
    def _catalog_model(self, info: ValidationInfo) -> AgentRewarder:
        context = info.context if isinstance(info.context, dict) else {}
        catalog = context.get("catalog") or _bundled_catalog()
        if not isinstance(catalog, ModelCatalog):
            raise TypeError("catalog validation context must be a ModelCatalog")
        selected = catalog.get(self.model)
        if selected is None:
            nearby = catalog.suggest(self.model) if hasattr(catalog, "suggest") else []
            hint = (
                f" Nearby catalog IDs: {', '.join(nearby)}."
                if nearby
                else " Call ModelCatalog().ids() or plural models list to see registered IDs."
            )
            raise ValueError(
                f"Cannot create AgentRewarder {self.name!r}.\n"
                f"model {self.model!r} is not registered in the effective ModelCatalog.{hint}"
            )
        if self.provider is not None and self.provider not in selected.host_providers():
            raise ValueError(
                f"Cannot create AgentRewarder {self.name!r}.\n"
                f"provider {self.provider!r} is not a catalog endpoint for model {self.model!r}."
            )
        unknown = [model for model in self.fallback_models if catalog.get(model) is None]
        if unknown:
            raise ValueError(
                f"Cannot create AgentRewarder {self.name!r}.\n"
                "fallback models are not registered in the effective ModelCatalog: "
                + ", ".join(repr(model) for model in unknown)
            )
        return self

    @classmethod
    def from_catalog(cls, catalog: ModelCatalog, **fields: Any) -> AgentRewarder:
        """Create a model judge against an explicit effective catalog.

        Returns:
            A validated AgentRewarder without global registration.
        """
        return cls.model_validate(fields, context={"catalog": catalog})

    @property
    def routing(self) -> RoutingSpec:
        """Internal routing representation used by the judge harness."""
        return RoutingSpec(provider=self.provider, fallback_models=self.fallback_models)


class HumanRewarder(Rewarder):
    """Human review rewarder."""

    kind: Literal["human"] = "human"
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1)
    instructions: str = ""


RewarderDefinition = Annotated[
    DeterministicRewarder | AgentRewarder | HumanRewarder,
    Field(discriminator="kind"),
]


class WeightedRewarder(FrozenModel):
    """One pinned Rewarder revision and aggregate weight."""

    rewarder: RewarderDefinition
    weight: float = Field(default=1, gt=0)


__all__ = [
    "AgentRewarder",
    "AppSnapshot",
    "DeterministicRewarder",
    "Episode",
    "EpisodeUsage",
    "HumanRewarder",
    "RubricCriterion",
    "Step",
    "StepTask",
    "Rewarder",
    "RewarderDefinition",
    "RewarderOutput",
    "RewarderRuntime",
    "WeightedRewarder",
    "coerce_rewarder_output",
]
