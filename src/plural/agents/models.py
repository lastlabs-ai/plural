"""First-class schema-v2 Agent definitions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    Field,
    SerializerFunctionWrapHandler,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)

from plural._deprecation import renamed_attribute, renamed_keys
from plural.catalog import ModelCatalog
from plural.common import (
    FrozenModel,
    HarnessBinding,
    HarnessPackage,
    RoutingSpec,
    content_hash,
    semantic_version,
    stable_id,
    without_unset_title,
)
from plural.external.protocol import check_agent_url
from plural.harness.models import Harness, HarnessDefinition
from plural.identity import revision_hash

AuthMode = Literal["environment", "api_key", "oauth", "none"]

AGENT_RENAMES = {
    "harness_kwargs": "harness_config",
    "auth_mode": "auth",
    "secret_names": "secrets",
}
"""Old Agent field names, accepted on input for one release, and their new names."""


@lru_cache(maxsize=1)
def _bundled_catalog() -> ModelCatalog:
    return ModelCatalog()


def _check_auth(auth: str, secrets: tuple[str, ...]) -> None:
    if auth == "api_key" and not secrets:
        raise ValueError("auth='api_key' requires the secret's name in secrets")
    if auth == "none" and secrets:
        raise ValueError("auth='none' cannot grant secrets")


class AgentCredential(FrozenModel):
    """A credential this Agent supplies to the Apps it works with.

    The value, such as the Salesforce token of the user this Agent acts as, is
    never part of the Agent: each person who runs it saves their own with
    ``plural credential set`` or exports it, and it reaches only the App host.
    ``scopes`` records what the token may do, as you describe it; the system
    that issued the token enforces them, and every Trial records them for audit.
    """

    scopes: tuple[str, ...] = ()
    description: str = ""


def _credential_map(value: Any) -> Any:
    """Accept a list of names, or of ``{name, scopes}``, as well as a mapping.

    Returns:
        Name to credential settings.
    """
    if isinstance(value, (list, tuple)):
        out: dict[str, Any] = {}
        for item in value:
            if isinstance(item, str):
                out[item] = {}
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                out[item["name"]] = {key: v for key, v in item.items() if key != "name"}
            else:
                raise ValueError("each credential is a name or {name, scopes}")
        return out
    if isinstance(value, dict):
        return {key: {} if item is None else item for key, item in value.items()}
    return value


def _credential_names(value: dict[str, AgentCredential]) -> dict[str, AgentCredential]:
    from pydantic import ValidationError

    from plural.apps.definition import SecretReference

    for name in value:
        try:
            SecretReference(name=name)
        except ValidationError:
            raise ValueError(
                f"{name!r} is not a usable credential name. Use upper-case letters, digits, "
                "and underscores, such as SALESFORCE_TOKEN, matching the App's credentials."
            ) from None
    return dict(sorted(value.items()))


class ExternalAgent(FrozenModel):
    """An agent that already runs as a service of its own.

    A Job calls ``url`` with a signed request for each episode. The agent acts
    only through that episode's actions and files, and its code is not part of
    any content hash: ``version`` is the label you give each release.
    """

    url: str
    """Where the Job sends each signed episode start, over https."""
    signing_key: str
    """The name of the secret holding the key both sides sign with. Never the key."""
    version: str = ""
    """A label for the agent's release, such as 2026.10.3."""
    ca_bundle: str | None = None
    """A PEM file of the certificate authority that signed the agent's certificate,
    for a service inside your own network."""

    @field_validator("url")
    @classmethod
    def _safe_url(cls, value: str) -> str:
        return check_agent_url(value)

    @field_validator("signing_key")
    @classmethod
    def _secret_name(cls, value: str) -> str:
        from plural.apps.definition import SecretReference

        return SecretReference(name=value).name


