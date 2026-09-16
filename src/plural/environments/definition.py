"""Schema-v2 Environment definition, runtime, and policy declarations."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator

from plural.common import (
    SHA256_PATTERN,
    ExecutionTarget,
    FrozenModel,
    HarnessBinding,
    HarnessCapability,
    PackageSource,
    content_hash,
    semantic_version,
)
from plural.sandbox.models import (
    Capability,
    DeclarativeImage,
    NetworkMode,
    ResourceRequirements,
    environment_required_capabilities,
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


class NativeAction(FrozenModel):
    """An action owned by an Environment."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: Literal["command", "python"] = "command"
    command: tuple[str, ...] = ()
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "additionalProperties": True}
    )
    observation_schema: dict[str, Any] = Field(default_factory=dict)
    mutates_state: bool = True
    timeout_seconds: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def _command_required(self) -> NativeAction:
        if self.kind == "command" and not self.command:
            raise ValueError("kind='command' requires a non-empty command")
        return self


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


class SecretReference(FrozenModel):
    """A named credential supplied when a Job runs, with an explicit execution target."""

    name: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    required: bool = True
    target: Literal["environment", "harness", "verifier"] = "environment"
    description: str = ""

    @field_validator("name")
    @classmethod
    def _application_name(cls, value: str) -> str:
        return RuntimeVariable._application_name(value)


class RewarderDefinition(FrozenModel):
    """A train-only state-transition rewarder."""

    name: str = Field(min_length=1)
    description: str = ""
    kind: Literal["command", "python"] = "command"
    command: tuple[str, ...] = ()
    implementation_digest: str = ""
    weight: float = Field(default=1, gt=0)
    timeout_seconds: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def _implementation(self) -> RewarderDefinition:
        if self.kind == "command" and not self.command:
            raise ValueError("command rewarders require a command")
        if self.kind == "python" and not self.implementation_digest:
            raise ValueError("python rewarders require an implementation_digest")
        return self


