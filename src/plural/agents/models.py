"""First-class schema-v2 Agent definitions."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, ValidationInfo, model_validator

from plural.catalog import ModelCatalog
from plural.common import (
    FrozenModel,
    HarnessBinding,
    HarnessPackage,
    RoutingSpec,
    content_hash,
    semantic_version,
    stable_id,
)
from plural.harness.models import Harness


@lru_cache(maxsize=1)
def _bundled_catalog() -> ModelCatalog:
    return ModelCatalog()


class Agent(FrozenModel):
    """A catalog-backed model and its optional execution harness."""

    model: str = Field(min_length=1)
    name: str = ""
    version: str = "0.1.0"
    provider: str | None = None
    instructions: str = ""
    fallback_models: tuple[str, ...] = ()
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    harness: Harness | None = None
    auth_mode: Literal["environment", "api_key", "oauth", "none"] = "environment"
    secret_names: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_public_agent(self, info: ValidationInfo) -> Agent:
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
        unknown_fallbacks = [model for model in self.fallback_models if catalog.get(model) is None]
        if unknown_fallbacks:
            raise ValueError(
                "fallback models are not registered in the effective ModelCatalog: "
                + ", ".join(repr(model) for model in unknown_fallbacks)
            )
        semantic_version(self.version)
        if not self.name:
            object.__setattr__(self, "name", self.model.rsplit("/", 1)[-1])
        if self.auth_mode == "api_key" and not self.secret_names:
            raise ValueError("api_key auth_mode requires a secret name")
        if self.auth_mode == "none" and self.secret_names:
            raise ValueError("none auth_mode cannot declare secrets")
        if self.harness is not None:
            undeclared = sorted(set(self.secret_names) - set(self.harness.secrets))
            if undeclared:
                raise ValueError(
                    f"Agent secret_names are not declared by Harness {self.harness.name!r}: "
                    f"{undeclared!r}"
                )
        return self

    @classmethod
    def from_catalog(cls, catalog: ModelCatalog, **fields: Any) -> Agent:
        """Create an Agent against an explicit effective catalog.

        Returns:
            A validated Agent without changing process-global state.
        """
        return cls.model_validate(fields, context={"catalog": catalog})

    @property
    def routing(self) -> RoutingSpec:
        """Internal routing representation used by the execution engine."""
        return RoutingSpec(
            provider=self.provider,
            fallback_models=self.fallback_models,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    @property
    def harness_binding(self) -> HarnessBinding | None:
        """Internal content-addressed binding derived from ``harness``."""
        return HarnessBinding.from_package(self.harness._package()) if self.harness else None

    @property
    def content_hash(self) -> str:
        """Stable Agent version digest."""
        return content_hash(self)

    @property
    def agent_id(self) -> str:
        """Stable Agent identifier."""
        return stable_id("agt", self)

    def _definition(self) -> AgentDefinition:
        """Compile this Agent into the current execution contract.

        Returns:
            The internal immutable execution definition.
        """
        harness_package = self.harness._package() if self.harness else None
        return AgentDefinition(
            name=self.name,
            revision=self.version,
            model=self.model,
            instructions=self.instructions,
            routing=self.routing,
            harness=(HarnessBinding.from_package(harness_package) if harness_package else None),
            harness_package=harness_package,
            auth_mode=self.auth_mode,
            secret_names=self.secret_names,
            metadata=self.metadata,
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


__all__ = ["Agent", "AgentBinding", "AgentDefinition", "RoutingSpec"]
