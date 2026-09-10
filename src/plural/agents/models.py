"""First-class schema-v2 Agent definitions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from plural.common import (
    FrozenModel,
    HarnessBinding,
    HarnessPackage,
    RoutingSpec,
    content_hash,
    stable_id,
)


class AgentDefinition(FrozenModel):
    """Revisioned Agent independent of any Environment."""

    schema_version: Literal["2"] = "2"
    name: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    model: str = Field(min_length=1)
    instructions: str = ""
    routing: RoutingSpec = Field(default_factory=RoutingSpec)
    harness: HarnessBinding | None = None
    harness_package: HarnessPackage | None = None
    auth_mode: Literal["environment", "api_key", "oauth", "none"] = "environment"
    secret_names: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _package_matches_binding(self) -> AgentDefinition:
        if self.harness is None and self.harness_package is not None:
            raise ValueError("harness_package requires a harness binding")
        if (
            self.harness is not None
            and self.harness_package is not None
            and HarnessBinding.from_package(self.harness_package) != self.harness
        ):
            raise ValueError("harness_package does not match the exact harness binding")
        if self.auth_mode == "api_key" and not self.secret_names:
            raise ValueError("api_key auth_mode requires a secret name")
        if self.auth_mode == "none" and self.secret_names:
            raise ValueError("none auth_mode cannot declare secrets")
        return self

    @property
    def content_hash(self) -> str:
        """Stable Agent revision digest."""
        return content_hash(self)

    @property
    def agent_id(self) -> str:
        """Stable Agent revision identifier."""
        return stable_id("agt", self)


class AgentBinding(FrozenModel):
    """A Job participant."""

    agent: AgentDefinition

    @property
    def agent_id(self) -> str:
        """Planning identity."""
        return self.agent.agent_id

    @property
    def name(self) -> str:
        """Display name."""
        return self.agent.name

    @property
    def model(self) -> str:
        """Model id."""
        return self.agent.model

    @property
    def routing(self) -> RoutingSpec:
        """Routing policy."""
        return self.agent.routing

    @property
    def harness(self) -> HarnessBinding | None:
        """Optional harness binding."""
        return self.agent.harness

    @property
    def harness_package(self) -> HarnessPackage | None:
        """Optional executable package."""
        return self.agent.harness_package

    @property
    def auth_mode(self) -> str:
        """Authentication mode."""
        return self.agent.auth_mode

    @property
    def secret_names(self) -> tuple[str, ...]:
        """Secret references granted to the harness."""
        return self.agent.secret_names

    @property
    def content_hash(self) -> str:
        """Stable binding digest."""
        return content_hash(self)


__all__ = ["AgentBinding", "AgentDefinition", "RoutingSpec"]
