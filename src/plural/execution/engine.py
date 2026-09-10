"""Deterministic client-orchestrated Job and Trial execution."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import math
import os
import statistics
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from plural.benchmarks import CaseKey, CaseResult, ModelStats, Report, RunManifest
from plural.domain import (
    AgentBinding,
    ErrorCode,
    HarnessPackage,
    JobResult,
    JobSpec,
    TaskDefinition,
    TrialReceipt,
    TrialResult,
    TrialSpec,
    content_hash,
)
from plural.execution.policy import (
    ProjectPolicy,
    resolve_effective_policy,
    sandbox_requirements_for,
)
from plural.execution.store import JobStore
from plural.harness import (
    BUILTIN_PROFILES,
    HarnessExecutionError,
    HarnessProtocolError,
    HarnessRunner,
    HarnessRunRequest,
    native_actions_v1,
    native_chat_v1,
)
from plural.harness.retrieval import materialize_package, retrieve_archive, tree_digest
from plural.sandbox import (
    CapabilityError,
    DownloadedFile,
    FileUpload,
    ProviderRegistry,
    SandboxError,
    SandboxHandle,
    SandboxProvider,
    SandboxRequirements,
    default_registry,
)


class VerifierOutput(BaseModel):
    """Strict score document produced only by an isolated verifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reward: float | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()

    def validated_finite(self) -> VerifierOutput:
        """Reject non-finite numeric evidence."""
        values = [*self.scores.values()]
        if self.reward is not None:
            values.append(self.reward)
        if any(not math.isfinite(item) for item in values):
            raise ValueError("verifier emitted non-finite scores")
        return self


