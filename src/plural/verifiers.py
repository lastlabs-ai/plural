"""First-class schema-v2 Verifier definitions."""

from __future__ import annotations

import shlex
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationInfo, model_validator

from plural.catalog import ModelCatalog
from plural.common import FrozenModel, RoutingSpec, content_hash
from plural.evidence import EvidenceContract
from plural.sandbox.models import NetworkMode, ResourceRequirements


class VerifierRuntime(FrozenModel):
    """Verifier-owned runtime and connectivity, independent of the Environment."""

    provider: str = Field(default="docker", min_length=1)
    image: str | None = None
    network: NetworkMode = NetworkMode.NONE
    network_allowlist: tuple[str, ...] = ()
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    timeout_seconds: float = Field(default=60, gt=0)

    @model_validator(mode="after")
    def _network(self) -> VerifierRuntime:
        if self.network_allowlist and self.network is not NetworkMode.RESTRICTED:
            raise ValueError("network_allowlist requires network='restricted'")
        return self


class RubricCriterion(FrozenModel):
    """One deterministic human or agent rubric criterion."""

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


class Verifier(FrozenModel):
    """Fields shared by every completed-Trial verifier."""

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    info: Any = None
    criteria: tuple[RubricCriterion, ...] = ()
    evidence: EvidenceContract = Field(default_factory=EvidenceContract)
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

    @property
    def content_hash(self) -> str:
        """Stable Verifier version digest."""
        return content_hash(self)


class DeterministicVerifier(Verifier):
    """Deterministic command verifier."""

    kind: Literal["deterministic"] = "deterministic"
    check: tuple[str, ...] = Field(min_length=1)
    runtime: VerifierRuntime = Field(default_factory=VerifierRuntime)
    result_path: str = "verifier-result.json"
    evidence_required: bool = True

    @model_validator(mode="before")
    @classmethod
    def _normalize_check(cls, value: Any) -> Any:
        if isinstance(value, dict):
            payload = dict(value)
            if "check" not in payload and "command" in payload:
                payload["check"] = payload.pop("command")
            check = payload.get("check")
            if isinstance(check, str):
                payload["check"] = tuple(shlex.split(check))
            elif isinstance(check, list):
                payload["check"] = tuple(str(item) for item in check)
            if "required_artifacts" not in payload:
                return payload
            artifacts = payload.pop("required_artifacts")
            evidence = payload.get("evidence")
            if isinstance(evidence, EvidenceContract):
                if not evidence.artifacts:
                    payload["evidence"] = evidence.model_copy(
                        update={"artifacts": tuple(artifacts)}
                    )
            else:
                merged = dict(evidence or {})
                merged.setdefault("artifacts", artifacts)
                payload["evidence"] = merged
            return payload
        return value

    @property
    def command(self) -> tuple[str, ...]:
        """Normalized command consumed by the execution engine."""
        return self.check

    @property
    def required_artifacts(self) -> tuple[str, ...]:
        """Artifact names the verifier must see."""
        return self.evidence.artifacts


class AgentVerifier(Verifier):
    """Model-judge verifier with its own runtime and connectivity policy."""

    kind: Literal["agent"] = "agent"
    model: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    provider: str | None = None
    fallback_models: tuple[str, ...] = ()
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1)
    runtime: VerifierRuntime = Field(
        default_factory=lambda: VerifierRuntime(network=NetworkMode.FULL)
    )

    @model_validator(mode="after")
    def _catalog_model(self, info: ValidationInfo) -> AgentVerifier:
        context = info.context if isinstance(info.context, dict) else {}
        catalog = context.get("catalog") or _bundled_catalog()
        if not isinstance(catalog, ModelCatalog):
            raise TypeError("catalog validation context must be a ModelCatalog")
        selected = catalog.get(self.model)
        if selected is None:
            raise ValueError(
                f"model {self.model!r} is not registered in the effective ModelCatalog"
            )
        if self.provider is not None and self.provider not in selected.host_providers():
            raise ValueError(
                f"provider {self.provider!r} is not a catalog endpoint for model {self.model!r}"
            )
        unknown = [model for model in self.fallback_models if catalog.get(model) is None]
        if unknown:
            raise ValueError(
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
    "EvidenceContract",
    "HumanVerifier",
    "RubricCriterion",
    "Verifier",
    "VerifierDefinition",
    "VerifierRuntime",
    "WeightedVerifier",
]