class EnvironmentRuntime(FrozenModel):
    """Where an Environment runs: Docker, a trusted local process, or Daytona."""

    provider: str = Field(default="docker", min_length=1)
    placement: dict[str, str] = Field(default_factory=dict)
    variables: tuple[RuntimeVariable, ...] = ()
    image: str | None = None
    snapshot: str | None = None
    declarative_image: DeclarativeImage | None = None
    build_context: str | None = None
    dockerfile: str | None = None
    network: NetworkMode = NetworkMode.PUBLIC
    network_allowlist: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices("network_allowlist", "allowed_hosts"),
    )
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    read_only_root: bool = False
    targets: frozenset[ExecutionTarget] = Field(
        default_factory=lambda: frozenset({ExecutionTarget.DOCKER, ExecutionTarget.REMOTE})
    )
    persistent: bool = False
    compose: bool = False
    extra_capabilities: frozenset[Capability] = frozenset()
    timeout_seconds: float = Field(default=300, gt=0)
    build_timeout_sec: float = Field(default=600, gt=0)
    allow_unsafe_local: bool = False

    @model_validator(mode="before")
    @classmethod
    def _convenience_resources(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        resources = dict(payload.get("resources") or {})
        for source, target in (
            ("cpus", "cpu"),
            ("memory_mb", "memory_mb"),
            ("storage_mb", "storage_mb"),
        ):
            if source in payload and target not in resources:
                resources[target] = payload.pop(source)
        if "allowed_hosts" in payload and "network_allowlist" not in payload:
            payload["network_allowlist"] = payload.pop("allowed_hosts")
        if resources:
            payload["resources"] = resources
        return payload

    @model_validator(mode="after")
    def _valid_runtime(self) -> EnvironmentRuntime:
        names = [item.name for item in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("Runtime variable names must be unique")
        if self.network_allowlist and self.network is not NetworkMode.ALLOWLIST:
            raise ValueError(
                "Cannot create Runtime.\n"
                f"allowed_hosts is set ({list(self.network_allowlist)!r}) but "
                f"network={self.network.value!r}.\n"
                "Set network='allowlist' (Harbor name) or network='restricted' "
                "(legacy alias), or remove allowed_hosts."
            )
        if self.network is NetworkMode.ALLOWLIST and not self.network_allowlist:
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
            fields["network_allowlist"] = allowed_hosts
        if any(item is not None for item in (cpus, memory_mb, storage_mb)):
            fields["resources"] = ResourceRequirements(
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
            fields["network_allowlist"] = allowed_hosts
        return cls(
            provider="daytona",
            image=image,
            network=NetworkMode(network) if not isinstance(network, NetworkMode) else network,
            targets=frozenset({ExecutionTarget.REMOTE}),
            **fields,
        )

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        """Harbor name for the network allowlist."""
        return self.network_allowlist

    @property
    def requested_target(self) -> ExecutionTarget:
        """Execution target implied by the Environment provider."""
        if self.provider == "local":
            return ExecutionTarget.LOCAL
        if self.provider in {"remote", "daytona"}:
            return ExecutionTarget.REMOTE
        return ExecutionTarget.DOCKER

    def required_capabilities(self) -> frozenset[Capability]:
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
        if self.resources.configured:
            reasons.setdefault(ExecutionTarget.LOCAL, "cannot enforce resource limits")
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


class ExecutionLimits(FrozenModel):
    """Environment execution limits."""

    max_turns: int = Field(default=8, ge=1, le=128)
    max_seconds: float = Field(default=120, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)


class EnvironmentDefinition(FrozenModel):
    """Schema-v2 Environment. Tasks, Verifiers, and mode are intentionally absent."""

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    overview: str = ""
    readme: str = ""
    actions: tuple[NativeAction, ...] = ()
    reset_command: tuple[str, ...] = ()
    observation_schema: dict[str, Any] = Field(default_factory=dict)
    state_schema: dict[str, Any] = Field(default_factory=dict)
    rewarders: tuple[RewarderDefinition, ...] = ()
    guardrails: tuple[Guardrail, ...] = ()
    resources: tuple[EnvironmentResource, ...] = ()
    runtime: EnvironmentRuntime = Field(default_factory=EnvironmentRuntime)
    secrets: tuple[SecretReference, ...] = ()
    harness_policy: HarnessPolicy = Field(default_factory=HarnessPolicy)
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: PackageSource | None = Field(
        default=None,
        json_schema_extra={"x-internal": True},
    )

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
            payload = dict(value)
            payload.pop("schema_version", None)
            if "version" not in payload and "revision" in payload:
                payload["version"] = payload.pop("revision")
            return payload
        return value

    @model_validator(mode="after")
    def _unique_names(self) -> EnvironmentDefinition:
        semantic_version(self.version)
        overlap = {item.name for item in self.runtime.variables} & {
            item.name for item in self.secrets
        }
        if overlap:
            raise ValueError("Declare each runtime variable or secret only once")
        for label, values in (
            ("action", self.actions),
            ("resource", self.resources),
            ("rewarder", self.rewarders),
            ("secret", self.secrets),
        ):
            names = [item.name for item in values]
            if len(names) != len(set(names)):
                raise ValueError(f"{label} names must be unique")
        return self

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
        payload["source_digest"] = self.source.digest if self.source else None
        return content_hash(payload)

    @property
    def identity(self) -> EnvironmentIdentity:
        """Exact identity represented by this revision."""
        return EnvironmentIdentity(name=self.name, revision=self.version, digest=self.content_hash)


Action = NativeAction
Resource = EnvironmentResource
Runtime = EnvironmentRuntime
Secret = SecretReference


__all__ = [
    "Action",
    "EnvironmentIdentity",
    "EnvironmentDefinition",
    "EnvironmentResource",
    "EnvironmentRuntime",
    "ExecutionLimits",
    "Guardrail",
    "HarnessPolicy",
    "HarnessGrant",
    "NativeAction",
    "RewarderDefinition",
    "Resource",
    "Runtime",
    "Secret",
    "SecretReference",
]
