"""First-class Verifier definitions."""

from __future__ import annotations

import inspect
import math
import shlex
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationInfo, field_serializer, model_validator

from plural.catalog import ModelCatalog
from plural.common import FrozenModel, RoutingSpec, content_hash
from plural.sandbox.models import NetworkMode, ResourceRequirements


class VerifierRuntime(FrozenModel):
    """Verifier-owned runtime, independent of the Environment."""

    provider: str = Field(default="docker", min_length=1)
    image: str | None = None
    network: NetworkMode = NetworkMode.PUBLIC
    network_allowlist: tuple[str, ...] = ()
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    timeout_seconds: float = Field(default=60, gt=0)

    @model_validator(mode="after")
    def _network(self) -> VerifierRuntime:
        if self.network_allowlist and self.network is not NetworkMode.ALLOWLIST:
            raise ValueError(
                "Cannot create VerifierRuntime.\n"
                f"allowed_hosts is set but network={self.network.value!r}.\n"
                "Set network='allowlist' or remove allowed_hosts."
            )
        return self


class EpisodeUsage(FrozenModel):
    """Token, turn, and cost totals captured for one completed episode."""

    turns: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


class Episode(FrozenModel):
    """Completed Agent episode handed to a Verifier.

    ``state`` is the full internal Environment snapshot. It is never shown to
    the Agent. ``observation`` is what the Agent last saw.
    """

    observation: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    trajectory: list[Any] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    usage: EpisodeUsage = Field(default_factory=EpisodeUsage)


class VerifierOutput(FrozenModel):
    """Score returned by a Verifier function or command."""

    reward: float
    scores: dict[str, float] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    feedback: str = ""

    def validated_finite(self) -> VerifierOutput:
        """Reject non-finite scores.

        Returns:
            This output when all scores are finite.
        """
        if any(not math.isfinite(item) for item in (self.reward, *self.scores.values())):
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


@lru_cache(maxsize=1)
def _bundled_catalog() -> ModelCatalog:
    return ModelCatalog()


def coerce_verifier_output(value: Any, *, verifier_name: str) -> VerifierOutput:
    """Accept a VerifierOutput, mapping, or object with the same fields.

    Returns:
        A validated VerifierOutput.
    """
    if isinstance(value, VerifierOutput):
        return value
    if isinstance(value, Mapping):
        try:
            return VerifierOutput.model_validate(value)
        except Exception as exc:
            raise ValueError(
                f"Verifier {verifier_name!r} returned an invalid result.\n"
                "Return VerifierOutput or a mapping with a finite 'reward' and optional "
                "'scores', 'evidence', and 'feedback'.\n"
                f"Got: {value!r}\n"
                f"Cause: {exc}"
            ) from exc
    raise ValueError(
        f"Verifier {verifier_name!r} must return VerifierOutput or a mapping.\n"
        f"Got {type(value).__name__}."
    )


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
        """Stable Verifier version digest."""
        return content_hash(self._hash_payload())


class DeterministicVerifier(Verifier):
    """Function or command that scores a completed Episode."""

    kind: Literal["deterministic"] = "deterministic"
    check: Any
    runtime: VerifierRuntime = Field(default_factory=VerifierRuntime)
    result_path: str = "verifier-result.json"
    evidence_required: bool = True

    @model_validator(mode="before")
    @classmethod
    def _normalize_check(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "check" not in payload and "command" in payload:
            payload["check"] = payload.pop("command")
        check = payload.get("check")
        if isinstance(check, str):
            payload["check"] = tuple(shlex.split(check))
        elif isinstance(check, list):
            payload["check"] = tuple(str(item) for item in check)
        payload.pop("required_artifacts", None)
        payload.pop("evidence", None)
        return payload

    @model_validator(mode="after")
    def _valid_check(self) -> DeterministicVerifier:
        check = self.check
        if callable(check):
            if not _accepts_episode(check):
                raise ValueError(
                    f"Cannot create DeterministicVerifier {self.name!r}.\n"
                    "check must be a function that accepts an Episode "
                    "(observation, state, trajectory, artifacts, usage).\n"
                    f"Got {check!r} with no Episode parameter.\n"
                    "Define it like:\n"
                    "  def solved(episode: Episode) -> VerifierOutput: ...\n"
                    "  DeterministicVerifier(name='solved', check=solved)"
                )
            return self
        if isinstance(check, dict) and check.get("python"):
            return self
        if isinstance(check, tuple) and check and all(isinstance(item, str) for item in check):
            return self
        raise ValueError(
            f"Cannot create DeterministicVerifier {self.name!r}.\n"
            "check must be a function that accepts an Episode, a "
            "{'python': 'verify.py:solved'} reference, or a command argv.\n"
            f"Got {type(check).__name__}: {check!r}."
        )

    @field_serializer("check")
    def _serialize_check(self, check: Any) -> Any:
        if callable(check):
            source = inspect.getsourcefile(check)
            qualname = getattr(check, "__qualname__", getattr(check, "__name__", "check"))
            return {"python": f"{Path(source).name}:{qualname}" if source else qualname}
        if isinstance(check, tuple):
            return list(check)
        return check

    @property
    def command(self) -> tuple[str, ...]:
        """Command consumed by sandboxed execution, if this check is argv."""
        check = self.check
        if isinstance(check, tuple) and check and all(isinstance(item, str) for item in check):
            return check
        return ()

    @property
    def python_ref(self) -> str | None:
        """Serialized ``path.py:object`` reference, if present."""
        check = self.check
        if isinstance(check, dict):
            value = check.get("python")
            return str(value) if value else None
        return None

    @property
    def checker(self) -> Callable[[Episode], Any] | None:
        """In-process Episode function, if this check is a callable."""
        check = self.check
        return check if callable(check) else None

    def _hash_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude={"check"})
        check = self.check
        if callable(check):
            source = inspect.getsourcefile(check)
            qualname = getattr(check, "__qualname__", getattr(check, "__name__", "check"))
            payload["check"] = {"python": f"{Path(source).name}:{qualname}" if source else qualname}
        elif isinstance(check, tuple):
            payload["check"] = list(check)
        else:
            payload["check"] = check
        return payload

    def invoke(self, episode: Episode) -> VerifierOutput:
        """Run an in-process Episode function.

        Returns:
            A validated VerifierOutput.
        """
        fn = self.checker
        if fn is None:
            raise ValueError(
                f"Verifier {self.name!r} cannot be invoked in-process.\n"
                "Its check is a command or Python reference that has not been resolved."
            )
        try:
            return coerce_verifier_output(fn(episode), verifier_name=self.name)
        except TypeError as exc:
            raise ValueError(
                f"Verifier {self.name!r} check failed to accept the Episode.\n"
                "The function must accept one argument: the completed Episode.\n"
                f"Cause: {exc}"
            ) from exc


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
            hint = (
                f" Nearby catalog IDs: {', '.join(nearby)}."
                if nearby
                else " Call ModelCatalog().ids() or plural models list to see registered IDs."
            )
            raise ValueError(
                f"Cannot create AgentVerifier {self.name!r}.\n"
                f"model {self.model!r} is not registered in the effective ModelCatalog.{hint}"
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
                "fallback models are not registered in the effective ModelCatalog: "
                + ", ".join(repr(model) for model in unknown)
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
    "DeterministicVerifier",
    "Episode",
    "EpisodeUsage",
    "HumanVerifier",
    "RubricCriterion",
    "Verifier",
    "VerifierDefinition",
    "VerifierOutput",
    "VerifierRuntime",
    "WeightedVerifier",
    "coerce_verifier_output",
]