class Agent(FrozenModel):
    """A catalog-backed model and its optional execution harness.

    To evaluate your own agent or model server instead, give ``endpoint``: the
    base URL of an OpenAI-compatible API (one that serves
    ``/chat/completions``). ``model`` is then sent to it as is and need not be
    in the catalog, and ``endpoint_key`` names the secret holding its API key.
    Plural's native Harness calls it with the Environment's actions as tools,
    and a custom Harness reaches it through ``agent.complete``.

    An agent that already runs elsewhere is an ``external`` Agent instead: the
    Job calls it over signed HTTPS, and ``model`` is the label it reports.

    ``title`` is only the display name in the hosted project; Jobs and results
    call the Agent by ``name``.
    """

    model: str = Field(min_length=1)
    name: str = ""
    title: str | None = Field(
        default=None,
        min_length=1,
        description="Display name in the hosted project. Defaults to name.",
    )
    version: str = "0.1.0"
    provider: str | None = None
    instructions: str = ""
    fallback_models: tuple[str, ...] = ()
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    harness: HarnessDefinition | Harness | str | None = None
    harness_config: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("harness_config", "harness_kwargs"),
        description=(
            "Options for the Agent's Harness. A built-in Harness validates them; a custom "
            "one reads them in self.config, over its own config."
        ),
    )
    auth: AuthMode = Field(
        default="environment",
        validation_alias=AliasChoices("auth", "auth_mode"),
        description="How the Harness authenticates to the model; none when it calls no model.",
    )
    secrets: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices("secrets", "secret_names"),
        description="Names of the Harness's declared secrets this Agent grants it.",
    )
    endpoint: str | None = None
    endpoint_key: str | None = None
    external: ExternalAgent | None = None
    credentials: dict[str, AgentCredential] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _credential_map = field_validator("credentials", mode="before")(_credential_map)
    _credential_names = field_validator("credentials")(_credential_names)

    harness_kwargs = renamed_attribute("harness_kwargs", "harness_config")
    auth_mode = renamed_attribute("auth_mode", "auth")
    secret_names = renamed_attribute("secret_names", "secrets")

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> Any:
        return without_unset_title(handler(self))

    @model_validator(mode="before")
    @classmethod
    def _renamed_fields(cls, value: Any) -> Any:
        return renamed_keys(value, AGENT_RENAMES, "Agent")

    @model_validator(mode="before")
    @classmethod
    def _external_ca_bundle(cls, value: Any, info: ValidationInfo) -> Any:
        context = info.context if isinstance(info.context, dict) else {}
        root = context.get("root")
        external = value.get("external") if isinstance(value, dict) else None
        if not isinstance(external, dict) or not isinstance(root, Path):
            return value
        bundle = external.get("ca_bundle")
        if isinstance(bundle, str) and not Path(bundle).is_absolute():
            value = {**value, "external": {**external, "ca_bundle": str(root / bundle)}}
        return value

    @model_validator(mode="after")
    def _validate_public_agent(self, info: ValidationInfo) -> Agent:
        context = info.context if isinstance(info.context, dict) else {}
        catalog = context.get("catalog") or _bundled_catalog()
        if not isinstance(catalog, ModelCatalog):
            raise TypeError("catalog validation context must be a ModelCatalog")
        if self.external is not None:
            self._validate_external_agent()
            return self
        if self.endpoint is not None or self.endpoint_key is not None:
            self._validate_endpoint_agent()
            if self.harness is not None:
                self._check_custom_harness()
            return self
        selected = catalog.get(self.model)
        if selected is None:
            nearby = catalog.suggest(self.model)
            hint = f" Did you mean {', '.join(nearby)}?" if nearby else ""
            raise ValueError(
                f"Unknown model {self.model!r}.{hint} `plural model list` shows every "
                "model id; a model of your own is registered with CatalogContext."
            )
        if self.provider is not None and self.provider not in selected.host_providers():
            raise ValueError(
                f"provider {self.provider!r} is not a catalog endpoint for model {self.model!r}"
            )
        unknown_fallbacks = [model for model in self.fallback_models if catalog.get(model) is None]
        if unknown_fallbacks:
            raise ValueError(
                "unknown fallback models: " + ", ".join(repr(model) for model in unknown_fallbacks)
            )
        semantic_version(self.version)
        if not self.name:
            object.__setattr__(self, "name", self.model.rsplit("/", 1)[-1])
        _check_auth(self.auth, self.secrets)
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
                "harness_config",
                normalize_kwargs(self.harness, self.harness_config, root=root_path),
            )
            undeclared = sorted(set(self.secrets) - set(spec.secret_names))
            if undeclared:
                raise ValueError(
                    f"Agent secrets are not declared by Harness {self.harness!r}: {undeclared!r}"
                )
        elif self.harness is not None:
            self._check_custom_harness()
        elif self.harness_config:
            raise ValueError(
                "harness_config sets options of this Agent's Harness, and the native Harness "
                "takes none. Name a Harness with `harness:`, or remove harness_config."
            )
        return self

    def _check_custom_harness(self) -> None:
        assert self.harness is not None and not isinstance(self.harness, str)
        package = self.harness._package()
        undeclared = sorted(set(self.secrets) - set(package.definition.secret_names))
        if undeclared:
            raise ValueError(
                f"Agent secrets are not declared by Harness {package.definition.name!r}: "
                f"{undeclared!r}"
            )

    def _validate_external_agent(self) -> None:
        name = self.name or self.model
        unsupported = [
            label
            for label, given in (
                ("harness", self.harness is not None),
                ("harness_config", bool(self.harness_config)),
                ("endpoint", self.endpoint is not None or self.endpoint_key is not None),
                ("provider", self.provider is not None),
                ("fallback_models", bool(self.fallback_models)),
                ("temperature", self.temperature is not None),
                ("max_tokens", self.max_tokens is not None),
                ("secrets", bool(self.secrets)),
            )
            if given
        ]
        if unsupported:
            raise ValueError(
                f"Cannot create Agent {name!r}.\n"
                "An external Agent runs as its own service, so Plural cannot honor "
                f"{', '.join(unsupported)}. Remove them; the service decides those itself."
            )
        semantic_version(self.version)
        if not self.name:
            object.__setattr__(self, "name", self.model.rsplit("/", 1)[-1])

    def _validate_endpoint_agent(self) -> None:
        name = self.name or self.model
        if not self.endpoint or not self.endpoint.startswith(("http://", "https://")):
            raise ValueError(
                f"Cannot create Agent {name!r}.\n"
                "endpoint must be the http(s) base URL of an OpenAI-compatible API, "
                "such as https://agent.example.com/v1."
            )
        if isinstance(self.harness, str):
            raise ValueError(
                f"Cannot create Agent {name!r}.\n"
                f"Built-in Harness {self.harness!r} calls models through the Plural gateway, "
                "so it cannot use an endpoint. Use Plural's native Harness or a custom one."
            )
        unsupported = [
            label
            for label, given in (
                ("provider", self.provider is not None),
                ("fallback_models", bool(self.fallback_models)),
                ("secrets", bool(self.secrets) and self.harness is None),
            )
            if given
        ]
        if unsupported:
            raise ValueError(
                f"Cannot create Agent {name!r}.\n"
                f"An endpoint Agent takes no {', '.join(unsupported)}. Put its API key's "
                "name in endpoint_key."
            )
        if self.endpoint_key is not None:
            from plural.apps.definition import SecretReference

            SecretReference(name=self.endpoint_key)
        semantic_version(self.version)
        if not self.name:
            object.__setattr__(self, "name", self.model.rsplit("/", 1)[-1])

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

            return resolve_builtin_package(self.harness, self.harness_config)
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
            harness_config=self.harness_config,
            auth=self.auth,
            secrets=self.secrets,
            endpoint=self.endpoint,
            endpoint_key=self.endpoint_key,
            external=self.external,
            credentials=self.credentials,
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
    harness_config: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("harness_config", "harness_kwargs"),
    )
    auth: AuthMode = Field(
        default="environment", validation_alias=AliasChoices("auth", "auth_mode")
    )
    secrets: tuple[str, ...] = Field(
        default=(), validation_alias=AliasChoices("secrets", "secret_names")
    )
    endpoint: str | None = None
    """An OpenAI-compatible base URL the native Harness calls instead of the gateway."""
    endpoint_key: str | None = None
    """The secret holding ``endpoint``'s API key."""
    external: ExternalAgent | None = None
    """The service a Job calls for each episode, for an Agent that runs elsewhere."""
    credentials: dict[str, AgentCredential] = Field(default_factory=dict)
    """The credentials this Agent supplies to Apps, by name. Never their values."""
    metadata: dict[str, Any] = Field(default_factory=dict)

    _credential_map = field_validator("credentials", mode="before")(_credential_map)
    _credential_names = field_validator("credentials")(_credential_names)

    harness_kwargs = renamed_attribute("harness_kwargs", "harness_config")
    auth_mode = renamed_attribute("auth_mode", "auth")
    secret_names = renamed_attribute("secret_names", "secrets")

    @model_validator(mode="before")
    @classmethod
    def _renamed_fields(cls, value: Any) -> Any:
        return renamed_keys(value, AGENT_RENAMES, "AgentDefinition")

    @model_validator(mode="after")
    def _package_matches_binding(self) -> AgentDefinition:
        if self.harness is None and self.harness_package is not None:
            raise ValueError("harness_package requires a harness binding")
        if self.external is not None and (self.harness is not None or self.endpoint is not None):
            raise ValueError("an external Agent has no harness or endpoint")
        if (
            self.harness is not None
            and self.harness_package is not None
            and HarnessBinding.from_package(self.harness_package) != self.harness
        ):
            raise ValueError("harness_package does not match the exact harness binding")
        _check_auth(self.auth, self.secrets)
        return self

    @property
    def content_hash(self) -> str:
        """Stable Agent revision digest, independent of where the Harness is stored."""
        payload = self.model_dump(mode="json", exclude={"harness", "harness_package"})
        # Renamed fields hash under their original names, so Agents keep their identity.
        for old, new in AGENT_RENAMES.items():
            payload[old] = payload.pop(new)
        if not self.credentials:
            # Agents with no credentials keep the identity they had before credentials.
            del payload["credentials"]
        if self.external is None:
            del payload["external"]
        else:
            # Where the key lives, and which CA signed the service, don't change the agent.
            payload["external"] = {
                "url": self.external.url,
                "version": self.external.version,
            }
        if self.harness_package is not None:
            payload["harness"] = self.harness_package.content_hash
        else:
            payload["harness"] = self.harness.digest if self.harness is not None else None
        return revision_hash("agent", payload)

    @property
    def agent_id(self) -> str:
        """Stable Job participant identifier.

        The content hash leaves the name out, so two identically configured
        Agents under different names would share it; a Job still needs to tell
        them apart.
        """
        return stable_id("agt", {"name": self.name, "content_hash": self.content_hash})


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
    def harness_config(self) -> dict[str, Any]:
        """Normalized built-in Harness options."""
        return self.agent.harness_config

    @property
    def auth(self) -> str:
        """Authentication mode."""
        return self.agent.auth

    @property
    def secrets(self) -> tuple[str, ...]:
        """Secret references granted to the harness."""
        return self.agent.secrets

    harness_kwargs = renamed_attribute("harness_kwargs", "harness_config")
    auth_mode = renamed_attribute("auth_mode", "auth")
    secret_names = renamed_attribute("secret_names", "secrets")

    @property
    def external(self) -> ExternalAgent | None:
        """The service this Agent runs as, when it runs elsewhere."""
        return self.agent.external

    @property
    def content_hash(self) -> str:
        """Stable binding digest."""
        return content_hash(self)


__all__ = [
    "Agent",
    "AgentBinding",
    "AgentCredential",
    "AgentDefinition",
    "ExternalAgent",
    "RoutingSpec",
]