class ExecutionFailure(RuntimeError):
    """Internal typed failure used to drive retry policy."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _requirements(
    spec: JobSpec,
    *,
    verifier: bool = False,
    harness_digest: str | None = None,
) -> SandboxRequirements:
    requirements = sandbox_requirements_for(
        spec.environment,
        verifier=verifier,
        harness_digest=harness_digest,
    )
    timeout = min(
        requirements.timeout_seconds or spec.runtime.timeout_seconds,
        spec.runtime.timeout_seconds,
    )
    return requirements.model_copy(update={"timeout_seconds": timeout})


def _classify(exc: BaseException) -> ErrorCode:
    if isinstance(exc, ExecutionFailure):
        return exc.code
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return ErrorCode.TIMEOUT
    if isinstance(exc, HarnessProtocolError):
        return ErrorCode.PROTOCOL_FAILED
    if isinstance(exc, HarnessExecutionError) and "denied capability" in str(exc):
        return ErrorCode.PROTOCOL_FAILED
    if isinstance(exc, HarnessExecutionError):
        return ErrorCode.HARNESS_FAILED
    if isinstance(exc, CapabilityError):
        return ErrorCode.RUNTIME_UNAVAILABLE
    if isinstance(exc, SandboxError):
        return ErrorCode.RUNTIME_UNAVAILABLE
    if isinstance(exc, asyncio.CancelledError):
        return ErrorCode.CANCELLED
    if isinstance(exc, (ValueError, FileNotFoundError)):
        return ErrorCode.CONFIGURATION
    return ErrorCode.INTERNAL


def _package_requirements(spec: JobSpec, package: HarnessPackage) -> SandboxRequirements:
    requirements = _requirements(
        spec,
        harness_digest=package.source.digest or package.content_hash,
    )
    if package.source.kind != "oci":
        return requirements
    env_runtime = spec.environment.runtime
    if (
        env_runtime.image
        or env_runtime.snapshot
        or env_runtime.declarative_image
        or env_runtime.build_context
    ):
        raise CapabilityError(
            "OCI harness image composition with a separate environment image is unsupported; "
            "use the digest-pinned harness image as the runtime image"
        )
    if package.source.digest is None:  # pragma: no cover - model invariant
        raise ValueError("OCI harness requires a digest")
    reference = (
        package.source.uri
        if "@sha256:" in package.source.uri
        else f"{package.source.uri}@{package.source.digest}"
    )
    return requirements.model_copy(
        update={"image": reference, "build_context": None, "dockerfile": None}
    )


def _package_for(agent: AgentBinding, spec: JobSpec | None = None) -> HarnessPackage:
    if agent.harness_package is not None:
        return agent.harness_package
    if agent.harness is None:
        environment = spec.environment if spec is not None else None
        if environment is not None and environment.actions:
            return native_actions_v1()
        return native_chat_v1()
    factory = BUILTIN_PROFILES.get(agent.harness.name)
    if factory is None:
        raise ExecutionFailure(
            ErrorCode.CONFIGURATION,
            f"agent {agent.name!r} has no executable harness_package",
        )
    package = factory()
    if package.manifest.version != agent.harness.revision:
        raise ExecutionFailure(ErrorCode.CONFIGURATION, "built-in harness revision does not match")
    return package


def _harness_environment(
    agent: AgentBinding,
    package: HarnessPackage,
    environ: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    missing = [name for name in agent.secret_names if not environ.get(name)]
    if missing:
        raise ExecutionFailure(
            ErrorCode.AUTHENTICATION,
            f"missing declared harness secrets: {missing!r}",
        )
    secrets = {name: environ[name] for name in agent.secret_names}
    configured = {
        name: environ[name]
        for name in package.manifest.environment_names
        if environ.get(name) is not None
    }
    return {**configured, **secrets}, secrets


def _validate_harness_preflight(
    spec: JobSpec, agent: AgentBinding, package: HarnessPackage
) -> None:
    manifest = package.manifest
    if manifest.implementation == "declared":
        raise ExecutionFailure(
            ErrorCode.CONFIGURATION,
            f"harness {manifest.name} is declared but not runnable",
        )
    if not any(fnmatch.fnmatchcase(agent.model, pattern) for pattern in manifest.supported_models):
        raise CapabilityError(
            f"harness {manifest.name!r} does not support model {agent.model!r}; "
            f"supported patterns: {list(manifest.supported_models)!r}"
        )
    if agent.auth_mode not in manifest.auth_modes:
        raise CapabilityError(
            f"harness {manifest.name!r} does not support auth mode {agent.auth_mode!r}"
        )
    undeclared_secrets = set(agent.secret_names) - set(manifest.secret_names)
    if undeclared_secrets:
        raise CapabilityError(
            f"agent requests undeclared harness secrets: {sorted(undeclared_secrets)!r}"
        )
    stamp = agent.stamp
    if stamp is not None and not stamp.granted:
        raise CapabilityError(f"agent {agent.name!r} harness has no granted capabilities")


def _environment_payload(spec: JobSpec, *, stamped: bool) -> dict[str, Any]:
    payload = {
        "name": spec.environment.name,
        "instructions": spec.environment.instructions,
        "context": spec.environment.context,
        "limits": spec.environment.limits.model_dump(mode="json"),
        "guardrails": [item.model_dump(mode="json") for item in spec.environment.guardrails],
        "resources": [item.model_dump(mode="json") for item in spec.environment.resources],
        "workspace": "/workspace/environment",
    }
    if not stamped:
        payload["actions"] = [item.model_dump(mode="json") for item in spec.environment.actions]
    return payload


def _redact_bytes(value: bytes, secrets: Mapping[str, str]) -> bytes:
    output = value
    for secret in secrets.values():
        if secret:
            output = output.replace(secret.encode(), b"***")
    return output


class Trial:
    """Public runtime API for one immutable trial."""

    def __init__(
        self,
        spec: TrialSpec,
        *,
        job_spec: JobSpec,
        provider: SandboxProvider,
        store: JobStore,
        environ: Mapping[str, str] | None = None,
        project_policy: ProjectPolicy | None = None,
    ) -> None:
        self.spec = spec
        self.job_spec = job_spec
        self.provider = provider
        self.store = store
        self.environ = os.environ if environ is None else environ
        self.project_policy = project_policy or ProjectPolicy.permissive(
            allow_unsafe_local=job_spec.runtime.unsafe_local
        )
        self._active: dict[str, SandboxHandle] = {}

    async def cancel(self) -> None:
        """Force cancellation of all sandboxes owned by this trial."""
        await asyncio.gather(
            *(self.provider.cancel(handle) for handle in tuple(self._active.values())),
            return_exceptions=True,
        )

    async def run(self, retry: int = 0, *, execution_id: int | None = None) -> TrialResult:
        """Run one fresh agent sandbox and optional isolated verifier."""
        started = datetime.now(timezone.utc)
        clock = time.monotonic()
        agent = next(item for item in self.job_spec.agents if item.agent_id == self.spec.agent_id)
        task = next(
            item for item in self.job_spec.environment.tasks if item.task_id == self.spec.task_id
        )
        package = _package_for(agent, self.job_spec)
        secrets: dict[str, str] = {}
        harness_env: dict[str, str] = {}
        stdout = b""
        stderr = b""
        verifier_stdout = b""
        verifier_stderr = b""
        artifacts: tuple[DownloadedFile, ...] = ()
        image_identity: str | None = None
        effective: dict[str, Any] = {}
        harness_duration = 0.0
        verifier_duration = 0.0
        try:
            harness_env, secrets = _harness_environment(agent, package, self.environ)
            if self.provider.name == "local" and not self.job_spec.runtime.unsafe_local:
                raise ExecutionFailure(
                    ErrorCode.CONFIGURATION,
                    "local execution requires runtime.unsafe_local=true or --unsafe-local",
                )
            source = materialize_package(package)
            if package.source.kind == "oci" and self.provider.name != "docker":
                raise ExecutionFailure(
                    ErrorCode.RUNTIME_UNAVAILABLE,
                    "OCI harness images currently require DockerProvider",
                )
            if package.source.digest is None and not self.job_spec.runtime.unsafe_local:
                raise ExecutionFailure(
                    ErrorCode.CONFIGURATION,
                    "unsigned local harness execution requires explicit unsafe opt-in",
                )
            if (
                package.source.kind == "local"
                and package.source.unsafe_local
                and not self.job_spec.runtime.unsafe_local
            ):
                raise ExecutionFailure(
                    ErrorCode.CONFIGURATION,
                    "local development harness requires explicit unsafe opt-in",
                )
            if agent.harness is not None:
                _validate_harness_preflight(self.job_spec, agent, package)
            if (
                package.source.kind == "local"
                and source is not None
                and package.source.digest is not None
                and tree_digest(source) != package.source.digest
            ):
                raise ExecutionFailure(
                    ErrorCode.CONFIGURATION,
                    "local harness source digest does not match its lock",
                )
            declared = await self.provider.capabilities()
            resolved = resolve_effective_policy(
                environment=self.job_spec.environment,
                template=agent.template,
                stamp=agent.stamp,
                project=self.project_policy,
                provider=declared,
                requested_target=self.job_spec.runtime.requested_target,
            )
            requirements = _package_requirements(self.job_spec, package)
            requirements = resolved.requirements.model_copy(
                update={
                    "image": requirements.image,
                    "snapshot": requirements.snapshot,
                    "declarative_image": requirements.declarative_image,
                    "execution_identity": requirements.execution_identity,
                    "build_context": requirements.build_context,
                    "dockerfile": requirements.dockerfile,
                    "timeout_seconds": requirements.timeout_seconds,
                }
            )
            await self.provider.preflight(requirements)
            effective = resolved.model_dump(mode="json")
            effective["enforced"] = sorted(item.value for item in resolved.enforced)
            handle = await self.provider.create(requirements)
            self._active[handle.sandbox_id] = handle
            image_identity = handle.image_identity
            try:
                await self.provider.upload_files(
                    handle,
                    (
                        FileUpload(
                            path=".plural/execution-identity",
                            data=requirements.execution_identity.encode()
                            if requirements.execution_identity
                            else b"",
                        ),
                    ),
                    root="/workspace/harness",
                )
                if source is not None:
                    await self.provider.upload_bundle(handle, source, root="/workspace/harness")
                environment_source = self.job_spec.environment.source
                if environment_source is not None:
                    if environment_source.kind == "oci":
                        raise ExecutionFailure(
                            ErrorCode.CONFIGURATION,
                            "OCI environment source staging is unsupported",
                        )
                    environment_root = (
                        Path(environment_source.uri).expanduser().resolve()
                        if environment_source.kind == "local"
                        else retrieve_archive(
                            environment_source.uri,
                            environment_source.digest or "",
                        )
                    )
                    await self.provider.upload_bundle(
                        handle,
                        environment_root,
                        root="/workspace/environment",
                    )
                request = HarnessRunRequest(
                    request_id=self.spec.trial_id,
                    task=task.public_payload,
                    agent={
                        "agent_id": agent.agent_id,
                        "name": agent.name,
                        "model": agent.model,
                        "routing": agent.routing.model_dump(mode="json", exclude_none=True),
                    },
                    environment=_environment_payload(
                        self.job_spec,
                        stamped=agent.harness is not None,
                    ),
                    workspace="/workspace/harness",
                    granted_capabilities=tuple(
                        sorted(item.value for item in agent.stamp.granted)
                    )
                    if agent.stamp is not None
                    else (),
                    denied_capabilities=tuple(
                        sorted(item.value for item in agent.stamp.denied)
                    )
                    if agent.stamp is not None
                    else (),
                )
                execution = await HarnessRunner(self.provider).run(
                    handle,
                    package.manifest,
                    request,
                    env=harness_env,
                    timeout_seconds=min(
                        self.job_spec.runtime.timeout_seconds,
                        self.job_spec.environment.limits.max_seconds,
                    ),
                )
                stdout = _redact_bytes(execution.stdout, secrets)
                stderr = _redact_bytes(execution.stderr, secrets)
                harness_duration = execution.duration_seconds
                paths = tuple(dict.fromkeys((*execution.output_paths, *execution.artifact_paths)))
                artifacts = await self.provider.download_artifacts(
                    handle,
                    paths,
                    root="/workspace/harness",
                )
            finally:
                self._active.pop(handle.sandbox_id, None)
                await self.provider.destroy(handle)
            verifier = self.job_spec.environment.verifier
            verifier_output: VerifierOutput | None = None
            verifier_hash: str | None = None
            if verifier is not None:
                (
                    verifier_output,
                    verifier_stdout,
                    verifier_stderr,
                    verifier_duration,
                ) = await self._verify(task, artifacts)
                verifier_hash = content_hash(verifier_output)
            receipt = self._receipt(
                agent=agent,
                task=task,
                package=package,
                retry=retry,
                started=started,
                image_identity=image_identity,
                effective=effective,
                artifacts=artifacts,
                trace_id=execution.trace_id,
                verifier_hash=verifier_hash,
                timings={
                    "total_seconds": time.monotonic() - clock,
                    "harness_seconds": harness_duration,
                    "verifier_seconds": verifier_duration,
                },
            )
            result = TrialResult(
                status="succeeded",
                receipt=receipt,
                reward=verifier_output.reward if verifier_output else None,
                scores=verifier_output.scores if verifier_output else {},
                trace_id=execution.trace_id,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, HarnessExecutionError):
                stdout = _redact_bytes(exc.stdout, secrets)
                stderr = _redact_bytes(exc.stderr, secrets)
            code = _classify(exc)
            receipt = self._receipt(
                agent=agent,
                task=task,
                package=package,
                retry=retry,
                started=started,
                image_identity=image_identity,
                effective=effective,
                artifacts=artifacts,
                trace_id=None,
                verifier_hash=None,
                timings={"total_seconds": time.monotonic() - clock},
            )
            result = TrialResult(
                status="cancelled" if code is ErrorCode.CANCELLED else "failed",
                receipt=receipt,
                error_code=None if code is ErrorCode.CANCELLED else code,
                error_message=_redact_bytes(str(exc).encode(), secrets).decode(errors="replace")[
                    :1000
                ],
            )
        resolved_execution_id = (
            self.store.next_execution_id(self.spec) if execution_id is None else execution_id
        )
        self.store.write_trial_attempt(
            self.spec,
            resolved_execution_id,
            result,
            stdout=stdout,
            stderr=stderr,
            artifacts=artifacts,
            verifier_stdout=verifier_stdout,
            verifier_stderr=verifier_stderr,
        )
        return result

    async def _verify(
        self, task: TaskDefinition, artifacts: tuple[DownloadedFile, ...]
    ) -> tuple[VerifierOutput, bytes, bytes, float]:
        verifier = self.job_spec.environment.verifier
        if verifier is None:  # pragma: no cover - caller invariant
            raise RuntimeError("verifier is not configured")
        present = {item.path for item in artifacts}
        missing = set(verifier.required_artifacts) - present
        if missing:
            raise ExecutionFailure(
                ErrorCode.EVIDENCE_MISSING,
                f"required verifier artifacts are missing: {sorted(missing)!r}",
            )
        requirements = _requirements(self.job_spec, verifier=True)
        await self.provider.preflight(requirements)
        handle = await self.provider.create(requirements)
        self._active[handle.sandbox_id] = handle
        try:
            hidden = json.dumps(
                {
                    "task": task.public_payload,
                    "expected": task.expected,
                    "verifier_input": task.verifier_input,
                    "artifacts": [item.path for item in artifacts],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            uploads = [
                FileUpload(path=".plural/verifier-input.json", data=hidden),
                *(FileUpload(path=f"artifacts/{item.path}", data=item.data) for item in artifacts),
            ]
            await self.provider.upload_files(handle, uploads)
            execution = await self.provider.exec(
                handle,
                request=_verifier_request(verifier.command, verifier.timeout_seconds),
            )
            if execution.timed_out:
                raise ExecutionFailure(ErrorCode.TIMEOUT, "verifier timed out")
            if execution.exit_code != 0:
                raise ExecutionFailure(
                    ErrorCode.VERIFIER_FAILED,
                    f"verifier exited with code {execution.exit_code}",
                )
            files = await self.provider.download_files(handle, (verifier.result_path,))
            if len(files) != 1:
                raise ExecutionFailure(ErrorCode.EVIDENCE_MISSING, "verifier result is missing")
            output = VerifierOutput.model_validate_json(files[0].data).validated_finite()
            if verifier.evidence_required and not output.evidence:
                raise ExecutionFailure(ErrorCode.EVIDENCE_MISSING, "verifier evidence is required")
            return output, execution.stdout, execution.stderr, execution.duration_seconds
        finally:
            self._active.pop(handle.sandbox_id, None)
            await self.provider.destroy(handle)

    def _receipt(
        self,
        *,
        agent: AgentBinding,
        task: TaskDefinition,
        package: HarnessPackage,
        retry: int,
        started: datetime,
        image_identity: str | None,
        effective: dict[str, Any],
        artifacts: tuple[DownloadedFile, ...],
        trace_id: str | None,
        verifier_hash: str | None,
        timings: dict[str, float],
    ) -> TrialReceipt:
        return TrialReceipt(
            trial_id=self.spec.trial_id,
            job_id=self.spec.job_id,
            retry_count=retry,
            attempt=self.spec.attempt,
            environment_digest=self.spec.environment.digest,
            benchmark_digest=self.job_spec.benchmark.content_hash,
            agent_digest=agent.content_hash,
            harness_digest=package.source.digest or package.content_hash,
            runtime_provider=self.provider.name,
            runtime_identity=content_hash(
                {
                    "provider": self.provider.name,
                    "environment": self.spec.environment.digest,
                    "harness": package.source.digest or package.content_hash,
                    "runtime": self.job_spec.runtime,
                }
            ),
            effective_capabilities=tuple(
                sorted(
                    item.value
                    for item in _package_requirements(
                        self.job_spec,
                        package,
                    ).required_capabilities()
                )
            ),
            effective_policy=effective,
            image_identity=image_identity,
            task_hash=content_hash(task),
            trace_hash=content_hash(trace_id) if trace_id else None,
            artifact_hashes={item.path: item.digest for item in artifacts},
            verifier_hash=verifier_hash,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            timings=timings,
            instructions_hash=content_hash(self.job_spec.environment.instructions),
            actions_hash=content_hash(self.job_spec.environment.actions),
            environment_source_digest=(
                self.job_spec.environment.source.digest
                if self.job_spec.environment.source is not None
                else None
            ),
            execution_limits=self.job_spec.environment.limits,
            guardrails=self.job_spec.environment.guardrails,
            agent_instance_id=self.spec.instance_id,
            harness_implementation=(
                package.manifest.implementation if agent.harness is not None else None
            ),
            granted_capabilities=tuple(
                sorted(item.value for item in agent.stamp.granted) if agent.stamp else ()
            ),
        )


def _verifier_request(command: tuple[str, ...], timeout: float) -> Any:
    from plural.sandbox import ExecRequest

    return ExecRequest(command=command, cwd="/workspace", timeout_seconds=timeout)


class Job:
    """Public async API for deterministic multi-trial execution."""

    def __init__(
        self,
        spec: JobSpec,
        *,
        provider: SandboxProvider | None = None,
        registry: ProviderRegistry = default_registry,
        store: JobStore | None = None,
        environ: Mapping[str, str] | None = None,
        progress: Callable[[TrialSpec, TrialResult], None] | None = None,
        project_policy: ProjectPolicy | None = None,
    ) -> None:
        self.spec = spec
        self.plan = spec.plan()
        self.provider = provider or registry.get(spec.runtime.provider)
        self.store = store or JobStore()
        self.environ = os.environ if environ is None else environ
        self.progress = progress
        self.project_policy = project_policy or ProjectPolicy.permissive(
            allow_unsafe_local=spec.runtime.unsafe_local
        )
        self._trials: set[Trial] = set()

    async def cancel(self) -> None:
        """Persist cancellation and force active sandbox cancellation."""
        self.store.request_cancel(self.plan.job_id)
        await asyncio.gather(*(trial.cancel() for trial in tuple(self._trials)))

    async def preflight(self) -> None:
        """Validate package locks and provider controls before any launch."""
        if self.provider.name == "local" and not self.spec.runtime.unsafe_local:
            raise ValueError(
                "local execution is not configured for unsafe subprocess mode; "
                "pass --unsafe-local or set runtime.unsafe_local=true"
            )
        declared = await self.provider.capabilities()
        for agent in self.spec.agents:
            resolve_effective_policy(
                environment=self.spec.environment,
                template=agent.template,
                stamp=agent.stamp,
                project=self.project_policy,
                provider=declared,
                requested_target=self.spec.runtime.requested_target,
            )
        await self.provider.preflight(_requirements(self.spec))
        if self.spec.environment.verifier is not None:
            await self.provider.preflight(_requirements(self.spec, verifier=True))
        environment_source = self.spec.environment.source
        if environment_source is not None:
            if environment_source.kind != "local":
                raise CapabilityError(
                    "only local Environment source staging is currently supported"
                )
            environment_root = Path(environment_source.uri).expanduser().resolve()
            if (
                environment_source.digest is not None
                and tree_digest(environment_root) != environment_source.digest
            ):
                raise ValueError("environment source lock mismatch")
        for agent in self.spec.agents:
            package = _package_for(agent, self.spec)
            if agent.harness is not None:
                _validate_harness_preflight(self.spec, agent, package)
            if package.source.kind == "oci" and self.provider.name != "docker":
                raise CapabilityError("OCI harness images currently require DockerProvider")
            await self.provider.preflight(_package_requirements(self.spec, package))
            source = materialize_package(package)
            if package.source.digest is None and not self.spec.runtime.unsafe_local:
                raise ValueError("unsigned local harness requires explicit unsafe opt-in")
            if (
                package.source.kind == "local"
                and package.source.unsafe_local
                and not self.spec.runtime.unsafe_local
            ):
                raise ValueError("local development harness requires explicit unsafe opt-in")
            if (
                package.source.kind == "local"
                and source is not None
                and package.source.digest is not None
                and tree_digest(source) != package.source.digest
            ):
                raise ValueError(f"harness source lock mismatch for {agent.name!r}")

    async def run(self, *, resume: bool = False) -> JobResult:
        """Execute all locked trials with global and per-agent semaphores."""
        await self.preflight()
        self.store.initialize(self.spec, self.plan)
        if resume:
            self.store.clear_cancel(self.plan.job_id)
        global_limit = asyncio.Semaphore(self.spec.concurrency)
        per_agent = {
            agent.agent_id: asyncio.Semaphore(self.spec.per_agent_concurrency)
            for agent in self.spec.agents
        }
        results: dict[str, TrialResult] = {}

        async def execute(trial_spec: TrialSpec) -> None:
            existing = self.store.successful_result(trial_spec)
            if existing is not None:
                results[trial_spec.trial_id] = existing
                return
            async with per_agent[trial_spec.agent_id], global_limit:
                if self.store.cancel_requested(self.plan.job_id):
                    result = await self._cancelled_result(trial_spec)
                else:
                    trial = Trial(
                        trial_spec,
                        job_spec=self.spec,
                        provider=self.provider,
                        store=self.store,
                        environ=self.environ,
                        project_policy=self.project_policy,
                    )
                    self._trials.add(trial)
                    try:
                        result = await self._run_with_retries(trial)
                    finally:
                        self._trials.discard(trial)
                results[trial_spec.trial_id] = result
                if self.progress is not None:
                    self.progress(trial_spec, result)

        await asyncio.gather(*(execute(trial) for trial in self.plan.trials))
        ordered = tuple(results[trial.trial_id] for trial in self.plan.trials)
        result = JobResult(
            job_id=self.plan.job_id,
            plan_hash=content_hash(self.plan),
            trials=ordered,
        )
        self.store.write_job_result(result)
        return result

    async def regrade(self) -> JobResult:
        """Rerun only isolated verifiers against immutable stored artifacts.

        Returns:
            Updated ordered job result.
        """
        if self.spec.environment.verifier is None:
            raise ValueError("job environment has no verifier")
        await self.provider.preflight(_requirements(self.spec, verifier=True))
        self.store.initialize(self.spec, self.plan)
        results: list[TrialResult] = []
        for trial_spec in self.plan.trials:
            source = self.store.successful_result(trial_spec)
            if source is None:
                raise ValueError(f"trial {trial_spec.trial_id} has no successful source receipt")
            task = next(
                item for item in self.spec.environment.tasks if item.task_id == trial_spec.task_id
            )
            artifacts = self.store.artifact_files(trial_spec)
            runtime = Trial(
                trial_spec,
                job_spec=self.spec,
                provider=self.provider,
                store=self.store,
                environ=self.environ,
                project_policy=self.project_policy,
            )
            started = time.monotonic()
            output, stdout, stderr, duration = await runtime._verify(task, artifacts)
            receipt = source.receipt.model_copy(
                update={
                    "verifier_hash": content_hash(output),
                    "source_receipt_hash": source.receipt.receipt_hash,
                    "completed_at": datetime.now(timezone.utc),
                    "timings": {
                        **source.receipt.timings,
                        "regrade_seconds": duration,
                        "regrade_total_seconds": time.monotonic() - started,
                    },
                }
            )
            result = TrialResult(
                status="succeeded",
                receipt=receipt,
                reward=output.reward,
                scores=output.scores,
                trace_id=source.trace_id,
            )
            self.store.write_regrade(
                trial_spec,
                result,
                verifier_stdout=stdout,
                verifier_stderr=stderr,
            )
            results.append(result)
        aggregate = JobResult(
            job_id=self.plan.job_id,
            plan_hash=content_hash(self.plan),
            trials=tuple(results),
        )
        self.store.write_job_result(aggregate)
        return aggregate

    def report(self, result: JobResult) -> Report:
        """Aggregate execution results into the established Report shape.

        Returns:
            Benchmark report preserving ordered trial cases.
        """
        if result.job_id != self.plan.job_id:
            raise ValueError("job result does not match this job")
        cases: list[CaseResult] = []
        by_agent: dict[str, list[TrialResult]] = {agent.name: [] for agent in self.spec.agents}
        for trial_spec, trial_result in zip(self.plan.trials, result.trials, strict=True):
            by_agent[trial_spec.agent_name].append(trial_result)
            cases.append(
                CaseResult(
                    key=CaseKey(
                        model=trial_spec.agent_name,
                        task_id=trial_spec.task_id,
                        repeat=trial_spec.attempt - 1,
                    ),
                    trace_id=trial_result.trace_id,
                    reward=trial_result.reward,
                    scores=trial_result.scores,
                    failure_type=(
                        trial_result.error_code.value
                        if trial_result.error_code is not None
                        else None
                    ),
                    failure_message=trial_result.error_message,
                    runtime_fingerprint=trial_result.receipt.runtime_identity,
                )
            )
        models = {}
        for name, values in by_agent.items():
            successful = [item for item in values if item.status == "succeeded"]
            rewards = [item.reward for item in successful if item.reward is not None]
            models[name] = ModelStats(
                model=name,
                n=len(successful),
                failures=len(values) - len(successful),
                mean_reward=statistics.fmean(rewards) if rewards else None,
            )
        started = [item.receipt.started_at for item in result.trials if item.receipt.started_at]
        completed = [
            item.receipt.completed_at for item in result.trials if item.receipt.completed_at
        ]
        now = datetime.now(timezone.utc)
        return Report(
            environment=self.spec.environment.name,
            environment_version=self.spec.environment.revision,
            name=self.spec.benchmark.name,
            description=self.spec.benchmark.description,
            primary_metric=self.spec.benchmark.primary_metric,
            models=models,
            cases=cases,
            manifest=RunManifest(
                started_at=min(started) if started else now,
                completed_at=max(completed) if completed else now,
                environment=self.spec.environment.name,
                environment_version=self.spec.environment.revision,
                environment_fingerprint=self.spec.environment.identity.digest,
                runtime_fingerprints=sorted(
                    {
                        item.receipt.runtime_identity
                        for item in result.trials
                        if item.receipt.runtime_identity
                    }
                ),
                targets=[agent.name for agent in self.spec.agents],
                task_ids=list(self.spec.benchmark.task_ids),
                repeats=self.spec.n_attempts,
                concurrency=self.spec.concurrency,
                status=(
                    "completed"
                    if all(item.status == "succeeded" for item in result.trials)
                    else "completed_with_failures"
                ),
                benchmark_name=self.spec.benchmark.name,
                primary_metric=self.spec.benchmark.primary_metric,
            ),
            metadata={"job_id": result.job_id, "plan_hash": result.plan_hash},
        )

    async def _run_with_retries(self, trial: Trial) -> TrialResult:
        result: TrialResult | None = None
        for retry in range(self.spec.retry.max_retries + 1):
            result = await trial.run(
                retry,
                execution_id=self.store.next_execution_id(trial.spec),
            )
            if (
                result.status != "failed"
                or result.error_code not in self.spec.retry.retryable_codes
            ):
                return result
            if retry < self.spec.retry.max_retries:
                delay = min(
                    self.spec.retry.max_backoff_seconds,
                    self.spec.retry.initial_backoff_seconds * (self.spec.retry.multiplier**retry),
                )
                await asyncio.sleep(delay)
        if result is None:  # pragma: no cover - range is always non-empty
            raise RuntimeError("trial did not execute")
        return result

    async def _cancelled_result(self, trial: TrialSpec) -> TrialResult:
        agent = next(item for item in self.spec.agents if item.agent_id == trial.agent_id)
        task = next(item for item in self.spec.environment.tasks if item.task_id == trial.task_id)
        now = datetime.now(timezone.utc)
        receipt = TrialReceipt(
            trial_id=trial.trial_id,
            job_id=trial.job_id,
            attempt=trial.attempt,
            environment_digest=trial.environment.digest,
            benchmark_digest=self.spec.benchmark.content_hash,
            agent_digest=agent.content_hash,
            harness_digest=trial.harness.digest if trial.harness is not None else "",
            runtime_provider=self.provider.name,
            task_hash=content_hash(task),
            started_at=now,
            completed_at=now,
        )
        result = TrialResult(status="cancelled", receipt=receipt)
        self.store.write_trial_attempt(
            trial,
            self.store.next_execution_id(trial),
            result,
        )
        return result


__all__ = ["ExecutionFailure", "Job", "Trial", "VerifierOutput"]
