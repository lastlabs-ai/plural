"""Five-layer effective execution policy.

Provider capability, project policy, environment constraints, harness
requirements, and the agent request are intersected here. Each layer may only
narrow. Unsatisfiable requirements raise ``CapabilityError`` before a sandbox
is created and name the blame layer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from plural.domain import (
    AgentTemplate,
    EnvironmentManifest,
    ExecutionTarget,
    FrozenModel,
    HarnessCapability,
    HarnessStamp,
)
from plural.sandbox.models import (
    Capability,
    CapabilityError,
    EffectiveSandboxPolicy,
    NetworkMode,
    ProviderCapabilities,
    ResourceRequirements,
    SandboxRequirements,
    environment_required_capabilities,
)

PolicyLayer = Literal["provider", "project", "environment", "harness", "agent"]

_NETWORK_RANK = {
    NetworkMode.NONE: 0,
    NetworkMode.RESTRICTED: 1,
    NetworkMode.FULL: 2,
}


class PolicyDenial(FrozenModel):
    """One capability removed by a named policy layer."""

    capability: str
    layer: PolicyLayer
    reason: str


class ProjectPolicy(FrozenModel):
    """Project-level ceiling an environment may narrow but never exceed."""

    allowed_targets: frozenset[ExecutionTarget] = Field(
        default_factory=lambda: frozenset({ExecutionTarget.DOCKER, ExecutionTarget.REMOTE})
    )
    network_ceiling: NetworkMode = NetworkMode.FULL
    max_cpu: float | None = Field(default=None, gt=0)
    max_memory_mb: int | None = Field(default=None, gt=0)
    max_disk_mb: int | None = Field(default=None, gt=0)
    allowed_harness_capabilities: frozenset[HarnessCapability] | None = None
    allow_unsafe_local: bool = False

    @classmethod
    def permissive(cls, *, allow_unsafe_local: bool = False) -> ProjectPolicy:
        """Return a project policy that does not add extra ceilings."""
        return cls(
            allowed_targets=frozenset(ExecutionTarget),
            network_ceiling=NetworkMode.FULL,
            allow_unsafe_local=allow_unsafe_local,
        )


class EffectivePolicy(EffectiveSandboxPolicy):
    """Resolved launch policy frozen into receipts and preflight responses."""

    target: ExecutionTarget
    granted_harness_capabilities: frozenset[HarnessCapability] = frozenset()
    trust: Literal["self_reported"] = "self_reported"
    denials: tuple[PolicyDenial, ...] = ()


def _narrower_network(left: NetworkMode, right: NetworkMode) -> NetworkMode:
    return left if _NETWORK_RANK[left] <= _NETWORK_RANK[right] else right


def _cap_resources(
    requested: ResourceRequirements,
    project: ProjectPolicy,
    denials: list[PolicyDenial],
) -> ResourceRequirements:
    cpu = requested.cpu
    memory_mb = requested.memory_mb
    disk_mb = requested.disk_mb
    if cpu is not None and project.max_cpu is not None and cpu > project.max_cpu:
        denials.append(
            PolicyDenial(
                capability="resources",
                layer="project",
                reason=f"project max_cpu={project.max_cpu} caps environment cpu={cpu}",
            )
        )
        cpu = project.max_cpu
    if (
        memory_mb is not None
        and project.max_memory_mb is not None
        and memory_mb > project.max_memory_mb
    ):
        denials.append(
            PolicyDenial(
                capability="resources",
                layer="project",
                reason=(
                    f"project max_memory_mb={project.max_memory_mb} "
                    f"caps environment memory_mb={memory_mb}"
                ),
            )
        )
        memory_mb = project.max_memory_mb
    if disk_mb is not None and project.max_disk_mb is not None and disk_mb > project.max_disk_mb:
        denials.append(
            PolicyDenial(
                capability="resources",
                layer="project",
                reason=(
                    f"project max_disk_mb={project.max_disk_mb} "
                    f"caps environment disk_mb={disk_mb}"
                ),
            )
        )
        disk_mb = project.max_disk_mb
    return ResourceRequirements(
        cpu=cpu,
        memory_mb=memory_mb,
        pids=requested.pids,
        disk_mb=disk_mb,
    )


def sandbox_requirements_for(
    environment: EnvironmentManifest,
    *,
    network: NetworkMode | None = None,
    resources: ResourceRequirements | None = None,
    verifier: bool = False,
    harness_digest: str | None = None,
) -> SandboxRequirements:
    """Build sandbox requirements from an environment runtime."""
    runtime = environment.runtime
    identity = environment.identity.digest
    if harness_digest:
        identity = f"{identity}:{harness_digest}"
    if verifier:
        return SandboxRequirements(
            image=environment.verifier.image if environment.verifier else runtime.image,
            snapshot=None,
            declarative_image=None,
            execution_identity=identity,
            build_context=None,
            dockerfile=None,
            resources=resources or runtime.resources,
            network=NetworkMode.NONE,
            network_allowlist=(),
            timeout_seconds=(
                environment.verifier.timeout_seconds
                if environment.verifier
                else runtime.timeout_seconds
            ),
            persistent=False,
            compose=False,
            read_only_root=runtime.read_only_root,
        )
    return SandboxRequirements(
        image=runtime.image,
        snapshot=runtime.snapshot,
        declarative_image=runtime.declarative_image,
        execution_identity=identity,
        build_context=runtime.build_context,
        dockerfile=runtime.dockerfile,
        resources=resources or runtime.resources,
        network=network if network is not None else runtime.network,
        network_allowlist=() if network is NetworkMode.NONE else runtime.network_allowlist,
        timeout_seconds=runtime.timeout_seconds,
        persistent=runtime.persistent,
        compose=runtime.compose,
        read_only_root=runtime.read_only_root,
    )


def resolve_effective_policy(
    *,
    environment: EnvironmentManifest,
    template: AgentTemplate,
    stamp: HarnessStamp | None,
    project: ProjectPolicy,
    provider: ProviderCapabilities,
    requested_target: ExecutionTarget,
) -> EffectivePolicy:
    """Intersect all five layers or raise CapabilityError naming the blame layer."""
    denials: list[PolicyDenial] = []

    if not provider.available:
        raise CapabilityError(
            f"provider '{provider.provider}' is unavailable"
            + (f": {provider.reason}" if provider.reason else ""),
            # CapabilityError is a SandboxError; message names the provider layer.
        )

    if requested_target not in project.allowed_targets:
        raise CapabilityError(
            f"target {requested_target.value} required by agent "
            f"is not allowed by project policy"
        )

    if requested_target is ExecutionTarget.LOCAL and not project.allow_unsafe_local:
        raise CapabilityError(
            "unsafe local execution required by agent is not allowed by project policy"
        )

    if requested_target not in environment.runtime.targets:
        raise CapabilityError(
            f"target {requested_target.value} required by agent "
            f"is not declared by environment '{environment.name}'"
        )

    exclusions = environment.runtime.target_exclusions()
    if requested_target in exclusions:
        raise CapabilityError(
            f"{exclusions[requested_target]} required by environment "
            f"'{environment.name}' is not enforceable by target '{requested_target.value}'"
        )

    if requested_target is ExecutionTarget.LOCAL and not environment.runtime.allow_unsafe_local:
        raise CapabilityError(
            f"unsafe local execution required by agent is not allowed by "
            f"environment '{environment.name}'"
        )

    env_network = environment.runtime.network
    effective_network = _narrower_network(env_network, project.network_ceiling)
    if _NETWORK_RANK[env_network] > _NETWORK_RANK[project.network_ceiling]:
        denials.append(
            PolicyDenial(
                capability=f"network_{env_network.value}",
                layer="project",
                reason=f"project network ceiling is {project.network_ceiling.value}",
            )
        )

    resources = _cap_resources(environment.runtime.resources, project, denials)
    requirements = sandbox_requirements_for(
        environment,
        network=effective_network,
        resources=resources,
    )

    required = requirements.required_capabilities() | environment_required_capabilities(
        environment.runtime
    )
    if effective_network is NetworkMode.NONE:
        required = required | {Capability.NETWORK_NONE}
    missing = required - provider.capabilities
    if missing:
        capability = sorted(item.value for item in missing)[0]
        raise CapabilityError(
            f"{capability} required by environment '{environment.name}' "
            f"is not enforceable by provider '{provider.provider}'"
        )

    granted: frozenset[HarnessCapability] = stamp.granted if stamp is not None else frozenset()
    if stamp is not None:
        if template.harness is None:
            raise CapabilityError(
                "harness stamp required by agent does not match a native template"
            )
        if project.allowed_harness_capabilities is not None:
            blocked = stamp.granted - project.allowed_harness_capabilities
            if blocked:
                for capability in sorted(blocked, key=lambda item: item.value):
                    denials.append(
                        PolicyDenial(
                            capability=capability.value,
                            layer="project",
                            reason="not in project allowed_harness_capabilities",
                        )
                    )
                granted = stamp.granted & project.allowed_harness_capabilities
            if not granted:
                raise CapabilityError(
                    f"harness {stamp.harness.name} required by agent "
                    f"has no granted capabilities after project policy"
                )

    _ = template  # template routing/secrets are validated at job compatibility
    return EffectivePolicy(
        provider=provider.provider,
        requirements=requirements,
        enforced=required & provider.capabilities,
        target=requested_target,
        granted_harness_capabilities=granted,
        denials=tuple(denials),
    )


def policy_case_environment(payload: dict[str, Any]) -> EnvironmentManifest:
    """Build a minimal environment from a shared policy fixture case."""
    runtime = payload.get("runtime") or {}
    return EnvironmentManifest(
        name=str(payload.get("name") or "env"),
        runtime=runtime,
        actions=tuple(payload.get("actions") or ()),
        harness_policy=payload.get("harness_policy") or {},
    )


def policy_case_template(
    environment: EnvironmentManifest,
    payload: dict[str, Any],
    stamp: HarnessStamp | None,
) -> AgentTemplate:
    """Build a minimal agent template from a shared policy fixture case."""
    harness = payload.get("harness")
    return AgentTemplate(
        name=str(payload.get("name") or "agent"),
        model=str(payload.get("model") or "openai/gpt-4.1-mini"),
        environment=environment.identity,
        harness=harness,
        stamp=stamp,
    )
