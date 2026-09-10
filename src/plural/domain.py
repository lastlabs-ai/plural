"""Immutable package, job, and trial domain models.

These models describe execution without implementing an execution provider. They
are intentionally serializable, content-addressed, and strict so the same config
produces the same job and trial identities on every machine.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

from plural.sandbox.models import (
    Capability,
    DeclarativeImage,
    NetworkMode,
    ResourceRequirements,
    environment_required_capabilities,
)

SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for a model or JSON-compatible value."""
    value = to_jsonable_python(value, exclude_none=False)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    """Return a versioned SHA-256 content digest."""
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def stable_id(prefix: str, value: Any) -> str:
    """Return a compact stable identifier derived from canonical content."""
    return f"{prefix}_{content_hash(value).removeprefix('sha256:')[:24]}"


class FrozenModel(BaseModel):
    """Strict frozen base for public domain and config models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ErrorCode(str, Enum):
    """Stable execution error codes used by retry policies and receipts."""

    AUTHENTICATION = "authentication"
    CONFIGURATION = "configuration"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    HARNESS_FAILED = "harness_failed"
    PROTOCOL_FAILED = "protocol_failed"
    ENVIRONMENT_FAILED = "environment_failed"
    VERIFIER_FAILED = "verifier_failed"
    EVIDENCE_MISSING = "evidence_missing"
    ARTIFACT_FAILED = "artifact_failed"
    LOCK_INCOMPATIBLE = "lock_incompatible"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class ExecutionTarget(str, Enum):
    """Where a trial for this environment may execute."""

    LOCAL = "local"
    DOCKER = "docker"
    REMOTE = "remote"


class HarnessCapability(str, Enum):
    """Actions a stamped harness may request."""

    SHELL = "shell"
    FILE_READ = "file_read"
    FILE_EDIT = "file_edit"
    CODE_EXECUTION = "code_execution"
    WEB_SEARCH = "web_search"
    BROWSER = "browser"
    NETWORK_FETCH = "network_fetch"
    MCP = "mcp"
    SUBAGENTS = "subagents"
    PERSISTENCE = "persistence"


class PackageSource(FrozenModel):
    """Immutable source for a harness package.

    Published and remote sources require a digest. An unsigned local source is
    accepted only when explicitly marked unsafe. ``trusted`` is retained only
    for manifest migration and never bypasses digest or unsafe checks.
    """

    kind: Literal["local", "oci", "archive"]
    uri: str = Field(min_length=1)
    digest: str | None = None
    trusted: bool = False
    unsafe_local: bool = False

    @field_validator("digest")
    @classmethod
    def _valid_digest(cls, value: str | None) -> str | None:
        if value is not None and SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must be sha256:<64 lowercase hex characters>")
        return value

    @model_validator(mode="after")
    def _immutable_or_explicit_local(self) -> PackageSource:
        if self.kind != "local" and self.digest is None:
            raise ValueError("nonlocal harness sources require an immutable digest")
        if self.kind == "local" and self.digest is None and not self.unsafe_local:
            raise ValueError("unsigned local harness source requires unsafe_local=true")
        if self.kind != "local" and self.unsafe_local:
            raise ValueError("unsafe_local is valid only for local sources")
        return self


class FileDeclaration(FrozenModel):
    """One exact file a harness or verifier may emit or consume."""

    path: str = Field(min_length=1)
    required: bool = True
    media_type: str = "application/octet-stream"

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        from plural.sandbox.models import safe_relative_path

        return safe_relative_path(value)


class HarnessManifest(FrozenModel):
    """Public manifest for a single-agent harness package.

    A ``declared`` harness can be stamped and inspected but cannot execute a
    trial. A ``runnable`` harness must provide a command.
    """

    schema_version: Literal["1"] = "1"
    name: str = Field(min_length=1)
    version: str = Field(default="0.1.0", min_length=1)
    description: str = ""
    protocol: Literal["plural-harness-v1", "acp"] = "plural-harness-v1"
    protocol_adapter: Literal["acp-client-v1"] | None = None
    entrypoint: str | None = None
    implementation: Literal["declared", "runnable"] = "declared"
    command: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    capabilities: frozenset[HarnessCapability] = frozenset()
    supported_models: tuple[str, ...] = ("*",)
    auth_modes: tuple[Literal["environment", "api_key", "oauth", "none"], ...] = ("environment",)
    secret_names: tuple[str, ...] = ()
    environment_names: tuple[str, ...] = ()
    healthcheck: tuple[str, ...] | None = None
    trajectory_path: str | None = None
    outputs: tuple[FileDeclaration, ...] = ()
    artifacts: tuple[FileDeclaration, ...] = ()

    @field_validator(
        "command",
        "requirements",
        "supported_models",
        "secret_names",
        "environment_names",
        "healthcheck",
    )
    @classmethod
    def _nonempty_items(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("items must be non-empty strings")
        return value

    @model_validator(mode="after")
    def _protocol_and_implementation(self) -> HarnessManifest:
        if self.protocol == "acp" and self.protocol_adapter != "acp-client-v1":
            raise ValueError("protocol='acp' requires protocol_adapter='acp-client-v1'")
        if self.protocol != "acp" and self.protocol_adapter is not None:
            raise ValueError("protocol_adapter is valid only for protocol='acp'")
        if self.trajectory_path is not None:
            declared = {item.path for item in self.artifacts}
            if self.trajectory_path not in declared:
                raise ValueError("trajectory_path must be declared in artifacts")
        if self.implementation == "runnable" and not self.command:
            raise ValueError("runnable harnesses require a command")
        return self


class HarnessPackage(FrozenModel):
    """Content-addressed harness manifest and source."""

    manifest: HarnessManifest
    source: PackageSource

    @property
    def content_hash(self) -> str:
        """Stable package hash."""
        return content_hash(self)

    @property
    def package_id(self) -> str:
        """Stable package identifier."""
        return stable_id("hrn", self)


class HarnessBinding(FrozenModel):
    """Exact harness binding used by one agent and every resulting trial."""

    name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    digest: str

    @field_validator("digest")
    @classmethod
    def _valid_digest(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must be sha256:<64 lowercase hex characters>")
        return value

    @classmethod
    def from_package(cls, package: HarnessPackage) -> HarnessBinding:
        """Create an exact binding from a harness package.

        Returns:
            Exact immutable harness binding.
        """
        return cls(
            name=package.manifest.name,
            revision=package.manifest.version,
            digest=package.source.digest or package.content_hash,
        )


class EnvironmentIdentity(FrozenModel):
    """Exact identity and revision for a packaged environment."""

    name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    digest: str

    @field_validator("digest")
    @classmethod
    def _valid_digest(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must be sha256:<64 lowercase hex characters>")
        return value


class TaskDefinition(FrozenModel):
    """Task owned by an environment package."""

    task_id: str = Field(min_length=1)
    input: Any
    expected: Any = None
    verifier_input: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def public_payload(self) -> dict[str, Any]:
        """Task data that may be sent to an agent harness."""
        return {"task_id": self.task_id, "input": self.input, "metadata": self.metadata}


class VerifierManifest(FrozenModel):
    """Isolated verifier command and required evidence contract."""

    command: tuple[str, ...] = Field(min_length=1)
    image: str | None = None
    timeout_seconds: float = Field(default=60, gt=0)
    required_artifacts: tuple[str, ...] = ()
    result_path: str = "verifier-result.json"
    evidence_required: bool = True

    @field_validator("command")
    @classmethod
    def _nonempty_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("items must be non-empty strings")
        return value

    @field_validator("required_artifacts")
    @classmethod
    def _safe_artifacts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        from plural.sandbox.models import safe_relative_path

        return tuple(safe_relative_path(item) for item in value)

    @field_validator("result_path")
    @classmethod
    def _safe_result_path(cls, value: str) -> str:
        from plural.sandbox.models import safe_relative_path

        return safe_relative_path(value)


class NativeAction(FrozenModel):
    """One action the environment owns. Acts in the environment, returns an observation."""

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

    @field_validator("command")
    @classmethod
    def _valid_command(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("command items must be non-empty and contain no NUL")
        return value

    @model_validator(mode="after")
    def _command_kind_requires_argv(self) -> NativeAction:
        if self.kind == "command" and not self.command:
            raise ValueError("kind='command' requires a non-empty command")
        return self


class Guardrail(FrozenModel):
    """One plain-language rule. Instructions, not enforcement."""

    name: str = ""
    rule: str = Field(min_length=1)


class EnvironmentResource(FrozenModel):
    """Data, application, or file the environment provides to the agent."""

    kind: Literal["data", "application", "file", "secret"]
    name: str = Field(min_length=1)
    path: str | None = None
    uri: str | None = None
    digest: str | None = None
    content_type: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class EnvironmentRuntime(FrozenModel):
    """Container, network, compute, and execution surface the environment requires."""

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
        sources = (
            self.image is not None,
            self.snapshot is not None,
            self.declarative_image is not None,
        )
        if sum(sources) > 1:
            raise ValueError("image, snapshot, and declarative_image are mutually exclusive")
        if ExecutionTarget.LOCAL in self.targets and not self.allow_unsafe_local:
            raise ValueError("ExecutionTarget.LOCAL requires allow_unsafe_local=true")
        return self

    def required_capabilities(self) -> frozenset[Capability]:
        """Return the sandbox controls this environment requires."""
        return environment_required_capabilities(self)

    def target_exclusions(self) -> dict[ExecutionTarget, str]:
        """Return derived reasons a target cannot run this environment."""
        reasons: dict[ExecutionTarget, str] = {}
        if self.network in {NetworkMode.NONE, NetworkMode.RESTRICTED}:
            reasons[ExecutionTarget.LOCAL] = f"cannot enforce network={self.network.value}"
        elif not self.allow_unsafe_local:
            reasons[ExecutionTarget.LOCAL] = "allow_unsafe_local is required for local execution"
        if ExecutionTarget.LOCAL not in reasons and self.persistent:
            reasons[ExecutionTarget.LOCAL] = "cannot enforce persistence"
        if ExecutionTarget.LOCAL not in reasons and self.compose:
            reasons[ExecutionTarget.LOCAL] = "cannot enforce compose"
        if ExecutionTarget.LOCAL not in reasons and self.resources.configured:
            reasons[ExecutionTarget.LOCAL] = "cannot enforce resource limits"
        if self.build_context or self.dockerfile:
            reasons[ExecutionTarget.REMOTE] = "remote provider cannot consume a local build context"
        return reasons

    def available_targets(self) -> frozenset[ExecutionTarget]:
        """Return declared targets that are not derived-excluded."""
        excluded = self.target_exclusions()
        return frozenset(target for target in self.targets if target not in excluded)


class HarnessPolicy(FrozenModel):
    """How an environment restricts any harness stamped onto it."""

    mode: Literal["allow_all", "allowlist"] = "allow_all"
    allowed_harnesses: tuple[HarnessBinding, ...] = ()
    allowed_capabilities: frozenset[HarnessCapability] | None = None
    denied_capabilities: frozenset[HarnessCapability] = frozenset()


class HarnessStamp(FrozenModel):
    """Frozen result of stamping one harness onto one environment revision."""

    environment: EnvironmentIdentity
    harness: HarnessBinding
    declared: frozenset[HarnessCapability]
    granted: frozenset[HarnessCapability]
    denied: frozenset[HarnessCapability]
    denial_reasons: dict[str, str] = Field(default_factory=dict)


class ExecutionLimits(FrozenModel):
    """Externally supplied limits enforced by built-in harnesses and provider timeout."""

    max_turns: int = Field(default=8, ge=1, le=128)
    max_seconds: float = Field(default=120, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)


class EnvironmentManifest(FrozenModel):
    """Environment package: native actions, runtime, resources, and harness policy."""

    schema_version: Literal["1"] = "1"
    name: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    description: str = ""
    instructions: str = ""
    context: Any = None
    actions: tuple[NativeAction, ...] = ()
    observation_schema: dict[str, Any] = Field(default_factory=dict)
    state_schema: dict[str, Any] = Field(default_factory=dict)
    guardrails: tuple[Guardrail, ...] = ()
    resources: tuple[EnvironmentResource, ...] = ()
    runtime: EnvironmentRuntime = Field(default_factory=EnvironmentRuntime)
    harness_policy: HarnessPolicy = Field(default_factory=HarnessPolicy)
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    tasks: tuple[TaskDefinition, ...] = ()
    verifier: VerifierManifest | None = None
    source: PackageSource | None = None

    @model_validator(mode="after")
    def _unique_owned_values(self) -> EnvironmentManifest:
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("environment task_id values must be unique")
        harnesses = [
            (item.name, item.revision, item.digest)
            for item in self.harness_policy.allowed_harnesses
        ]
        if len(harnesses) != len(set(harnesses)):
            raise ValueError("allowed harness bindings must be unique")
        action_names = [item.name for item in self.actions]
        if len(action_names) != len(set(action_names)):
            raise ValueError("environment action names must be unique")
        resource_names = [item.name for item in self.resources]
        if len(resource_names) != len(set(resource_names)):
            raise ValueError("environment resource names must be unique")
        return self

    @property
    def content_hash(self) -> str:
        """Stable environment content digest."""
        payload = self.model_dump(mode="json", exclude={"source"})
        payload["source_digest"] = self.source.digest if self.source is not None else None
        return content_hash(payload)

    @property
    def identity(self) -> EnvironmentIdentity:
        """Exact identity represented by this manifest."""
        return EnvironmentIdentity(
            name=self.name,
            revision=self.revision,
            digest=self.content_hash,
        )


class BenchmarkDefinition(FrozenModel):
    """Ordered task selection tied to one exact environment revision."""

    schema_version: Literal["1"] = "1"
    name: str = Field(min_length=1)
    environment: EnvironmentIdentity
    task_ids: tuple[str, ...] = Field(min_length=1)
    primary_metric: str = "reward"
    description: str = ""

    @model_validator(mode="after")
    def _unique_tasks(self) -> BenchmarkDefinition:
        if len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError("benchmark task_ids must be unique")
        return self

    @property
    def content_hash(self) -> str:
        """Stable benchmark definition digest."""
        return content_hash(self)


BenchmarkSpec = BenchmarkDefinition


class RoutingSpec(FrozenModel):
    """Portable model routing configuration for an agent."""

    provider: str | None = None
    fallback_models: tuple[str, ...] = ()
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, gt=0)


class AgentTemplate(FrozenModel):
    """Immutable model + environment configuration, optionally with a stamped harness."""

    schema_version: Literal["1"] = "1"
    name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    routing: RoutingSpec = Field(default_factory=RoutingSpec)
    environment: EnvironmentIdentity
    harness: HarnessBinding | None = None
    harness_package: HarnessPackage | None = None
    stamp: HarnessStamp | None = None
    auth_mode: Literal["environment", "api_key", "oauth", "none"] = "environment"
    secret_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _package_matches_binding(self) -> AgentTemplate:
        if self.harness is None and self.stamp is not None:
            raise ValueError("stamp requires a harness binding")
        if self.harness is not None and self.stamp is None:
            raise ValueError("stamped harness requires a HarnessStamp")
        if self.harness is None and self.harness_package is not None:
            raise ValueError("harness_package requires a harness binding")
        if (
            self.harness_package is not None
            and self.harness is not None
            and HarnessBinding.from_package(self.harness_package) != self.harness
        ):
            raise ValueError("harness_package does not match the exact harness binding")
        unknown = (
            set(self.secret_names) - set(self.harness_package.manifest.secret_names)
            if self.harness_package is not None
            else set()
        )
        if unknown:
            raise ValueError(f"secret_names contains undeclared names: {sorted(unknown)!r}")
        if (
            self.harness_package is not None
            and self.auth_mode not in self.harness_package.manifest.auth_modes
        ):
            raise ValueError("agent auth_mode is not supported by its harness")
        if self.auth_mode == "api_key" and not self.secret_names:
            raise ValueError("api_key auth_mode requires at least one declared secret name")
        if self.auth_mode == "none" and self.secret_names:
            raise ValueError("none auth_mode cannot declare secret names")
        return self

    @property
    def content_hash(self) -> str:
        """Stable agent template digest."""
        return content_hash(self)

    @property
    def template_id(self) -> str:
        """Stable agent template identifier."""
        return stable_id("atp", self)

    @property
    def agent_id(self) -> str:
        """Stable identifier used by job planning."""
        return self.template_id


class AgentInstanceRef(FrozenModel):
    """Hosted identity of a persistent agent instance."""

    instance_id: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    template_hash: str = Field(min_length=1)


class AgentBinding(FrozenModel):
    """A job participant: a template, optionally bound to a hosted instance."""

    template: AgentTemplate
    instance: AgentInstanceRef | None = None

    @property
    def agent_id(self) -> str:
        """Stable planning identity for this binding."""
        if self.instance is not None:
            return self.instance.instance_id
        return self.template.template_id

    @property
    def name(self) -> str:
        """Display name from the template."""
        return self.template.name

    @property
    def harness(self) -> HarnessBinding | None:
        """Optional stamped harness."""
        return self.template.harness

    @property
    def harness_package(self) -> HarnessPackage | None:
        """Optional executable harness package."""
        return self.template.harness_package

    @property
    def stamp(self) -> HarnessStamp | None:
        """Frozen harness stamp, if any."""
        return self.template.stamp

    @property
    def environment(self) -> EnvironmentIdentity:
        """Pinned environment identity."""
        return self.template.environment

    @property
    def model(self) -> str:
        """Routed model id."""
        return self.template.model

    @property
    def routing(self) -> RoutingSpec:
        """Portable routing configuration."""
        return self.template.routing

    @property
    def auth_mode(self) -> str:
        """Declared authentication mode."""
        return self.template.auth_mode

    @property
    def secret_names(self) -> tuple[str, ...]:
        """Secret names granted to this agent."""
        return self.template.secret_names

    @property
    def content_hash(self) -> str:
        """Stable binding digest."""
        return content_hash(self)


class RetryPolicy(FrozenModel):
    """Execution retries, separate from independent benchmark attempts."""

    max_retries: int = Field(default=0, ge=0)
    initial_backoff_seconds: float = Field(default=0.25, ge=0)
    max_backoff_seconds: float = Field(default=10, ge=0)
    multiplier: float = Field(default=2, ge=1)
    retryable_codes: tuple[ErrorCode, ...] = (
        ErrorCode.RATE_LIMITED,
        ErrorCode.PROVIDER_UNAVAILABLE,
        ErrorCode.TIMEOUT,
        ErrorCode.RUNTIME_UNAVAILABLE,
    )

    @model_validator(mode="after")
    def _bounded_backoff(self) -> RetryPolicy:
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must be at least initial_backoff_seconds")
        return self


class RuntimeSpec(FrozenModel):
    """Requested execution target. Image, network, and resources live on the environment."""

    provider: str = Field(default="docker", min_length=1)
    capabilities: tuple[str, ...] = ()
    timeout_seconds: float = Field(default=300, gt=0)
    unsafe_local: bool = False

    @property
    def requested_target(self) -> ExecutionTarget:
        """Map a provider name onto an execution target."""
        if self.provider == ExecutionTarget.LOCAL.value:
            return ExecutionTarget.LOCAL
        if self.provider == ExecutionTarget.REMOTE.value or self.provider == "daytona":
            return ExecutionTarget.REMOTE
        return ExecutionTarget.DOCKER


class JobSpec(FrozenModel):
    """Complete deterministic benchmark planning input."""

    schema_version: Literal["1"] = "1"
    environment: EnvironmentManifest
    benchmark: BenchmarkDefinition
    agents: tuple[AgentBinding, ...] = Field(min_length=1)
    n_attempts: int = Field(default=1, ge=1)
    concurrency: int = Field(default=1, ge=1)
    per_agent_concurrency: int = Field(default=1, ge=1)
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @model_validator(mode="after")
    def _compatible(self) -> JobSpec:
        validate_job_compatibility(self.environment, self.benchmark, self.agents)
        target = self.runtime.requested_target
        available = self.environment.runtime.available_targets()
        if target not in available:
            reason = self.environment.runtime.target_exclusions().get(
                target, "not in environment.runtime.targets"
            )
            raise ValueError(
                f"requested target {target.value!r} is not available for this environment: {reason}"
            )
        if target is ExecutionTarget.LOCAL and not self.runtime.unsafe_local:
            raise ValueError("local execution requires runtime.unsafe_local=true")
        agent_ids = [agent.agent_id for agent in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("agents must have unique identities")
        return self

    @property
    def content_hash(self) -> str:
        """Stable job configuration digest."""
        return content_hash(self)

    @property
    def job_id(self) -> str:
        """Stable trial-set identity, excluding retries and scheduling."""
        return stable_id(
            "job",
            {
                "schema_version": self.schema_version,
                "environment": self.environment,
                "benchmark": self.benchmark,
                "agents": self.agents,
                "n_attempts": self.n_attempts,
                "runtime": self.runtime,
            },
        )

    def plan(self) -> JobPlan:
        """Expand agent × ordered task × independent attempt deterministically.

        Returns:
            Ordered trial plan and reproducibility lock.
        """
        trials: list[TrialSpec] = []
        for agent in self.agents:
            for task_id in self.benchmark.task_ids:
                for attempt in range(1, self.n_attempts + 1):
                    trials.append(
                        TrialSpec(
                            job_id=self.job_id,
                            agent_id=agent.agent_id,
                            agent_name=agent.name,
                            task_id=task_id,
                            attempt=attempt,
                            environment=self.benchmark.environment,
                            harness=agent.harness,
                            instance_id=agent.instance.instance_id if agent.instance else None,
                            runtime=self.runtime,
                        )
                    )
        task_map = {task.task_id: task for task in self.environment.tasks}
        selected_tasks = [task_map[task_id] for task_id in self.benchmark.task_ids]
        lock = JobLock(
            job_id=self.job_id,
            spec_hash=self.content_hash,
            environment=self.benchmark.environment,
            benchmark_hash=self.benchmark.content_hash,
            task_set_hash=content_hash(selected_tasks),
            agent_hashes=tuple(agent.content_hash for agent in self.agents),
            harness_digests=tuple(
                agent.harness.digest for agent in self.agents if agent.harness is not None
            ),
            environment_source_digest=(
                self.environment.source.digest if self.environment.source is not None else None
            ),
            execution_limits=self.environment.limits,
            instructions_hash=content_hash(self.environment.instructions),
            actions_hash=content_hash(self.environment.actions),
            guardrails_hash=content_hash(self.environment.guardrails),
            runtime=self.runtime,
        )
        return JobPlan(
            job_id=self.job_id, spec_hash=self.content_hash, lock=lock, trials=tuple(trials)
        )


class TrialSpec(FrozenModel):
    """One independent attempt for one agent and environment-owned task."""

    job_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    environment: EnvironmentIdentity
    harness: HarnessBinding | None = None
    instance_id: str | None = None
    runtime: RuntimeSpec

    @property
    def trial_id(self) -> str:
        """Stable trial identifier independent of execution retries."""
        return stable_id(
            "trl",
            {
                "job_id": self.job_id,
                "agent_id": self.agent_id,
                "task_id": self.task_id,
                "attempt": self.attempt,
            },
        )


class JobLock(FrozenModel):
    """Immutable content lock captured when a job is planned."""

    job_id: str
    spec_hash: str
    environment: EnvironmentIdentity
    benchmark_hash: str
    task_set_hash: str
    agent_hashes: tuple[str, ...]
    harness_digests: tuple[str, ...]
    environment_source_digest: str | None = None
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    instructions_hash: str = ""
    actions_hash: str = ""
    guardrails_hash: str = ""
    runtime: RuntimeSpec


class JobPlan(FrozenModel):
    """Deterministically ordered trial expansion and package locks."""

    job_id: str
    spec_hash: str
    lock: JobLock
    trials: tuple[TrialSpec, ...]

    @property
    def trial_count(self) -> int:
        """Exact number of independent trials."""
        return len(self.trials)


class TrialReceipt(FrozenModel):
    """Execution provenance for one trial."""

    trial_id: str
    job_id: str
    retry_count: int = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1)
    environment_digest: str
    benchmark_digest: str = ""
    agent_digest: str = ""
    harness_digest: str = ""
    runtime_provider: str
    runtime_identity: str = ""
    effective_capabilities: tuple[str, ...] = ()
    effective_policy: dict[str, Any] = Field(default_factory=dict)
    image_identity: str | None = None
    task_hash: str = ""
    trace_hash: str | None = None
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    verifier_hash: str | None = None
    source_receipt_hash: str | None = None
    trust: Literal["self_reported"] = "self_reported"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    instructions_hash: str = ""
    actions_hash: str = ""
    environment_source_digest: str | None = None
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    guardrails: tuple[Guardrail, ...] = ()
    agent_instance_id: str | None = None
    harness_implementation: Literal["declared", "runnable"] | None = None
    granted_capabilities: tuple[str, ...] = ()

    @property
    def receipt_hash(self) -> str:
        """Integrity digest for the complete receipt."""
        return content_hash(self)


class TrialResult(FrozenModel):
    """Typed trial outcome plus immutable execution receipt."""

    status: Literal["succeeded", "failed", "cancelled"]
    receipt: TrialReceipt
    reward: float | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    trace_id: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _failure_shape(self) -> TrialResult:
        if self.status == "succeeded" and self.error_code is not None:
            raise ValueError("successful trials cannot have an error_code")
        if self.status == "failed" and self.error_code is None:
            raise ValueError("failed trials require a stable error_code")
        return self


class JobResult(FrozenModel):
    """Collected trial outcomes for one locked job."""

    job_id: str
    plan_hash: str
    trials: tuple[TrialResult, ...]


_NETWORK_NONE_DENIALS = frozenset(
    {
        HarnessCapability.WEB_SEARCH,
        HarnessCapability.BROWSER,
        HarnessCapability.NETWORK_FETCH,
        HarnessCapability.MCP,
    }
)
_NETWORK_RESTRICTED_DENIALS = frozenset(
    {HarnessCapability.WEB_SEARCH, HarnessCapability.BROWSER}
)


def resolve_harness_stamp(
    environment: EnvironmentManifest,
    harness: HarnessPackage | HarnessManifest,
) -> HarnessStamp:
    """Compute the frozen effective capability set for one harness on one environment."""
    manifest = harness.manifest if isinstance(harness, HarnessPackage) else harness
    binding = (
        HarnessBinding.from_package(harness)
        if isinstance(harness, HarnessPackage)
        else HarnessBinding(
            name=manifest.name,
            revision=manifest.version,
            digest=content_hash(manifest),
        )
    )
    declared = frozenset(manifest.capabilities)
    denied: set[HarnessCapability] = set()
    reasons: dict[str, str] = {}

    def _deny(capability: HarnessCapability, reason: str) -> None:
        if capability in declared and capability not in denied:
            denied.add(capability)
            reasons[capability.value] = reason

    for capability in environment.harness_policy.denied_capabilities:
        _deny(capability, "environment denied")
    allowed = environment.harness_policy.allowed_capabilities
    if allowed is not None:
        for capability in declared:
            if capability not in allowed:
                _deny(capability, "not in environment allowlist")
    network = environment.runtime.network
    if network is NetworkMode.NONE:
        for capability in _NETWORK_NONE_DENIALS:
            _deny(capability, "environment network=none")
    elif network is NetworkMode.RESTRICTED:
        for capability in _NETWORK_RESTRICTED_DENIALS:
            _deny(capability, "environment network=restricted")
    if environment.runtime.read_only_root:
        _deny(HarnessCapability.FILE_EDIT, "environment read_only_root")
    granted = frozenset(capability for capability in declared if capability not in denied)
    return HarnessStamp(
        environment=environment.identity,
        harness=binding,
        declared=declared,
        granted=granted,
        denied=frozenset(denied),
        denial_reasons=reasons,
    )


def validate_job_compatibility(
    environment: EnvironmentManifest,
    benchmark: BenchmarkDefinition,
    agents: tuple[AgentBinding, ...],
) -> None:
    """Validate environment ownership and exact agent/harness compatibility."""
    if benchmark.environment != environment.identity:
        raise ValueError("benchmark environment identity does not match environment manifest")
    owned_tasks = {task.task_id for task in environment.tasks}
    missing = [task_id for task_id in benchmark.task_ids if task_id not in owned_tasks]
    if missing:
        raise ValueError(f"benchmark selects tasks not owned by environment: {missing!r}")
    allowed = set(environment.harness_policy.allowed_harnesses)
    for agent in agents:
        template = agent.template
        if template.environment != benchmark.environment:
            raise ValueError(f"agent {template.name!r} targets a different environment identity")
        if template.harness is None:
            if template.stamp is not None:
                raise ValueError(f"agent {template.name!r} stamp requires a harness")
            continue
        if environment.harness_policy.mode == "allowlist" and template.harness not in allowed:
            raise ValueError(f"agent {template.name!r} harness is not allowed by the environment")
        package = template.harness_package
        if package is not None:
            if package.manifest.implementation == "declared":
                raise ValueError(
                    f"harness {package.manifest.name} is declared but not runnable"
                )
            expected = resolve_harness_stamp(environment, package)
            if template.stamp != expected:
                raise ValueError(f"agent {template.name!r} harness stamp is stale")
            if not expected.granted:
                raise ValueError(
                    f"agent {template.name!r} harness has no granted capabilities"
                )
        elif template.stamp is None:
            raise ValueError(f"agent {template.name!r} stamped harness requires a stamp")


__all__ = [
    "AgentBinding",
    "AgentInstanceRef",
    "AgentTemplate",
    "BenchmarkDefinition",
    "BenchmarkSpec",
    "EnvironmentIdentity",
    "EnvironmentManifest",
    "EnvironmentResource",
    "EnvironmentRuntime",
    "ErrorCode",
    "ExecutionLimits",
    "ExecutionTarget",
    "FileDeclaration",
    "Guardrail",
    "HarnessBinding",
    "HarnessCapability",
    "HarnessManifest",
    "HarnessPackage",
    "HarnessPolicy",
    "HarnessStamp",
    "JobLock",
    "JobPlan",
    "JobResult",
    "JobSpec",
    "NativeAction",
    "PackageSource",
    "RetryPolicy",
    "RoutingSpec",
    "RuntimeSpec",
    "TaskDefinition",
    "TrialReceipt",
    "TrialResult",
    "TrialSpec",
    "VerifierManifest",
    "canonical_json",
    "content_hash",
    "resolve_harness_stamp",
    "stable_id",
    "validate_job_compatibility",
]
