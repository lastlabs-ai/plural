"""Schema-v2 Task/Benchmark execution with Environment-directed scheduling."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from plural.catalog import ModelCatalog
from plural.domain import (
    AgentAggregate,
    AgentBinding,
    AgentVerifier,
    ArtifactReference,
    ErrorCode,
    HarnessPackage,
    HumanVerifier,
    JobMode,
    JobResult,
    JobSpec,
    TaskDefinition,
    TITORecord,
    TrialReceipt,
    TrialResult,
    TrialSpec,
    VerifierDefinition,
    VerifierResult,
    VerifierRuntime,
    content_hash,
)
from plural.evidence import environment_view, first_json_mapping
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
    ExecRequest,
    FileUpload,
    ProviderRegistry,
    SandboxError,
    SandboxHandle,
    SandboxProvider,
    SandboxRequirements,
    default_registry,
)
from plural.tasks import validate_task_state
from plural.trajectory import normalize_trajectory


class VerifierOutput(BaseModel):
    """Strict score document emitted by deterministic and agent Verifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reward: float
    scores: dict[str, float] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    feedback: str = ""

    def validated_finite(self) -> VerifierOutput:
        """Reject non-finite scores."""
        if any(not math.isfinite(item) for item in (self.reward, *self.scores.values())):
            raise ValueError("Verifier emitted non-finite scores")
        return self


