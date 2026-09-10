"""First-class schema-v2 Verifier definitions."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from plural.common import FrozenModel, RoutingSpec, content_hash
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


class DeterministicVerifier(FrozenModel):
    """Deterministic command verifier."""

    schema_version: Literal["2"] = "2"
    kind: Literal["deterministic"] = "deterministic"
    name: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    command: tuple[str, ...] = Field(min_length=1)
    runtime: VerifierRuntime = Field(default_factory=VerifierRuntime)
    required_artifacts: tuple[str, ...] = ()
    result_path: str = "verifier-result.json"
    evidence_required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Stable Verifier revision digest."""
        return content_hash(self)


class AgentVerifier(FrozenModel):
    """Model-judge verifier with its own runtime and connectivity policy."""

    schema_version: Literal["2"] = "2"
    kind: Literal["agent"] = "agent"
    name: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    model: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    routing: RoutingSpec = Field(default_factory=lambda: RoutingSpec())
    rubric: tuple[RubricCriterion, ...] = Field(min_length=1)
    runtime: VerifierRuntime = Field(
        default_factory=lambda: VerifierRuntime(network=NetworkMode.FULL)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Stable Verifier revision digest."""
        return content_hash(self)


class HumanVerifier(FrozenModel):
    """Human review verifier."""

    schema_version: Literal["2"] = "2"
    kind: Literal["human"] = "human"
    name: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    rubric: tuple[RubricCriterion, ...] = Field(min_length=1)
    instructions: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Stable Verifier revision digest."""
        return content_hash(self)


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
    "HumanVerifier",
    "RubricCriterion",
    "VerifierDefinition",
    "VerifierRuntime",
    "WeightedVerifier",
]
