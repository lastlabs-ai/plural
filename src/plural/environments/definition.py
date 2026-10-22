"""Schema-v2 Environment definition, runtime, and policy declarations."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from plural._deprecation import renamed_attribute, renamed_keys
from plural.apps.definition import (
    AppDefinition,
    ExposedAction,
    SecretReference,
    exposed_actions,
)
from plural.common import (
    SHA256_PATTERN,
    ExecutionTarget,
    FrozenModel,
    HarnessBinding,
    HarnessCapability,
    PackageSource,
    semantic_version,
)
from plural.identity import revision_hash
from plural.sandbox.catalog import runtime_provider
from plural.sandbox.models import (
    RUNTIME_RENAMES,
    DeclarativeImage,
    NetworkMode,
    ResourceRequirements,
    SandboxCapability,
    environment_required_capabilities,
    runtime_hash_payload,
)


class EnvironmentIdentity(FrozenModel):
    """Exact Environment revision identity."""

    name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    digest: str

    @field_validator("digest")
    @classmethod
    def _valid_digest(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must be sha256:<64 lowercase hex characters>")
        return value


class Guardrail(FrozenModel):
    """A plain-language Environment rule."""

    name: str = ""
    rule: str = Field(min_length=1)


class EnvironmentResource(FrozenModel):
    """Data or application supplied by an Environment.

    The short form ``Resource("policies/refunds.md")`` stages one file from
    the Environment's source package. The mapping form keeps its explicit
    ``delivery``.
    """

    kind: Literal["data", "application", "file"]
    name: str = Field(min_length=1)
    path: str | None = None
    uri: str | None = None
    digest: str | None = None
    content_type: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    delivery: Literal["descriptor", "source", "inline", "resolver"] = "descriptor"
    content: str | None = Field(default=None, max_length=1_048_576)
    resolver: str | None = None

    def __init__(self, path: str | Mapping[str, Any] | None = None, /, **data: Any) -> None:
        """Build a resource from a package path or a field mapping.

        Args:
            path: A relative file path inside the Environment's source
                package (staged with ``delivery="source"`` by default), or a
                full field mapping.
            data: Field overrides. ``content=`` switches the short form to
                ``delivery="inline"``; ``delivery=`` always wins when given.
        """
        if path is not None:
            fields: dict[str, Any] = dict(path) if isinstance(path, Mapping) else {}
            short_path = None if isinstance(path, Mapping) else str(path)
            if short_path is not None:
                fields.setdefault("path", short_path)
                fields.setdefault("name", short_path)
                fields.setdefault("kind", "file")
                if "content" in data or "content" in fields:
                    fields.setdefault("delivery", "inline")
                else:
                    fields.setdefault("delivery", "source")
            fields.update(data)
            data = fields
        super().__init__(**data)

    @model_validator(mode="after")
    def _resource_delivery(self) -> EnvironmentResource:
        if self.delivery == "descriptor":
            if self.content is not None or self.resolver is not None:
                raise ValueError("Choose inline or resolver delivery for resource content")
            return self
        path = self.path or ""
        if (
            not path
            or "\\" in path
            or path.startswith("/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or PurePosixPath(path).is_absolute()
        ):
            raise ValueError("Resource path must be a safe relative file path")
        if self.delivery == "inline":
            if self.content is None:
                raise ValueError("Inline resources require text content")
            digest = "sha256:" + hashlib.sha256(self.content.encode()).hexdigest()
            if self.digest is not None and self.digest != digest:
                raise ValueError("Resource content does not match its digest")
            object.__setattr__(self, "digest", digest)
        elif self.content is not None:
            raise ValueError("Only inline resources can contain text")
        if self.delivery == "resolver":
            if not self.resolver or not self.uri or not self.digest:
                raise ValueError("Resolved resources require a resolver, URI, and expected digest")
        elif self.resolver is not None:
            raise ValueError("Only resolver resources can name a resolver")
        if self.digest is not None and SHA256_PATTERN.fullmatch(self.digest) is None:
            raise ValueError("Resource digest must be sha256:<64 lowercase hex characters>")
        return self


class RuntimeVariable(FrozenModel):
    """A launch-time variable declaration. Values are supplied to Job, never saved here."""

    name: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    description: str = ""
    required: bool = True
    secret: bool = False
    format: Literal["text", "url", "integer", "json"] = "text"

    @field_validator("name")
    @classmethod
    def _application_name(cls, value: str) -> str:
        if value in {
            "PATH",
            "HOME",
            "PYTHONPATH",
            "PYTHONHOME",
            "LD_PRELOAD",
            "PLURAL_RESOURCES_DIR",
        } or value.startswith(("DYLD_", "PLURAL_")):
            raise ValueError("Runtime variables cannot replace execution or resource controls")
        return value


_REQUIREMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._,\s-]*\])?(\s*[@<>=!~;(].*)?$"
)


class RuntimePackages(FrozenModel):
    """Packages installed in the Runtime before an episode, by package manager.

    Each list holds what you would pass to that manager, one package per entry.
    """

    python: tuple[str, ...] = ()
    """Python requirements, such as ``duckdb>=1.1`` or ``snowflake-connector-python``."""

    @field_validator("python")
    @classmethod
    def _python_requirements(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for item in value:
            text = item.strip()
            if not _REQUIREMENT.match(text) or "\n" in text:
                raise ValueError(
                    f"{item!r} is not a Python requirement. Give one package per entry, "
                    "such as duckdb or duckdb>=1.1, with no pip options."
                )
            if text not in cleaned:
                cleaned.append(text)
        return tuple(cleaned)

    def __bool__(self) -> bool:
        return bool(self.python)


class EnvironmentRuntime(FrozenModel):
    """Where an Environment runs: Docker, a trusted local process, or a remote sandbox."""

    provider: str = Field(default="docker", min_length=1)
    ref: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9-]{0,79}$",
        description="Slug of the project Runtime this configuration was copied from. "
        "The machine fields hold that Runtime's settings as of the copy; credentials "
        "come from the project Runtime when a Job starts.",
    )
    placement: dict[str, str] = Field(default_factory=dict)
    variables: tuple[RuntimeVariable, ...] = ()
    image: str | None = None
    snapshot: str | None = None
    declarative_image: DeclarativeImage | None = None
    build_context: str | None = None
    dockerfile: str | None = None
    network: NetworkMode = NetworkMode.PUBLIC
    allowed_hosts: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices("allowed_hosts", "network_allowlist"),
        description="Hosts the Runtime may reach when network is 'allowlist'.",
    )
    compute: ResourceRequirements = Field(
        default_factory=ResourceRequirements,
        validation_alias=AliasChoices("compute", "resources"),
        description="CPU, memory, storage, and process limits for the Runtime.",
    )
    packages: RuntimePackages = Field(
        default_factory=RuntimePackages,
        description="Packages installed in the Runtime before an episode. In "
        "environment.yaml, list Python ones under python_packages. On the local "
        "Runtime they must already be installed.",
    )
    read_only_root: bool = False
    targets: frozenset[ExecutionTarget] = Field(
        default_factory=lambda: frozenset({ExecutionTarget.DOCKER, ExecutionTarget.REMOTE})
    )
    persistent: bool = False
    compose: bool = False
    extra_capabilities: frozenset[SandboxCapability] = frozenset()
    timeout_seconds: float = Field(default=300, gt=0)
    build_timeout_seconds: float = Field(
        default=600,
        gt=0,
        validation_alias=AliasChoices("build_timeout_seconds", "build_timeout_sec"),
    )
    allow_unsafe_local: bool = False

    network_allowlist = renamed_attribute("network_allowlist", "allowed_hosts")
    build_timeout_sec = renamed_attribute("build_timeout_sec", "build_timeout_seconds")
    resources = renamed_attribute("resources", "compute")

    @model_validator(mode="before")
    @classmethod
    def _convenience_resources(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(renamed_keys(value, RUNTIME_RENAMES, "Runtime"))
        compute = dict(payload.get("compute") or {})
        for source, target in (
            ("cpus", "cpu"),
            ("memory_mb", "memory_mb"),
            ("storage_mb", "storage_mb"),
        ):
            if source in payload and target not in compute:
                compute[target] = payload.pop(source)
        if "python_packages" in payload and "packages" not in payload:
            payload["packages"] = {"python": payload.pop("python_packages") or ()}
        if compute:
            payload["compute"] = compute
        return payload

    @model_validator(mode="after")
    def _valid_runtime(self) -> EnvironmentRuntime:
        names = [item.name for item in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("Runtime variable names must be unique")
        if self.allowed_hosts and self.network is not NetworkMode.ALLOWLIST:
            raise ValueError(
                "Cannot create Runtime.\n"
                f"allowed_hosts is set ({list(self.allowed_hosts)!r}) but "
                f"network={self.network.value!r}.\n"
                "Set network='allowlist' (Harbor name) or network='restricted' "
                "(legacy alias), or remove allowed_hosts."
            )
        if self.network is NetworkMode.ALLOWLIST and not self.allowed_hosts:
            raise ValueError(
                "Cannot create Runtime.\n"
                "network='allowlist' requires at least one host in allowed_hosts.\n"
                "Example: Runtime.docker(network='allowlist', allowed_hosts=('api.openai.com',))"
            )
        if (
            sum(
                (
                    self.image is not None,
                    self.snapshot is not None,
                    self.declarative_image is not None,
                )
            )
            > 1
        ):
            raise ValueError(
                "Cannot create Runtime.\n"
                "image, snapshot, and declarative_image are mutually exclusive.\n"
                "Pick one image source, or use Runtime.docker(dockerfile=..., build_context=...)."
            )
        target = self.requested_target
        if target is ExecutionTarget.LOCAL and not self.allow_unsafe_local:
            raise ValueError(
                "Cannot create Runtime.\n"
                "provider='local' runs a trusted subprocess on this machine and is not a sandbox.\n"
                "Use Runtime.local() or pass allow_unsafe_local=True, network='public', "
                "and targets that include 'local'."
            )
        if target not in self.targets:
            declared = sorted(item.value for item in self.targets)
            raise ValueError(
                "Cannot create Runtime.\n"
                f"provider={self.provider!r} maps to target {target.value!r}, "
                f"but targets={declared}.\n"
                f"Add {target.value!r} to targets, or use Runtime.{self.provider}()."
            )
        return self

    @classmethod
    def docker(
        cls,
        *,
        image: str | None = "python:3.12-slim",
        dockerfile: str | None = None,
        build_context: str | None = None,
        network: NetworkMode | str = NetworkMode.PUBLIC,
        allowed_hosts: tuple[str, ...] = (),
        cpus: float | None = None,
        memory_mb: int | None = None,
        storage_mb: int | None = None,
        **fields: Any,
    ) -> EnvironmentRuntime:
        """Docker Runtime with Harbor defaults: public network and a pinned image.

        Returns:
            A Docker Runtime.
        """
        if dockerfile is not None:
            image = None
            fields.setdefault("build_context", build_context or ".")
            fields["dockerfile"] = dockerfile
        if allowed_hosts:
            fields["allowed_hosts"] = allowed_hosts
        if any(item is not None for item in (cpus, memory_mb, storage_mb)):
            fields["compute"] = ResourceRequirements(
                cpu=cpus,
                memory_mb=memory_mb,
                storage_mb=storage_mb,
            )
        return cls(
            provider="docker",
            image=image,
            network=NetworkMode(network) if not isinstance(network, NetworkMode) else network,
            targets=frozenset({ExecutionTarget.DOCKER, ExecutionTarget.REMOTE}),
            **fields,
        )

    @classmethod
    def local(
        cls,
        *,
        network: NetworkMode | str = NetworkMode.PUBLIC,
        **fields: Any,
    ) -> EnvironmentRuntime:
        """Trusted local subprocess Runtime. Not a sandbox.

        Returns:
            A local Runtime.
        """
        return cls(
            provider="local",
            image=None,
            network=NetworkMode(network) if not isinstance(network, NetworkMode) else network,
            targets=frozenset({ExecutionTarget.LOCAL}),
            allow_unsafe_local=True,
            **fields,
        )

    @classmethod
    def daytona(
        cls,
        *,
        image: str | None = "python:3.12-slim",
        network: NetworkMode | str = NetworkMode.PUBLIC,
        allowed_hosts: tuple[str, ...] = (),
        **fields: Any,
    ) -> EnvironmentRuntime:
        """Daytona remote sandbox Runtime. Requires ``plural[daytona]``.

        Returns:
            A Daytona Runtime.
        """
        if allowed_hosts:
            fields["allowed_hosts"] = allowed_hosts
        return cls(
            provider="daytona",
            image=image,
            network=NetworkMode(network) if not isinstance(network, NetworkMode) else network,
            targets=frozenset({ExecutionTarget.REMOTE}),
            **fields,
        )

    @property
    def requested_target(self) -> ExecutionTarget:
        """Execution target implied by the Environment provider."""
        if self.provider == "local":
            return ExecutionTarget.LOCAL
        spec = runtime_provider(self.provider)
        if self.provider == "remote" or (spec is not None and spec.target == "remote"):
            return ExecutionTarget.REMOTE
        return ExecutionTarget.DOCKER

    def required_capabilities(self) -> frozenset[SandboxCapability]:
        """Provider capabilities needed by this runtime.

        Returns:
            Required provider capabilities.
        """
        return environment_required_capabilities(self)

    def target_exclusions(self) -> dict[ExecutionTarget, str]:
        """Derived target incompatibilities.

        Returns:
            Target-to-reason mapping.
        """
        reasons: dict[ExecutionTarget, str] = {}
        if self.network in {NetworkMode.NONE, NetworkMode.RESTRICTED}:
            reasons[ExecutionTarget.LOCAL] = f"cannot enforce network={self.network.value}"
        elif not self.allow_unsafe_local:
            reasons[ExecutionTarget.LOCAL] = "allow_unsafe_local is required for local execution"
        if self.persistent:
            reasons.setdefault(ExecutionTarget.LOCAL, "cannot enforce persistence")
        if self.compose:
            reasons.setdefault(ExecutionTarget.LOCAL, "cannot enforce compose")
        if self.compute.configured:
            reasons.setdefault(ExecutionTarget.LOCAL, "cannot enforce compute limits")
        if self.build_context or self.dockerfile:
            reasons[ExecutionTarget.REMOTE] = "remote provider cannot consume a local build context"
        return reasons

    def available_targets(self) -> frozenset[ExecutionTarget]:
        """Declared, enforceable targets.

        Returns:
            Available target classes.
        """
        excluded = self.target_exclusions()
        return frozenset(item for item in self.targets if item not in excluded)


class HarnessPolicy(FrozenModel):
    """Environment ceiling for a Trial's optional Agent harness."""

    mode: Literal["allow_all", "allowlist"] = "allow_all"
    allowed_harnesses: tuple[str, ...] = ()
    allowed_capabilities: frozenset[HarnessCapability] | None = None
    denied_capabilities: frozenset[HarnessCapability] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _public_harness_names(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        allowed = payload.get("allowed_harnesses")
        if isinstance(allowed, (list, tuple)):
            payload["allowed_harnesses"] = tuple(
                item.name if isinstance(item, HarnessBinding) else str(item) for item in allowed
            )
        return payload


class HarnessGrant(FrozenModel):
    """Effective harness tool policy for one Trial.

    Computed when an Agent binds to a Task Environment. The Environment may
    only subtract harness tools; it does not own or wrap the model.
    """

    environment: EnvironmentIdentity
    harness: HarnessBinding
    declared: frozenset[HarnessCapability]
    granted: frozenset[HarnessCapability]
    denied: frozenset[HarnessCapability]
    denial_reasons: dict[str, str] = Field(default_factory=dict)

    @property
    def capability_denials(self) -> tuple[dict[str, str], ...]:
        """Denied harness tools with the Environment reason for each."""
        return tuple(
            {
                "capability": capability.value,
                "reason": self.denial_reasons.get(capability.value, "Environment policy"),
            }
            for capability in sorted(self.denied, key=lambda item: item.value)
        )


MAX_TURNS = 1000


class ExecutionLimits(FrozenModel):
    """Environment execution limits."""

    max_turns: int = Field(default=8, ge=1, le=MAX_TURNS)
    max_seconds: float = Field(default=120, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)


MAX_PARTY = 100


PartyIsolation = Literal["isolated", "shared"]


class Party(FrozenModel):
    """How many Agents may share one episode of the Environment, such as 2 to 8 at poker.

    An Environment with a party is played by several Agents at once, each in a
    seat of its own: ``seat_1`` to ``seat_N`` for a party of N. A Job names the
    Agents in the party, and its size must fall between ``min`` and ``max``.
    """

    min: int = Field(default=2, ge=2, le=MAX_PARTY)
    max: int = Field(default=2, ge=2, le=MAX_PARTY)
    isolation: PartyIsolation = Field(
        default="isolated",
        description="``isolated``: each seat's Harness runs as its own OS user, and the "
        "Apps are the only thing the seats share; needs Docker or Daytona. ``shared``: "
        "every seat runs as one user and can read and write the others' files and the "
        "Environment's, for a team that works on the same files, or to try a party on "
        "the local Runtime. A shared seat could also act for another seat.",
    )

    @model_validator(mode="before")
    @classmethod
    def _from_size(cls, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool):
            return {"min": value, "max": value}
        return value

    @model_validator(mode="after")
    def _ordered(self) -> Party:
        if self.min > self.max:
            raise ValueError(f"party min {self.min} is more than its max {self.max}")
        return self

    def check(self, size: int) -> str | None:
        """Why a party of ``size`` cannot play, or ``None`` when it can.

        Returns:
            The reason, for a size outside ``min`` to ``max``.
        """
        if self.min <= size <= self.max:
            return None
        allowed = str(self.min) if self.min == self.max else f"{self.min} to {self.max}"
        return f"a party of {size} Agents cannot play; this Environment takes {allowed}"


def party_seats(size: int) -> tuple[str, ...]:
    """The seats of a party of ``size``: ``seat_1`` to ``seat_<size>``.

    Returns:
        The seat names, in order.
    """
    return tuple(f"seat_{index}" for index in range(1, size + 1))


def _merged(items: Iterable[SecretReference]) -> tuple[SecretReference, ...]:
    """Each name once; required wins when two Apps disagree.

    Returns:
        The references in first-seen order.
    """
    seen: dict[str, SecretReference] = {}
    for item in items:
        current = seen.get(item.name)
        if current is None or (item.required and not current.required):
            seen[item.name] = item
    return tuple(seen.values())


class EnvironmentDefinition(FrozenModel):
    """Schema-v2 Environment: Apps composed with one Runtime and one set of limits.

    Tasks, Verifiers, and mode are intentionally absent. Every action belongs
    to exactly one App; ``python`` optionally names an Environment subclass
    whose ``on_step``, ``terminated``, or ``truncated`` span several Apps.
    """

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    overview: str = ""
    readme: str = ""
    apps: tuple[AppDefinition, ...] = ()
    python: str | None = None
    guardrails: tuple[Guardrail, ...] = ()
    resources: tuple[EnvironmentResource, ...] = ()
    runtime: EnvironmentRuntime = Field(default_factory=EnvironmentRuntime)
    harness_policy: HarnessPolicy = Field(default_factory=HarnessPolicy)
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    party: Party | None = Field(
        default=None,
        description="How many Agents share each episode, for a game such as poker. "
        "Leave it unset for an Environment one Agent works in alone.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: PackageSource | None = Field(
        default=None,
        json_schema_extra={"x-internal": True},
    )

    @model_serializer(mode="wrap")
    def _omit_no_party(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        # An Environment one Agent works in serializes as it did before parties.
        if isinstance(data, dict) and self.party is None:
            data.pop("party", None)
        return data

    @model_validator(mode="before")
    @classmethod
    def _reject_v1_ownership(cls, value: Any) -> Any:
        if isinstance(value, dict):
            if str(value.get("schema_version", "2")) != "2":
                raise ValueError(
                    "schema-v1 Environment is unsupported; move tasks and verifiers into "
                    "first-class Task and Verifier packages"
                )
            stale = {"tasks", "verifier", "mode", "context"} & set(value)
            if stale:
                raise ValueError("schema-v2 Environment cannot own " + ", ".join(sorted(stale)))
            if value.get("verifiers"):
                raise ValueError(
                    "An Environment does not own Verifiers. List them on each Task under "
                    "verifiers:, so what counts as a good episode can differ per Task."
                )
            moved = {"actions", "secrets", "state_schema", "observation_schema"} & {
                key for key, item in value.items() if item
            }
            if moved:
                raise ValueError(
                    "An Environment no longer owns "
                    + ", ".join(sorted(moved))
                    + ". Declare them on an App and list it in apps."
                )
            payload = {
                key: item
                for key, item in value.items()
                if key
                not in {
                    "schema_version",
                    "actions",
                    "verifiers",
                    "secrets",
                    "state_schema",
                    "observation_schema",
                    "reset_command",
                }
            }
            if "version" not in payload and "revision" in payload:
                payload["version"] = payload.pop("revision")
            return payload
        return value

    @model_validator(mode="after")
    def _unique_names(self) -> EnvironmentDefinition:
        semantic_version(self.version)
        app_names = [item.name for item in self.apps]
        if len(app_names) != len(set(app_names)):
            raise ValueError("App names must be unique within an Environment")
        resource_names = [item.name for item in self.resources]
        if len(resource_names) != len(set(resource_names)):
            raise ValueError("resource names must be unique")
        variables = {item.name for item in self.runtime.variables}
        secret_names = {item.name for item in self.secrets}
        credential_names = {item.name for item in self.credentials}
        overlap = sorted(variables & (secret_names | credential_names))
        if overlap:
            raise ValueError(
                f"{overlap[0]} is both a Runtime variable and an App secret; declare it once"
            )
        mixed = sorted(secret_names & credential_names)
        if mixed:
            raise ValueError(
                f"{mixed[0]} is a secret of one App and a credential of another. A "
                "credential comes from the Agent and a secret from the project, so one name "
                "cannot be both; rename one of them."
            )
        exposed = [item.name for item in self.actions]
        clashes = sorted({name for name in exposed if exposed.count(name) > 1})
        if clashes:
            raise ValueError(f"Environment exposes duplicate action names: {clashes}")
        if self.party is not None:
            if not self.apps:
                raise ValueError(
                    f"Environment {self.name!r} has a party, so it needs an App its Agents share."
                )
            asking = [item.name for item in self.apps if item.credentials]
            if asking:
                # The host acts for every seat, so it could not keep one seat's credential
                # from another.
                raise ValueError(
                    f"Environment {self.name!r} has a party, but its Apps {', '.join(asking)} "
                    "ask for Agent credentials, and the party shares one App host. Use "
                    "project secrets instead."
                )
            if self.party.isolation == "isolated" and self.runtime.provider == "local":
                # Every process on the local Runtime runs as you, so one seat's
                # Harness could read another's folder, token, and memory.
                raise ValueError(
                    f"Environment {self.name!r} has a party, so each seat needs an OS user "
                    "of its own, and the local Runtime runs every seat as you. Use "
                    "Runtime.docker(), which runs on your machine too, or Runtime.daytona(), "
                    "or set party isolation to 'shared' if the seats may see each other."
                )
        return self

    @property
    def actions(self) -> tuple[ExposedAction, ...]:
        """Every App action as the Agent sees it.

        Each keeps its own name, made safe for every model provider, and is
        prefixed ``<app>__`` only when another App offers the same name. With
        several Apps, each description starts with the App's name, so the
        model knows which system a tool acts on.
        """
        return exposed_actions(self.apps)

    @property
    def secrets(self) -> tuple[SecretReference, ...]:
        """Every setup secret the Environment's Apps need, each listed once."""
        return _merged(item for app in self.apps for item in app.secrets)

    @property
    def credentials(self) -> tuple[SecretReference, ...]:
        """Every credential the running Agent must supply, each listed once."""
        return _merged(item for app in self.apps for item in app.credentials)

    def app(self, name: str) -> AppDefinition:
        """Return one App by name.

        Raises:
            KeyError: When the Environment has no App of that name.
        """
        for item in self.apps:
            if item.name == name:
                return item
        available = ", ".join(item.name for item in self.apps) or "none"
        raise KeyError(f"Environment {self.name!r} has no App {name!r}; Apps: {available}")

    @property
    def reproducible(self) -> bool:
        """Whether every App starts each Trial from the same state."""
        return all(item.reproducible for item in self.apps)

    @property
    def revision(self) -> str:
        """Compatibility version name used by execution and hosted internals."""
        return self.version

    @property
    def schema_version(self) -> Literal["2"]:
        """Internal protocol compatibility without public serialization."""
        return "2"

    @property
    def content_hash(self) -> str:
        """Stable Environment revision digest."""
        payload = self.model_dump(mode="json", exclude={"source"})
        if payload["runtime"]["ref"] is None:
            del payload["runtime"]["ref"]
        if not self.runtime.packages:
            # Runtimes that install nothing keep the identity they had before packages.
            del payload["runtime"]["packages"]
        payload["runtime"] = runtime_hash_payload(payload["runtime"])
        for app in payload["apps"]:
            # Apps that need no credentials keep the identity they had before credentials.
            if not app["credentials"]:
                del app["credentials"]

        digest = self.source.digest if self.source else None
        payload["source_digest"] = digest
        return revision_hash("environment", payload)

    @property
    def identity(self) -> EnvironmentIdentity:
        """Exact identity represented by this revision."""
        return EnvironmentIdentity(name=self.name, revision=self.version, digest=self.content_hash)


Resource = EnvironmentResource
Runtime = EnvironmentRuntime
Secret = SecretReference


__all__ = [
    "EnvironmentIdentity",
    "EnvironmentDefinition",
    "EnvironmentResource",
    "EnvironmentRuntime",
    "ExecutionLimits",
    "Guardrail",
    "HarnessPolicy",
    "HarnessGrant",
    "MAX_PARTY",
    "Party",
    "Resource",
    "Runtime",
    "Secret",
    "SecretReference",
    "party_seats",
]