class ExecutionFailure(RuntimeError):
    """Internal typed execution failure."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _classify(exc: BaseException) -> ErrorCode:
    if isinstance(exc, ExecutionFailure):
        return exc.code
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return ErrorCode.TIMEOUT
    if isinstance(exc, HarnessProtocolError):
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


def _package_for(agent: AgentBinding, task: TaskDefinition) -> HarnessPackage:
    if agent.harness_package is not None:
        return agent.harness_package
    if agent.harness is None:
        return native_actions_v1() if task.environment.actions else native_chat_v1()
    factory = BUILTIN_PROFILES.get(agent.harness.name)
    if factory is None:
        raise ExecutionFailure(
            ErrorCode.CONFIGURATION,
            f"Agent {agent.name!r} has no executable Harness package",
        )
    package = factory()
    if package.definition.revision != agent.harness.revision:
        raise ExecutionFailure(ErrorCode.CONFIGURATION, "built-in Harness revision mismatch")
    return package


def _harness_environment(
    agent: AgentBinding,
    package: HarnessPackage,
    environ: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    names = {*agent.secret_names}
    missing = [name for name in names if not environ.get(name)]
    if missing:
        raise ExecutionFailure(
            ErrorCode.AUTHENTICATION,
            f"missing declared Harness secrets: {missing!r}",
        )
    secrets = {name: environ[name] for name in names}
    configured = {
        name: environ[name]
        for name in package.definition.environment_names
        if environ.get(name) is not None
    }
    return {**configured, **secrets}, secrets


def _redact_bytes(value: bytes, secrets: Mapping[str, str]) -> bytes:
    output = value
    for secret in secrets.values():
        if secret:
            output = output.replace(secret.encode(), b"***")
    return output


def _environment_payload(task: TaskDefinition) -> dict[str, Any]:
    environment = task.environment
    properties = environment.observation_schema.get("properties", {})
    observation = {
        name: schema["default"]
        for name, schema in properties.items()
        if isinstance(schema, dict) and "default" in schema
    }
    return {
        "name": environment.name,
        "overview": environment.overview,
        "observation": observation,
        "observation_schema": environment.observation_schema,
        "limits": environment.limits.model_dump(mode="json"),
        "guardrails": [item.model_dump(mode="json") for item in environment.guardrails],
        "resources": [item.model_dump(mode="json") for item in environment.resources],
        "workspace": "/workspace/environment",
        "actions": [item.model_dump(mode="json") for item in environment.actions],
        "reset_command": list(environment.reset_command),
    }


async def _optional_json(
    provider: Any,
    handle: Any,
    path: str,
    *,
    root: str,
) -> dict[str, Any]:
    try:
        files = await provider.download_files(handle, (path,), root=root)
    except (FileNotFoundError, KeyError, OSError):
        return {}
    if not files:
        return {}
    try:
        value = json.loads(files[0].data)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _requirements(task: TaskDefinition, package: HarnessPackage) -> SandboxRequirements:
    environment = task.environment
    requirements = sandbox_requirements_for(
        environment,
        harness_digest=package.source.digest or package.content_hash,
    )
    if package.source.kind != "oci":
        return requirements
    runtime = environment.runtime
    if runtime.image or runtime.snapshot or runtime.declarative_image or runtime.build_context:
        raise CapabilityError(
            "OCI Harness composition with a separate Environment image is unsupported"
        )
    if package.source.digest is None:
        raise ValueError("OCI Harness requires a digest")
    reference = (
        package.source.uri
        if "@sha256:" in package.source.uri
        else f"{package.source.uri}@{package.source.digest}"
    )
    return requirements.model_copy(update={"image": reference})


def _artifact_reference(file: DownloadedFile, media_type: str) -> ArtifactReference:
    return ArtifactReference(
        name=file.path,
        digest=file.digest,
        media_type=media_type,
        size_bytes=len(file.data),
    )


def _json_artifact(path: str, value: Any) -> DownloadedFile:
    return DownloadedFile(
        path=path,
        data=(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


def _with_artifact(
    artifacts: Sequence[DownloadedFile],
    artifact: DownloadedFile,
) -> tuple[DownloadedFile, ...]:
    return (*tuple(item for item in artifacts if item.path != artifact.path), artifact)


def _trajectory_source(artifacts: Sequence[DownloadedFile]) -> DownloadedFile | None:
    return next(
        (
            item
            for item in artifacts
            if Path(item.path).name in {"trajectory.json", "trajectory.jsonl"}
            and item.path != "trajectory.normalized.json"
        ),
        None,
    )


def _normalized_trajectory_artifact(
    artifacts: Sequence[DownloadedFile],
) -> DownloadedFile | None:
    source = _trajectory_source(artifacts)
    if source is None:
        return None
    try:
        normalized = normalize_trajectory(source.data)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    return _json_artifact("trajectory.normalized.json", normalized.model_dump(mode="json"))


def _trajectory_cost(artifacts: Sequence[DownloadedFile]) -> float | None:
    source = _trajectory_source(artifacts)
    if source is None:
        return None
    try:
        trajectory = normalize_trajectory(source.data)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    values = []
    for event in trajectory.events:
        if event.kind != "cost":
            continue
        for key in ("cost_usd", "total_cost", "cost"):
            value = event.payload.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                values.append(float(value))
                break
    return sum(values) if values else None


def _validate_tito(
    package: HarnessPackage,
    artifacts: Sequence[DownloadedFile],
) -> ArtifactReference:
    path = package.definition.tito_path
    if not package.definition.supports_tito or path is None:
        raise ExecutionFailure(
            ErrorCode.TITO_UNSUPPORTED,
            f"Harness {package.definition.name!r} cannot provide exact TITO capture",
        )
    artifact = next((item for item in artifacts if item.path == path), None)
    if artifact is None:
        raise ExecutionFailure(ErrorCode.EVIDENCE_MISSING, f"TITO artifact {path!r} is missing")
    try:
        rows = [
            TITORecord.model_validate(json.loads(line))
            for line in artifact.data.decode().splitlines()
            if line.strip()
        ]
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExecutionFailure(ErrorCode.ARTIFACT_FAILED, f"invalid TITO artifact: {exc}") from exc
    if not rows:
        raise ExecutionFailure(ErrorCode.ARTIFACT_FAILED, "TITO artifact contains no records")
    return _artifact_reference(artifact, "application/x-ndjson; profile=plural-tito-v1")


class Trial:
    """One immutable Trial with append-only TrialExecutions."""

    def __init__(
        self,
        spec: TrialSpec,
        *,
        job_spec: JobSpec,
        provider_for: Callable[[str], SandboxProvider],
        store: JobStore,
        environ: Mapping[str, str],
        project_policy: ProjectPolicy,
    ) -> None:
        self.spec = spec
        self.job_spec = job_spec
        self.provider_for = provider_for
        self.store = store
        self.environ = environ
        self.project_policy = project_policy
        self._active: dict[tuple[str, str], SandboxHandle] = {}

    @property
    def task(self) -> TaskDefinition:
        """Pinned Task selected by this Trial."""
        return next(
            item for item in self.job_spec.tasks if item.content_hash == self.spec.task_digest
        )

    @property
    def agent(self) -> AgentBinding:
        """Pinned Agent selected by this Trial."""
        return next(item for item in self.job_spec.agents if item.agent_id == self.spec.agent_id)

    async def cancel(self) -> None:
        """Cancel all active sandboxes."""
        await asyncio.gather(
            *(
                self.provider_for(provider).cancel(handle)
                for (provider, _), handle in tuple(self._active.items())
            ),
            return_exceptions=True,
        )

    async def run(self, retry: int, execution_id: int) -> TrialResult:
        """Run one TrialExecution."""
        task = self.task
        agent = self.agent
        package = _package_for(agent, task)
        provider = self.provider_for(task.environment.runtime.provider)
        started = datetime.now(timezone.utc)
        clock = time.monotonic()
        secrets: dict[str, str] = {}
        stdout = b""
        stderr = b""
        verifier_stdout = b""
        verifier_stderr = b""
        artifacts: tuple[DownloadedFile, ...] = ()
        environment_state: dict[str, Any] = {}
        environment_observation: dict[str, Any] = {}
        environment_view_doc: dict[str, Any] = {}
        trace_id: str | None = None
        verifier_results: tuple[VerifierResult, ...] = ()
        tito: ArtifactReference | None = None
        cost_usd: float | None = None
        heartbeat = asyncio.create_task(self._heartbeat(execution_id))
        self.store.emit(
            self.spec.job_id,
            "provisioning",
            "provisioning",
            trial_id=self.spec.trial_id,
            execution_id=execution_id,
            data={"provider": provider.name, "placement": self.spec.placement},
        )
        try:
            harness_env, secrets = _harness_environment(agent, package, self.environ)
            await self._preflight_harness(provider, package)
            source = materialize_package(package)
            requirements = _requirements(task, package)
            handle = await provider.create(requirements)
            self._active[(provider.name, handle.sandbox_id)] = handle
            self.store.emit(
                self.spec.job_id,
                "environment_ready",
                "running",
                trial_id=self.spec.trial_id,
                execution_id=execution_id,
                data={"provider": provider.name, "image": handle.image_identity},
            )
            try:
                if source is not None:
                    await provider.upload_bundle(handle, source, root="/workspace/harness")
                await self._stage_environment(provider, handle)
                request = HarnessRunRequest(
                    request_id=self.spec.trial_id,
                    task=task.public_payload,
                    agent={
                        "agent_id": agent.agent_id,
                        "name": agent.name,
                        "model": agent.model,
                        "instructions": agent.agent.instructions,
                        "routing": agent.routing.model_dump(mode="json", exclude_none=True),
                    },
                    environment=_environment_payload(task),
                    mode=self.job_spec.mode.value,
                    capture_tito=self.job_spec.mode is JobMode.TRAIN,
                    workspace="/workspace/harness",
                    granted_capabilities=tuple(
                        sorted(item.value for item in self.spec.harness_grant.granted)
                    )
                    if self.spec.harness_grant
                    else (),
                    denied_capabilities=tuple(
                        sorted(item.value for item in self.spec.harness_grant.denied)
                    )
                    if self.spec.harness_grant
                    else (),
                    capability_denials=self.spec.harness_grant.capability_denials
                    if self.spec.harness_grant
                    else (),
                )
                self.store.emit(
                    self.spec.job_id,
                    "running",
                    "running",
                    trial_id=self.spec.trial_id,
                    execution_id=execution_id,
                    data={
                        "task_id": task.task_id,
                        "mode": self.job_spec.mode.value,
                        "capability_denials": list(request.capability_denials),
                    },
                    message=(
                        "Environment denied harness tools; Trial continues"
                        if request.capability_denials
                        else ""
                    ),
                )
                execution = await HarnessRunner(provider).run(
                    handle,
                    package.definition,
                    request,
                    env=harness_env,
                    timeout_seconds=min(
                        task.environment.runtime.timeout_seconds,
                        task.environment.limits.max_seconds,
                    ),
                )
                stdout = _redact_bytes(execution.stdout, secrets)
                stderr = _redact_bytes(execution.stderr, secrets)
                trace_id = execution.trace_id
                paths = tuple(dict.fromkeys((*execution.output_paths, *execution.artifact_paths)))
                artifacts = await provider.download_artifacts(
                    handle, paths, root="/workspace/harness"
                )
                environment_state = await _optional_json(
                    provider, handle, "state.json", root="/workspace/environment"
                ) or await _optional_json(provider, handle, "state.json", root="/workspace/harness")
                environment_observation = await _optional_json(
                    provider, handle, "observation.json", root="/workspace/environment"
                ) or await _optional_json(
                    provider, handle, "observation.json", root="/workspace/harness"
                )
                environment_view_doc = await _optional_json(
                    provider, handle, "view.json", root="/workspace/environment"
                ) or await _optional_json(provider, handle, "view.json", root="/workspace/harness")
                if environment_state:
                    artifacts = _with_artifact(
                        artifacts,
                        _json_artifact("state.json", environment_state),
                    )
                if environment_observation:
                    artifacts = _with_artifact(
                        artifacts,
                        _json_artifact("observation.json", environment_observation),
                    )
                if environment_view_doc:
                    artifacts = _with_artifact(
                        artifacts,
                        _json_artifact("view.json", environment_view_doc),
                    )
                normalized_trajectory = _normalized_trajectory_artifact(artifacts)
                if normalized_trajectory is not None:
                    artifacts = _with_artifact(artifacts, normalized_trajectory)
                cost_usd = _trajectory_cost(artifacts)
            finally:
                self._active.pop((provider.name, handle.sandbox_id), None)
                await provider.destroy(handle)

            if self.job_spec.mode is JobMode.TRAIN:
                tito = _validate_tito(package, artifacts)
                rewarder_results = await self._run_rewarders(artifacts, trace_id)
            else:
                rewarder_results = ()

            self.store.emit(
                self.spec.job_id,
                "verifying",
                "verifying",
                trial_id=self.spec.trial_id,
                execution_id=execution_id,
            )
            verifier_results, verifier_stdout, verifier_stderr = await self._run_verifiers(
                artifacts,
                trace_id,
                observation=environment_observation,
                state=environment_state,
            )
            all_results = (*rewarder_results, *verifier_results)
            artifacts = _with_artifact(
                artifacts,
                _json_artifact(
                    "verifier-results.json",
                    [item.model_dump(mode="json") for item in all_results],
                ),
            )
            awaiting = any(item.status == "awaiting_review" for item in verifier_results)
            reward, scores = _aggregate(task, all_results)
            status: Literal["succeeded", "awaiting_review"] = (
                "awaiting_review" if awaiting else "succeeded"
            )
            receipt = self._receipt(
                execution_id=execution_id,
                retry=retry,
                started=started,
                artifacts=artifacts,
                trace_id=trace_id,
                tito=tito,
                timings={"total_seconds": time.monotonic() - clock},
                cost_usd=cost_usd,
            )
            result = TrialResult(
                status=status,
                receipt=receipt,
                reward=None if awaiting else reward,
                scores={} if awaiting else scores,
                verifier_results=verifier_results,
                trace_id=trace_id,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, HarnessExecutionError):
                stdout = _redact_bytes(exc.stdout, secrets)
                stderr = _redact_bytes(exc.stderr, secrets)
            code = _classify(exc)
            receipt = self._receipt(
                execution_id=execution_id,
                retry=retry,
                started=started,
                artifacts=artifacts,
                trace_id=trace_id,
                tito=tito,
                timings={"total_seconds": time.monotonic() - clock},
                cost_usd=cost_usd,
            )
            result = TrialResult(
                status="cancelled" if code is ErrorCode.CANCELLED else "failed",
                receipt=receipt,
                verifier_results=verifier_results,
                trace_id=trace_id,
                error_code=None if code is ErrorCode.CANCELLED else code,
                error_message=_redact_bytes(str(exc).encode(), secrets).decode(errors="replace")[
                    :1000
                ],
            )
        self.store.write_trial_execution(
            self.spec,
            execution_id,
            result,
            stdout=stdout,
            stderr=stderr,
            artifacts=artifacts,
            verifier_stdout=verifier_stdout,
            verifier_stderr=verifier_stderr,
        )
        for stream, payload in (("stdout", stdout), ("stderr", stderr)):
            if payload:
                self.store.emit(
                    self.spec.job_id,
                    "log",
                    result.status,
                    trial_id=self.spec.trial_id,
                    execution_id=execution_id,
                    data={
                        "stream": stream,
                        "chunk": payload.decode(errors="replace")[:20_000],
                    },
                    secret_values=secrets.values(),
                )
        event_type = (
            "awaiting_review"
            if result.status == "awaiting_review"
            else "cancelled"
            if result.status == "cancelled"
            else "succeeded"
            if result.status == "succeeded"
            else "failed"
        )
        self.store.emit(
            self.spec.job_id,
            event_type,
            result.status,
            trial_id=self.spec.trial_id,
            execution_id=execution_id,
            message=result.error_message or "",
            data={"reward": result.reward, "scores": result.scores},
            secret_values=secrets.values(),
        )
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        return result

    async def _heartbeat(self, execution_id: int) -> None:
        while True:
            await asyncio.sleep(5)
            self.store.emit(
                self.spec.job_id,
                "heartbeat",
                "running",
                trial_id=self.spec.trial_id,
                execution_id=execution_id,
            )

    async def _preflight_harness(self, provider: SandboxProvider, package: HarnessPackage) -> None:
        agent = self.agent
        manifest = package.definition
        if manifest.implementation != "runnable":
            raise ExecutionFailure(ErrorCode.CONFIGURATION, "Harness is not runnable")
        if not any(fnmatch.fnmatchcase(agent.model, item) for item in manifest.supported_models):
            raise CapabilityError(
                f"Harness {manifest.name!r} does not support model {agent.model!r}"
            )
        if self.job_spec.mode is JobMode.TRAIN and not manifest.supports_tito:
            raise ExecutionFailure(
                ErrorCode.TITO_UNSUPPORTED,
                f"train mode requires exact TITO capture; Harness {manifest.name!r} "
                "does not declare supports_tito",
            )
        declared = await provider.capabilities()
        resolve_effective_policy(
            environment=self.task.environment,
            agent=agent.agent,
            grant=self.spec.harness_grant,
            project=self.project_policy,
            provider=declared,
            requested_target=self.task.environment.runtime.requested_target,
        )
        await provider.preflight(_requirements(self.task, package))
        source = materialize_package(package)
        if (
            source is not None
            and package.source.digest is not None
            and tree_digest(source) != package.source.digest
        ):
            raise ValueError(f"Harness source lock mismatch for {agent.name!r}")

    async def _stage_environment(self, provider: SandboxProvider, handle: SandboxHandle) -> None:
        source = self.task.environment.source
        if source is None:
            return
        if source.kind == "oci":
            raise ExecutionFailure(
                ErrorCode.CONFIGURATION, "OCI Environment source staging is unsupported"
            )
        root = (
            Path(source.uri).expanduser().resolve()
            if source.kind == "local"
            else retrieve_archive(source.uri, source.digest or "")
        )
        if source.digest is not None and tree_digest(root) != source.digest:
            raise ValueError("Environment source lock mismatch")
        await provider.upload_bundle(handle, root, root="/workspace/environment")
        if self.task.state:
            validate_task_state(
                task_id=self.task.task_id,
                environment_name=self.task.environment.name,
                state=self.task.state,
                state_schema=self.task.environment.state_schema,
            )
            await provider.upload_files(
                handle,
                (
                    FileUpload(
                        path="state.json",
                        data=(json.dumps(self.task.state, sort_keys=True) + "\n").encode(),
                    ),
                ),
                root="/workspace/environment",
            )

    async def _run_rewarders(
        self,
        artifacts: Sequence[DownloadedFile],
        trace_id: str | None,
    ) -> tuple[VerifierResult, ...]:
        output: list[VerifierResult] = []
        for rewarder in self.task.environment.rewarders:
            if rewarder.kind != "command":
                raise ExecutionFailure(
                    ErrorCode.CONFIGURATION,
                    f"Python Rewarder {rewarder.name!r} cannot execute from a package Job; "
                    "publish a command Rewarder",
                )
            result, _, _ = await self._run_score_command(
                name=rewarder.name,
                digest=content_hash(rewarder),
                kind="deterministic",
                command=rewarder.command,
                runtime=VerifierRuntime(
                    provider=self.task.environment.runtime.provider,
                    image=self.task.environment.runtime.image,
                    network=self.task.environment.runtime.network,
                    network_allowlist=self.task.environment.runtime.network_allowlist,
                    resources=self.task.environment.runtime.resources,
                    timeout_seconds=rewarder.timeout_seconds,
                ),
                result_path="rewarder-result.json",
                artifacts=artifacts,
                trace_id=trace_id,
                evidence_required=False,
            )
            output.append(result)
            self.store.emit(
                self.spec.job_id,
                "reward",
                "running",
                trial_id=self.spec.trial_id,
                data={"name": rewarder.name, "reward": result.reward},
            )
        return tuple(output)

    async def _run_verifiers(
        self,
        artifacts: Sequence[DownloadedFile],
        trace_id: str | None,
        *,
        observation: Mapping[str, Any] | None = None,
        state: Mapping[str, Any] | None = None,
    ) -> tuple[tuple[VerifierResult, ...], bytes, bytes]:
        results: list[VerifierResult] = []
        stdout = bytearray()
        stderr = bytearray()
        for binding in self.task.verifiers:
            verifier = binding.verifier
            if isinstance(verifier, HumanVerifier):
                results.append(
                    VerifierResult(
                        verifier_name=verifier.name,
                        verifier_digest=verifier.content_hash,
                        kind="human",
                        status="awaiting_review",
                    )
                )
                continue
            if isinstance(verifier, AgentVerifier):
                command: tuple[str, ...] = (
                    "python",
                    "-c",
                    _AGENT_VERIFIER_SCRIPT,
                )
                result_path = "agent-verifier-result.json"
                evidence_required = False
            else:
                command = verifier.command
                result_path = verifier.result_path
                evidence_required = verifier.evidence_required
                present = {item.path for item in artifacts}
                missing = set(verifier.required_artifacts) - present
                if missing:
                    raise ExecutionFailure(
                        ErrorCode.EVIDENCE_MISSING,
                        f"required Verifier artifacts are missing: {sorted(missing)!r}",
                    )
            result, out, err = await self._run_score_command(
                name=verifier.name,
                digest=verifier.content_hash,
                kind=verifier.kind,
                command=command,
                runtime=verifier.runtime,
                result_path=result_path,
                artifacts=artifacts,
                trace_id=trace_id,
                evidence_required=evidence_required,
                verifier=verifier,
                observation=observation,
                state=state,
            )
            results.append(result)
            stdout.extend(out)
            stderr.extend(err)
        return tuple(results), bytes(stdout), bytes(stderr)

    async def _run_score_command(
        self,
        *,
        name: str,
        digest: str,
        kind: str,
        command: tuple[str, ...],
        runtime: VerifierRuntime,
        result_path: str,
        artifacts: Sequence[DownloadedFile],
        trace_id: str | None,
        evidence_required: bool,
        verifier: VerifierDefinition | None = None,
        observation: Mapping[str, Any] | None = None,
        state: Mapping[str, Any] | None = None,
    ) -> tuple[VerifierResult, bytes, bytes]:
        provider = self.provider_for(runtime.provider)
        requirements = sandbox_requirements_for(
            self.task.environment,
            verifier_runtime=runtime,
        )
        await provider.preflight(requirements)
        handle = await provider.create(requirements)
        self._active[(provider.name, handle.sandbox_id)] = handle
        try:
            view_observation = first_json_mapping(
                artifacts, ("final-observation.json", "observation.json")
            ) or dict(observation or {})
            view_state = dict(state or {})
            if not view_state:
                view_state = first_json_mapping(artifacts, ("final-state.json", "state.json"))
            contract = getattr(verifier, "evidence", None)
            payload: dict[str, Any] = {
                "task": self.task.public_payload,
                "trace_id": trace_id,
                "artifacts": [item.path for item in artifacts],
                "environment_view": environment_view(
                    contract,
                    observation=view_observation,
                    state=view_state,
                )
                if contract is not None
                else {"observation": {}, "state": {}},
            }
            if isinstance(verifier, AgentVerifier):
                payload["agent_verifier"] = verifier.model_dump(mode="json")
            uploads = [
                FileUpload(path=".plural/verifier-input.json", data=json.dumps(payload).encode()),
                *(FileUpload(path=f"artifacts/{item.path}", data=item.data) for item in artifacts),
            ]
            await provider.upload_files(handle, uploads)
            execution = await provider.exec(
                handle,
                ExecRequest(
                    command=command,
                    cwd="/workspace",
                    env=self._verifier_env(verifier),
                    timeout_seconds=runtime.timeout_seconds,
                ),
            )
            if execution.timed_out:
                raise ExecutionFailure(ErrorCode.TIMEOUT, f"Verifier {name!r} timed out")
            if execution.exit_code != 0:
                raise ExecutionFailure(
                    ErrorCode.VERIFIER_FAILED,
                    f"Verifier {name!r} exited with code {execution.exit_code}",
                )
            files = await provider.download_files(handle, (result_path,))
            if len(files) != 1:
                raise ExecutionFailure(
                    ErrorCode.EVIDENCE_MISSING, f"Verifier {name!r} result is missing"
                )
            output = VerifierOutput.model_validate_json(files[0].data).validated_finite()
            if evidence_required and not output.evidence:
                raise ExecutionFailure(
                    ErrorCode.EVIDENCE_MISSING, f"Verifier {name!r} evidence is required"
                )
            return (
                VerifierResult(
                    verifier_name=name,
                    verifier_digest=digest,
                    kind=kind,  # type: ignore[arg-type]
                    status="succeeded",
                    reward=output.reward,
                    scores=output.scores,
                    evidence=output.evidence,
                    feedback=output.feedback,
                ),
                execution.stdout,
                execution.stderr,
            )
        finally:
            self._active.pop((provider.name, handle.sandbox_id), None)
            await provider.destroy(handle)

    def _verifier_env(self, verifier: VerifierDefinition | None) -> dict[str, str]:
        if not isinstance(verifier, AgentVerifier):
            return {}
        names = ("PLURAL_GATEWAY_URL", "OPENAI_BASE_URL", "PLURAL_API_KEY", "OPENAI_API_KEY")
        return {name: self.environ[name] for name in names if self.environ.get(name)}

    def _receipt(
        self,
        *,
        execution_id: int,
        retry: int,
        started: datetime,
        artifacts: Sequence[DownloadedFile],
        trace_id: str | None,
        tito: ArtifactReference | None,
        timings: dict[str, float],
        cost_usd: float | None,
    ) -> TrialReceipt:
        agent = self.agent
        return TrialReceipt(
            trial_id=self.spec.trial_id,
            job_id=self.spec.job_id,
            execution_id=execution_id,
            retry_count=retry,
            attempt=self.spec.attempt,
            task_digest=self.task.content_hash,
            task_pin=self.spec.task_pin,
            benchmark=self.spec.benchmark,
            model=self.spec.model,
            environment_digest=self.task.environment.content_hash,
            verifier_digests=self.spec.verifier_digests,
            agent_digest=agent.content_hash,
            harness_digest=self.spec.harness.digest if self.spec.harness else "",
            harness_grant=self.spec.harness_grant,
            mode=self.job_spec.mode,
            runtime_provider=self.task.environment.runtime.provider,
            placement=self.task.environment.runtime.placement,
            runtime_identity=content_hash(self.task.environment.runtime),
            artifact_hashes={item.path: item.digest for item in artifacts},
            tito_artifact=tito,
            trace_id=trace_id,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            timings=timings,
            cost_usd=cost_usd,
        )


def _aggregate(
    task: TaskDefinition,
    results: Sequence[VerifierResult],
) -> tuple[float | None, dict[str, float]]:
    """Aggregate final Verifiers and train Rewarders deterministically."""
    final = [
        item
        for item in results
        if item.verifier_digest in {binding.verifier.content_hash for binding in task.verifiers}
    ]
    if any(item.status == "awaiting_review" for item in final):
        return None, {}
    weights = {binding.verifier.content_hash: binding.weight for binding in task.verifiers}
    weighted = [
        (item.reward, weights[item.verifier_digest])
        for item in final
        if item.status == "succeeded" and item.reward is not None
    ]
    total = sum(weight for _, weight in weighted)
    reward = sum(value * weight for value, weight in weighted) / total if total else None
    scores: dict[str, float] = {}
    for item in final:
        if item.reward is not None:
            scores[f"verifier.{item.verifier_name}"] = item.reward
        for key, value in item.scores.items():
            scores[f"{item.verifier_name}.{key}"] = value
    return reward, scores


def _agent_aggregates(
    spec: JobSpec,
    results: Sequence[TrialResult],
) -> tuple[AgentAggregate, ...]:
    rows: list[AgentAggregate] = []
    for agent in spec.agents:
        selected = [item for item in results if item.receipt.agent_digest == agent.content_hash]
        rewards = [item.reward for item in selected if item.reward is not None]
        costs = [item.receipt.cost_usd for item in selected if item.receipt.cost_usd is not None]
        latencies = [
            item.receipt.timings["total_seconds"]
            for item in selected
            if "total_seconds" in item.receipt.timings
        ]
        rows.append(
            AgentAggregate(
                agent_name=agent.name,
                agent_digest=agent.content_hash,
                model_id=agent.model,
                count=len(selected),
                successes=sum(item.status == "succeeded" for item in selected),
                mean_reward=sum(rewards) / len(rewards) if rewards else None,
                total_cost=sum(costs) if costs else None,
                mean_latency_seconds=sum(latencies) / len(latencies) if latencies else None,
            )
        )
    return tuple(rows)


class Job:
    """Bounded async Job scheduler across Environment-owned runtimes."""

    def __init__(
        self,
        spec: JobSpec,
        *,
        provider: SandboxProvider | None = None,
        providers: Mapping[str, SandboxProvider] | None = None,
        registry: ProviderRegistry = default_registry,
        store: JobStore | None = None,
        environ: Mapping[str, str] | None = None,
        progress: Callable[[TrialSpec, TrialResult], None] | None = None,
        project_policy: ProjectPolicy | None = None,
        catalog: ModelCatalog | None = None,
    ) -> None:
        self.spec = spec
        self.catalog = catalog or ModelCatalog()
        self.plan = spec.plan(self.catalog)
        self._provider_override = provider
        self._providers = dict(providers or {})
        self.registry = registry
        self.store = store or JobStore()
        self.environ = os.environ if environ is None else environ
        self.progress = progress
        allow_local = any(task.environment.runtime.allow_unsafe_local for task in spec.tasks)
        self.project_policy = project_policy or ProjectPolicy.permissive(
            allow_unsafe_local=allow_local
        )
        self._trials: set[Trial] = set()

    def _provider_for(self, name: str) -> SandboxProvider:
        if self._provider_override is not None:
            return self._provider_override
        if name in self._providers:
            return self._providers[name]
        return self.registry.get(name)

    async def cancel(self) -> None:
        """Request cancellation and stop active sandboxes."""
        self.store.request_cancel(self.plan.job_id)
        await asyncio.gather(*(trial.cancel() for trial in tuple(self._trials)))

    async def preflight(self) -> None:
        """Validate every Environment/Harness/Verifier runtime before launching."""
        checked: set[tuple[str, str, str]] = set()
        for task in self.spec.tasks:
            for agent in self.spec.agents:
                package = _package_for(agent, task)
                key = (
                    task.environment.content_hash,
                    agent.content_hash,
                    package.content_hash,
                )
                if key in checked:
                    continue
                checked.add(key)
                trial = next(
                    item
                    for item in self.plan.trials
                    if item.task_digest == task.content_hash and item.agent_id == agent.agent_id
                )
                runtime = Trial(
                    trial,
                    job_spec=self.spec,
                    provider_for=self._provider_for,
                    store=self.store,
                    environ=self.environ,
                    project_policy=self.project_policy,
                )
                await runtime._preflight_harness(
                    self._provider_for(task.environment.runtime.provider),
                    package,
                )
            for binding in task.verifiers:
                verifier = binding.verifier
                if isinstance(verifier, HumanVerifier):
                    continue
                provider = self._provider_for(verifier.runtime.provider)
                await provider.preflight(
                    sandbox_requirements_for(
                        task.environment,
                        verifier_runtime=verifier.runtime,
                    )
                )

    async def run(self, *, resume: bool = False) -> JobResult:
        """Execute all ready Trials with global and per-runtime bounds."""
        self.store.initialize(self.spec, self.plan)
        if resume:
            self.store.clear_cancel(self.plan.job_id)
        if not (self.store.job_path(self.plan.job_id) / "events.jsonl").exists():
            self.store.emit(
                self.plan.job_id,
                "planned",
                "planned",
                data={"trial_count": self.plan.trial_count, "mode": self.spec.mode.value},
            )
        await self.preflight()
        global_limit = asyncio.Semaphore(self.spec.concurrency)
        runtime_limits = {
            content_hash(task.environment.runtime): asyncio.Semaphore(
                self.spec.per_runtime_concurrency
            )
            for task in self.spec.tasks
        }
        results: dict[str, TrialResult] = {}

        async def execute(trial_spec: TrialSpec) -> None:
            existing = self.store.successful_result(trial_spec)
            if existing is not None:
                results[trial_spec.trial_id] = existing
                return
            task = next(
                item for item in self.spec.tasks if item.content_hash == trial_spec.task_digest
            )
            self.store.emit(
                self.plan.job_id,
                "queued",
                "queued",
                trial_id=trial_spec.trial_id,
                data={"runtime": task.environment.runtime.provider},
            )
            async with global_limit, runtime_limits[content_hash(task.environment.runtime)]:
                if self.store.cancel_requested(self.plan.job_id):
                    result = self._cancelled_result(trial_spec)
                else:
                    trial = Trial(
                        trial_spec,
                        job_spec=self.spec,
                        provider_for=self._provider_for,
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
                if self.progress:
                    self.progress(trial_spec, result)

        await asyncio.gather(*(execute(item) for item in self.plan.trials))
        ordered = tuple(results[item.trial_id] for item in self.plan.trials)
        status: Literal["succeeded", "failed", "cancelled", "awaiting_review"]
        if any(item.status == "awaiting_review" for item in ordered):
            status = "awaiting_review"
        elif any(item.status == "failed" for item in ordered):
            status = "failed"
        elif any(item.status == "cancelled" for item in ordered):
            status = "cancelled"
        else:
            status = "succeeded"
        result = JobResult(
            job_id=self.plan.job_id,
            plan_hash=content_hash(self.plan),
            status=status,
            trials=ordered,
            benchmark=self.plan.lock.benchmark,
            aggregates=_agent_aggregates(self.spec, ordered),
        )
        self.store.write_job_result(result)
        self.store.emit(
            self.plan.job_id,
            "completed",
            status,
            data={
                "succeeded": sum(item.status == "succeeded" for item in ordered),
                "failed": sum(item.status == "failed" for item in ordered),
                "awaiting_review": sum(item.status == "awaiting_review" for item in ordered),
            },
        )
        return result

    def submit_review(
        self,
        trial_id: str,
        verifier_name: str,
        scores: Mapping[str, float],
        *,
        feedback: str = "",
    ) -> JobResult:
        """Resolve one pending Human Verifier and recompute deterministic aggregates.

        Returns:
            Updated durable Job result.
        """
        aggregate = self.store.read_job_result(self.plan.job_id)
        if aggregate is None:
            raise ValueError("Job has no result")
        trial_spec = next(
            (item for item in self.plan.trials if item.trial_id == trial_id),
            None,
        )
        if trial_spec is None:
            raise ValueError(f"Trial {trial_id!r} is not part of this Job")
        task = next(item for item in self.spec.tasks if item.content_hash == trial_spec.task_digest)
        binding = next(
            (
                item
                for item in task.verifiers
                if item.verifier.name == verifier_name and isinstance(item.verifier, HumanVerifier)
            ),
            None,
        )
        if binding is None or not isinstance(binding.verifier, HumanVerifier):
            raise ValueError(f"pending Human Verifier {verifier_name!r} was not found")
        expected = {item.name: item for item in binding.verifier.rubric}
        if set(scores) != set(expected):
            raise ValueError(f"review scores must match rubric criteria: {sorted(expected)!r}")
        weighted = 0.0
        total_weight = 0.0
        for name, criterion in expected.items():
            value = float(scores[name])
            if value < criterion.min_score or value > criterion.max_score:
                raise ValueError(
                    f"criterion {name!r} must be between "
                    f"{criterion.min_score} and {criterion.max_score}"
                )
            normalized = (value - criterion.min_score) / (criterion.max_score - criterion.min_score)
            weighted += normalized * criterion.weight
            total_weight += criterion.weight
        review_reward = weighted / total_weight
        source = next(item for item in aggregate.trials if item.receipt.trial_id == trial_id)
        replacements = tuple(
            VerifierResult(
                verifier_name=item.verifier_name,
                verifier_digest=item.verifier_digest,
                kind="human",
                status="succeeded",
                reward=review_reward,
                scores={str(key): float(value) for key, value in scores.items()},
                feedback=feedback,
            )
            if item.verifier_name == verifier_name and item.status == "awaiting_review"
            else item
            for item in source.verifier_results
        )
        reward, aggregate_scores = _aggregate(task, replacements)
        still_pending = any(item.status == "awaiting_review" for item in replacements)
        updated_trial = source.model_copy(
            update={
                "status": "awaiting_review" if still_pending else "succeeded",
                "reward": None if still_pending else reward,
                "scores": {} if still_pending else aggregate_scores,
                "verifier_results": replacements,
            }
        )
        updated_trials = tuple(
            updated_trial if item.receipt.trial_id == trial_id else item
            for item in aggregate.trials
        )
        job_status: Literal["succeeded", "failed", "cancelled", "awaiting_review"]
        if any(item.status == "awaiting_review" for item in updated_trials):
            job_status = "awaiting_review"
        elif any(item.status == "failed" for item in updated_trials):
            job_status = "failed"
        elif any(item.status == "cancelled" for item in updated_trials):
            job_status = "cancelled"
        else:
            job_status = "succeeded"
        updated = aggregate.model_copy(
            update={
                "status": job_status,
                "trials": updated_trials,
                "aggregates": _agent_aggregates(self.spec, updated_trials),
            }
        )
        self.store.write_review(
            trial_spec,
            verifier_name,
            {
                "scores": dict(scores),
                "feedback": feedback,
                "reward": review_reward,
            },
            updated_trial,
        )
        self.store.write_job_result(updated)
        self.store.emit(
            self.plan.job_id,
            "succeeded" if not still_pending else "awaiting_review",
            updated_trial.status,
            trial_id=trial_id,
            data={"verifier": verifier_name, "reward": review_reward},
        )
        return updated

    async def _run_with_retries(self, trial: Trial) -> TrialResult:
        result: TrialResult | None = None
        for retry in range(self.spec.retry.max_retries + 1):
            execution_id = self.store.next_execution_id(trial.spec)
            result = await trial.run(retry, execution_id)
            if (
                result.status != "failed"
                or result.error_code not in self.spec.retry.retryable_codes
            ):
                return result
            if retry < self.spec.retry.max_retries:
                delay = min(
                    self.spec.retry.max_backoff_seconds,
                    self.spec.retry.initial_backoff_seconds * self.spec.retry.multiplier**retry,
                )
                self.store.emit(
                    self.plan.job_id,
                    "retrying",
                    "queued",
                    trial_id=trial.spec.trial_id,
                    execution_id=execution_id,
                    data={"retry": retry + 1, "delay_seconds": delay},
                )
                await asyncio.sleep(delay)
        if result is None:
            raise RuntimeError("Trial did not execute")
        return result

    def _cancelled_result(self, trial: TrialSpec) -> TrialResult:
        task = next(item for item in self.spec.tasks if item.content_hash == trial.task_digest)
        agent = next(item for item in self.spec.agents if item.agent_id == trial.agent_id)
        now = datetime.now(timezone.utc)
        result = TrialResult(
            status="cancelled",
            receipt=TrialReceipt(
                trial_id=trial.trial_id,
                job_id=trial.job_id,
                execution_id=self.store.next_execution_id(trial),
                attempt=trial.attempt,
                task_digest=trial.task_digest,
                task_pin=trial.task_pin,
                benchmark=trial.benchmark,
                model=trial.model,
                environment_digest=task.environment.content_hash,
                verifier_digests=trial.verifier_digests,
                agent_digest=agent.content_hash,
                harness_digest=trial.harness.digest if trial.harness else "",
                harness_grant=trial.harness_grant,
                mode=self.spec.mode,
                runtime_provider=task.environment.runtime.provider,
                placement=task.environment.runtime.placement,
                started_at=now,
                completed_at=now,
            ),
        )
        self.store.write_trial_execution(
            trial,
            result.receipt.execution_id,
            result,
        )
        self.store.emit(
            self.plan.job_id,
            "cancelled",
            "cancelled",
            trial_id=trial.trial_id,
            execution_id=result.receipt.execution_id,
        )
        return result


_AGENT_VERIFIER_SCRIPT = r"""
import json, os, urllib.request
data = json.load(open(".plural/verifier-input.json"))
spec = data["agent_verifier"]
base = (
    os.getenv("PLURAL_GATEWAY_URL")
    or os.getenv("OPENAI_BASE_URL")
    or "https://api.openai.com/v1"
).rstrip("/")
prompt = json.dumps({
    "instructions": spec["instructions"],
    "rubric": spec["rubric"],
    "task": data["task"],
    "trace_id": data.get("trace_id"),
})
body = json.dumps({
    "model": spec["model"],
    "messages": [{"role": "user", "content": prompt}],
    "response_format": {"type": "json_object"},
}).encode()
headers = {"Content-Type": "application/json"}
key = os.getenv("PLURAL_API_KEY") or os.getenv("OPENAI_API_KEY")
if key: headers["Authorization"] = "Bearer " + key
req = urllib.request.Request(base + "/chat/completions", data=body, headers=headers)
response = json.load(urllib.request.urlopen(req))
content = response["choices"][0]["message"]["content"]
result = json.loads(content)
json.dump(result, open("agent-verifier-result.json", "w"))
"""


__all__ = ["ExecutionFailure", "Job", "Trial", "VerifierOutput"]
