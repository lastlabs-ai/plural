"""First-class schema-v2 Agent definitions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
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
    harness: Harness | str | None = None
    harness_kwargs: dict[str, Any] = Field(default_factory=dict)
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
            nearby = catalog.suggest(self.model)
            hint = f" Nearby catalog IDs: {', '.join(nearby)}." if nearby else ""
            raise ValueError(
                f"Cannot create Agent {self.name or self.model!r}.\n"
                f"model {self.model!r} is not registered in the effective ModelCatalog.{hint}\n"
                "Use a bundled catalog ID or register the model with CatalogContext."
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
        root = context.get("root")
        root_path = root if isinstance(root, Path) else Path.cwd()
        if isinstance(self.harness, str):
            from plural.harness.builtins import (
                get_builtin,
                model_supported,
                normalize_kwargs,
            )

            spec = get_builtin(self.harness)
            if not model_supported(self.model, spec.supported_models):
                allowed = ", ".join(spec.supported_models)
                raise ValueError(
                    f"Cannot attach Harness {self.harness!r} to model {self.model!r}.\n"
                    f"This built-in accepts: {allowed}."
                )
            object.__setattr__(
                self,
                "harness_kwargs",
                normalize_kwargs(self.harness, self.harness_kwargs, root=root_path),
            )
            undeclared = sorted(set(self.secret_names) - set(spec.secret_names))
            if undeclared:
                raise ValueError(
                    f"Agent secret_names are not declared by Harness {self.harness!r}: "
                    f"{undeclared!r}"
                )
        elif self.harness is not None:
            if self.harness_kwargs:
                raise ValueError(
                    "harness_kwargs is only valid with a built-in Harness name such as "
                    "'claude-code', 'codex', or 'hermes'"
                )
            package = self.harness._package()
            undeclared = sorted(set(self.secret_names) - set(package.definition.secret_names))
            if undeclared:
                raise ValueError(
                    "Agent secret_names are not declared by Harness "
                    f"{package.definition.name!r}: "
                    f"{undeclared!r}"
                )
        elif self.harness_kwargs:
            raise ValueError(
                "harness_kwargs requires harness to be a built-in name such as "
                "'claude-code', 'codex', or 'hermes'"
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

    def _resolved_package(self) -> HarnessPackage | None:
        """Return the executable package for a custom or built-in Harness."""
        if isinstance(self.harness, str):
            from plural.harness.builtins import resolve_builtin_package

            return resolve_builtin_package(self.harness, self.harness_kwargs)
        return self.harness._package() if self.harness is not None else None

    @property
    def harness_binding(self) -> HarnessBinding | None:
        """Internal content-addressed binding derived from ``harness``."""
        package = self._resolved_package()
        return HarnessBinding.from_package(package) if package is not None else None

    @property
    def content_hash(self) -> str:
        """Stable Agent version digest."""
        return self._definition().content_hash

    @property
    def agent_id(self) -> str:
        """Stable Agent identifier."""
        return self._definition().agent_id

    def _definition(self) -> AgentDefinition:
        """Compile this Agent into the current execution contract.

        Returns:
            The internal immutable execution definition.
        """
        harness_package = self._resolved_package()
        return AgentDefinition(
            name=self.name,
            revision=self.version,
            model=self.model,
            instructions=self.instructions,
            routing=self.routing,
            harness=(HarnessBinding.from_package(harness_package) if harness_package else None),
            harness_package=harness_package,
            harness_kwargs=self.harness_kwargs,
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
    harness_kwargs: dict[str, Any] = Field(default_factory=dict)
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
    def harness_kwargs(self) -> dict[str, Any]:
        """Normalized built-in Harness options."""
        return self.agent.harness_kwargs

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
