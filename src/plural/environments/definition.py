"""Schema-v2 Environment definition, runtime, and policy declarations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

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
    """Data or application supplied by an Environment."""

    kind: Literal["data", "application", "file"]
    name: str = Field(min_length=1)
    path: str | None = None
    uri: str | None = None
    digest: str | None = None
    content_type: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class SecretReference(FrozenModel):
    """A named secret injected by a runtime without embedding its value."""

    name: str = Field(min_length=1)
    required: bool = True
    target: Literal["environment", "harness", "verifier"] = "environment"


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
    """Immutable Environment-owned provider, placement, network, and compute."""

    provider: str = Field(default="docker", min_length=1)
    placement: dict[str, str] = Field(default_factory=dict)
    image: str | None = None
    snapshot: str | None = None
    declarative_image: DeclarativeImage | None = None
    build_context: str | None = None
    dockerfile: str | None = None
    network: NetworkMode = NetworkMode.NONE
    network_allowlist: tuple[str, ...] = ()
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    read_only_root: bool = False
    targets: frozenset[ExecutionTarget] = Field(
        default_factory=lambda: frozenset({ExecutionTarget.DOCKER, ExecutionTarget.REMOTE})
    )
    persistent: bool = False
    compose: bool = False
    extra_capabilities: frozenset[Capability] = frozenset()
    timeout_seconds: float = Field(default=300, gt=0)
    allow_unsafe_local: bool = False

    @model_validator(mode="after")
    def _valid_runtime(self) -> EnvironmentRuntime:
        if self.network_allowlist and self.network is not NetworkMode.RESTRICTED:
            raise ValueError("network_allowlist requires network='restricted'")
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
            raise ValueError("image, snapshot, and declarative_image are mutually exclusive")
        target = self.requested_target
        if target is ExecutionTarget.LOCAL and not self.allow_unsafe_local:
            raise ValueError("provider='local' requires allow_unsafe_local=true")
        if target not in self.targets:
            raise ValueError("runtime provider target must be declared in targets")
        return self

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
    allowed_harnesses: tuple[HarnessBinding, ...] = ()
    allowed_capabilities: frozenset[HarnessCapability] | None = None
    denied_capabilities: frozenset[HarnessCapability] = frozenset()


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
    source: PackageSource | None = None

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
