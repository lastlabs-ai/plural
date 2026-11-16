"""Schema-v2 Task/Benchmark execution with Environment-directed scheduling."""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import functools
import json
import math
import os
import secrets as token_source
import shlex
import sys
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from plural._deprecation import module_getattr
from plural.agents import AgentBinding
from plural.apps.daemon import MANAGED
from plural.apps.host import STATES_FILE
from plural.atif import ATIF_FILE, episode_to_atif
from plural.auth import AuthHTTPError, check_gateway_key
from plural.benchmarks.results import AttemptEvidence, aggregate_configuration
from plural.benchmarks.rules import BenchmarkScoring
from plural.catalog import ModelCatalog
from plural.common import ErrorCode, HarnessPackage, HarnessProtocol, content_hash
from plural.config import resolve_gateway_url
from plural.credentials import CredentialError, CredentialUse, CredentialValue
from plural.credentials import resolve as resolve_credentials
from plural.environments.definition import party_seats
from plural.evidence import first_json_mapping
from plural.execution.apps import (
    WORKSPACE,
    AppHostSession,
    AppHostTampered,
    HostReport,
    app_private_files,
    app_secret_values,
    describe_missing,
    environment_payload,
    host_files,
    host_inputs,
    missing_app_secrets,
    trial_seed,
    verifier_sources,
)
from plural.execution.bootstrap import (
    RUNTIME_VERSION_VARIABLE,
    PluralDistribution,
    install_plural,
    missing_packages,
    needed_extras,
    needs_plural,
    prepare_requirements,
    resolve_distribution,
)
from plural.execution.episode_server import EpisodeServer, EpisodeServerOptions
from plural.execution.external import ExternalAgentRunner, ExternalRun
from plural.execution.inputs import ResourceResolver, resource_uploads, runtime_values
from plural.execution.integrity import audit_external
from plural.execution.policy import (
    ProjectPolicy,
    resolve_effective_policy,
    sandbox_requirements_for,
    verifier_score_sandbox,
)
from plural.execution.scheduler import drain
from plural.execution.seats import (
    SEAT_ARTIFACTS,
    SeatSetupError,
    prepare_seats,
    seat_environment,
    seat_files,
    seat_results,
    seat_scores,
    seat_stage,
    seat_steps,
    seat_workspace,
    unknown_seats,
)
from plural.execution.steps import STEPS_FILE, dump_jsonl, episode_terminated, merge_host_steps
from plural.execution.store import JobStore
from plural.execution.trial_metrics import metric_lines, task_metric_specs, trial_metrics
from plural.external.protocol import EpisodeGateway, signing_key
from plural.harness.episode import EPISODE_FILE
from plural.harness.native_runner import (
    CREDIT_PAUSE_VARIABLE,
    DEFAULT_CREDIT_PAUSE_SECONDS,
    STOP_VARIABLE,
)
from plural.harness.packages import (
    BUILTIN_PROFILES,
    external_v1,
    native_actions_v1,
    native_chat_v1,
)
from plural.harness.protocol import HarnessProtocolError, HarnessRunRequest
from plural.harness.retrieval import (
    materialize_package,
    reference_files,
    retrieve_archive,
    source_digest,
)
from plural.harness.runner import (
    HarnessExecution,
    HarnessExecutionError,
    HarnessRunner,
    is_native_runner,
)
from plural.integrity.detectors import TrialEvidence, detect
from plural.jobs import (
    AgentAggregate,
    ArtifactReference,
    BenchmarkJobSource,
    IntegrityFinding,
    JobMode,
    JobResult,
    JobSpec,
    PhaseName,
    PhaseTiming,
    SeatResult,
    TITORecord,
    TrialReceipt,
    TrialResult,
    TrialSpec,
    VerifierResult,
)
from plural.local_models import (
    LocalModelError,
    LocalModelIdentity,
    inspect_local_model,
    on_this_machine,
)
from plural.metrics import (
    BUILTIN_METRICS,
    METRICS_FILE,
    MetricAggregate,
    MetricSpec,
    aggregate_metric,
    metric_failures,
    series_by_metric,
)
from plural.rewards import (
    LEDGER_FILE,
    HindsightTrial,
    RewardRecord,
    append_ledger,
    dump_ledger,
    online_records,
    parse_ledger,
    reward_failures,
    trial_from_artifacts,
)
from plural.sandbox import (
    CapabilityError,
    DownloadedFile,
    ExecRequest,
    FileUpload,
    NetworkMode,
    ProviderRegistry,
    SandboxCapability,
    SandboxError,
    SandboxHandle,
    SandboxProvider,
    SandboxRequirements,
    default_registry,
)
from plural.sandbox.conformance import conformance_status
from plural.sandbox.sweep import trial_labels
from plural.tasks import TaskDefinition, validate_task_state
from plural.trajectory import normalize_trajectory
from plural.transcript import TRAJECTORY_FILE, episode_to_messages
from plural.trust import ConformanceStatus, TrustAssessment, TrustFacts, trust_tier
from plural.verifiers import (
    STOP_REASONS,
    AgentVerifier,
    DeterministicVerifier,
    Episode,
    EpisodeOutcome,
    EpisodeUsage,
    HumanVerifier,
    VerifierDefinition,
    VerifierOutput,
    VerifierRuntime,
    criterion_metrics,
    hindsight_hooks,
    resolve_metrics,
    rubric_score,
)


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
    if isinstance(exc, HarnessExecutionError) and exc.code is not None:
        return ErrorCode(exc.code)
    if isinstance(exc, HarnessProtocolError):
        return ErrorCode.PROTOCOL_FAILED
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
    if agent.external is not None:
        return external_v1()
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
    orchestrated = {
        name
        for name in (
            "PLURAL_API_KEY",
            "PLURAL_GATEWAY_URL",
            "PLURAL_PROJECT_ID",
            "PLURAL_ALLOW_NO_AUTH",
        )
        if environ.get(name)
    }
    names = {*agent.secrets, *orchestrated}
    undeclared = sorted(set(agent.secrets) - set(package.definition.secret_names))
    if undeclared:
        raise ExecutionFailure(
            ErrorCode.CONFIGURATION,
            f"Agent {agent.name!r} grants secrets not declared by Harness "
            f"{package.definition.name!r}: {undeclared!r}.\n"
            "List extra app secrets on the Harness, or omit them from Agent.secrets.\n"
            "Model authentication is supplied by Job(client=...) or Job(api_key=...), "
            "not Agent.secrets.",
        )
    missing = [name for name in agent.secrets if not environ.get(name)]
    if missing:
        listed = ", ".join(missing)
        raise ExecutionFailure(
            ErrorCode.AUTHENTICATION,
            f"Agent {agent.name!r} is missing keys in the environment: {listed}.\n"
            "Set those names before the run. This error names the keys and does not "
            "include their values.",
        )
    secrets = {name: environ[name] for name in names if environ.get(name)}
    configured = {
        name: environ[name]
        for name in package.definition.environment_names
        if environ.get(name) is not None
    }
    if agent.agent.endpoint is not None:
        if agent.harness is not None and agent.harness_package is None:
            raise ExecutionFailure(
                ErrorCode.CONFIGURATION,
                f"Agent {agent.name!r} calls its own endpoint, which built-in Harness "
                f"{package.definition.name!r} cannot use.",
            )
        configured["PLURAL_AGENT_ENDPOINT"] = agent.agent.endpoint
        key_name = agent.agent.endpoint_key
        if key_name is not None:
            if not environ.get(key_name):
                raise ExecutionFailure(
                    ErrorCode.AUTHENTICATION,
                    f"Agent {agent.name!r} needs {key_name} for its endpoint. Set it before "
                    "the run. This error names the key and does not include its value.",
                )
            secrets["PLURAL_AGENT_ENDPOINT_KEY"] = environ[key_name]
    return {**configured, **secrets}, secrets


def _redact_bytes(value: bytes, secrets: Mapping[str, str]) -> bytes:
    output = value
    for secret in secrets.values():
        if secret:
            output = output.replace(secret.encode(), b"***")
    return output


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


def sandbox_lifetime(task: TaskDefinition) -> float:
    """The longest a Trial's sandbox may live: its budgets plus a margin.

    Setup, the episode, and verification each have their own limit, so the
    sandbox outlives none of them, and a provider that can stop a sandbox on
    its own stops one whose Job died.

    Returns:
        Seconds.
    """
    runtime = task.environment.runtime
    return (
        task.environment.limits.max_seconds
        + runtime.timeout_seconds
        + runtime.build_timeout_seconds
        + LIFETIME_MARGIN_SECONDS
    )


def default_allowlist(environ: Mapping[str, str], declared: Sequence[str]) -> tuple[str, ...]:
    """The hosts a recorded run may reach when its Environment leaves ``network`` unset.

    The gateway's host, so the Agent can call models, the Python package
    index, so setup can install Plural in an image without it, and the hosts
    the Environment declares in ``allowed_hosts``.

    Returns:
        Host names, without duplicates.
    """
    hosts = []
    for name in ("PLURAL_GATEWAY_URL", "PLURAL_BASE_URL"):
        value = environ.get(name)
        if value:
            host = urlsplit(value).hostname
            if host:
                hosts.append(host)
    if not hosts:
        host = urlsplit(resolve_gateway_url(None, environ)).hostname
        if host:
            hosts.append(host)
    return tuple(dict.fromkeys((*hosts, *PACKAGE_INDEX_HOSTS, *declared)))


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


_JOB_ARTIFACTS = frozenset({LEDGER_FILE, METRICS_FILE, STATES_FILE, STEPS_FILE, "apps.json"})
RESULT_FILES = ("result.json", "final-result.json", "output.json")
GatewayKeys = Callable[[str, int, int], "str | None"]
"""Mints a gateway key for a local Trial's execution, given its time to live in seconds."""
GatewayCalls = Callable[[str, int], "int | None"]
"""Counts the model calls the gateway saw on a local Trial execution's key, or None."""
ISOLATION_REQUIRED = (
    "This Trial did not run: the sandbox could not keep the agent away from the graders.\n"
    "The image needs passwordless sudo and useradd, or start from Plural's base image:\n"
    "  image: ghcr.io/lastlabs-ai/plural-sandbox:py3.12\n"
    "To run anyway for a quick local check, set isolation: best_effort (results will be "
    "marked unverified)."
)
GATEWAY_KEY_MAX_SECONDS = 7 * 86_400
"""Longest a Trial's gateway key lives; the backend refuses a longer one."""
PACKAGE_INDEX_HOSTS = ("pypi.org", "files.pythonhosted.org")
"""Reached during setup to install Plural when the image does not already have it."""
LIFETIME_MARGIN_SECONDS = 1_800
"""Added to a Trial's own budgets to get the longest its sandbox may live."""
_HOST_VIEWS = frozenset(
    {"state.json", "final-state.json", "observation.json", "final-observation.json", "view.json"}
)
"""With Apps, only the App host says what the State, observation, and view were."""


async def _episode_recorded(host: AppHostSession) -> bool:
    """Whether the App host ran any action, so a retry would let the Harness try again.

    Returns:
        True when it did, or when it cannot say.
    """
    try:
        return bool((await host.finish()).steps)
    except Exception:  # noqa: BLE001 - an unreadable host may have run steps
        return True


def _redact_json(value: Any, secrets: Mapping[str, str]) -> Any:
    hidden = sorted({item for item in secrets.values() if item}, key=len, reverse=True)
    if not hidden:
        return value

    def redact(item: Any) -> Any:
        if isinstance(item, str):
            for secret in hidden:
                item = item.replace(secret, "***")
            return item
        if isinstance(item, Mapping):
            return {key: redact(entry) for key, entry in item.items()}
        if isinstance(item, (list, tuple)):
            return [redact(entry) for entry in item]
        return item

    return redact(value)


def _with_host_steps(
    artifacts: Sequence[DownloadedFile], report: HostReport
) -> tuple[DownloadedFile, ...]:
    """Take every App step from the App host's report rather than the Harness.

    Returns:
        The artifacts with the host's ``steps.jsonl``, ``states.jsonl``, and
        ``metrics.jsonl``, and
        ``episode.jsonl`` rebuilt so each App step carries the host's account.
    """
    result = tuple(artifacts)
    if report.states:
        result = _with_artifact(
            result, DownloadedFile(path=STATES_FILE, data=dump_jsonl(report.states))
        )
    if report.metrics:
        result = _with_artifact(
            result, DownloadedFile(path=METRICS_FILE, data=dump_jsonl(report.metrics))
        )
    # Even empty: without it, readers fall back to the Harness's own result.json.
    result = _with_artifact(result, DownloadedFile(path=STEPS_FILE, data=dump_jsonl(report.steps)))
    records = _episode_records(result)
    if records or report.steps:
        merged = merge_host_steps(records, report.steps)
        result = _with_artifact(result, DownloadedFile(path=EPISODE_FILE, data=dump_jsonl(merged)))
    return result


_MAX_JUDGE_ARTIFACT_BYTES = 32_000
_MAX_JUDGE_ARTIFACT_TOTAL_BYTES = 128_000


def _bounded_artifact_evidence(
    artifacts: Sequence[DownloadedFile],
    requested: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Return bounded UTF-8 evidence for explicitly requested artifact paths."""
    indexed = {item.path: item for item in artifacts}
    remaining = _MAX_JUDGE_ARTIFACT_TOTAL_BYTES
    output: list[dict[str, Any]] = []
    for path in requested:
        artifact = indexed.get(path)
        if artifact is None:
            output.append({"name": path, "available": False})
            continue
        limit = min(_MAX_JUDGE_ARTIFACT_BYTES, remaining)
        chunk = artifact.data[:limit]
        row: dict[str, Any] = {
            "name": path,
            "available": True,
            "digest": artifact.digest,
            "size_bytes": len(artifact.data),
        }
        try:
            row["content"] = chunk.decode("utf-8")
            row["truncated"] = len(chunk) < len(artifact.data)
            remaining -= len(chunk)
        except UnicodeDecodeError:
            row["readable"] = False
        output.append(row)
    return tuple(output)


def _final_evidence(artifacts: Sequence[DownloadedFile]) -> dict[str, Any] | None:
    """Return one bounded final Harness output for a judging Verifier."""
    final = next(
        (item for name in RESULT_FILES for item in artifacts if item.path == name),
        None,
    )
    if final is None:
        return None
    return _bounded_artifact_evidence((final,), (final.path,))[0]


def _trajectory_source(artifacts: Sequence[DownloadedFile]) -> DownloadedFile | None:
    """The Harness's own trajectory, preferring its ATIF document."""
    for name in (ATIF_FILE, "trajectory.json", "trajectory.jsonl"):
        found = next((item for item in artifacts if Path(item.path).name == name), None)
        if found is not None:
            return found
    return None


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


def _episode_records(artifacts: Sequence[DownloadedFile]) -> list[dict[str, Any]]:
    """Return the framework-recorded ``episode.jsonl`` records, if any."""
    source = next((item for item in artifacts if item.path == EPISODE_FILE), None)
    if source is None:
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in source.data.decode().splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    records.append(parsed)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    return records


def _jsonl_artifact(artifacts: Sequence[DownloadedFile], path: str) -> list[dict[str, Any]]:
    source = next((item for item in artifacts if item.path == path), None)
    if source is None:
        return []
    rows: list[dict[str, Any]] = []
    for line in source.data.decode(errors="replace").splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows


def _transcript(artifacts: Sequence[DownloadedFile]) -> dict[str, Any] | None:
    """The chat transcript built from ``episode.jsonl``.

    ``None`` when the Harness wrote its own ``trajectory.json`` or the episode
    recorded neither a model call nor a step.
    """
    if any(item.path == TRAJECTORY_FILE for item in artifacts):
        return None
    records = _episode_records(artifacts)
    if not any(record.get("kind") in {"model.call", "environment.step"} for record in records):
        return None
    return episode_to_messages(records)


def _episode_outcome(artifacts: Sequence[DownloadedFile]) -> EpisodeOutcome:
    """Read how the episode ended from the Harness result."""
    result = first_json_mapping(artifacts, RESULT_FILES)
    if not result:
        return EpisodeOutcome()
    reported = str(result.get("stop_reason") or "")
    return EpisodeOutcome(
        # A third-party Harness may report anything; an unknown reason reads as
        # unreported here and is rejected outright at the hosted API boundary.
        stop_reason=cast(Any, reported if reported in STOP_REASONS else ""),
        terminated=bool(result.get("terminated")),
        truncated=bool(result.get("truncated")),
        turns=int(result.get("turns") or 0),
        total_reward=float(result.get("total_reward") or 0),
    )


def _integrity(
    player: _Player, artifacts: Sequence[DownloadedFile], *, gateway_calls: int | None = None
) -> tuple[IntegrityFinding, ...]:
    """An External Agent's trace set beside what the App host observed; empty otherwise."""
    run = player.run
    if run is None or run.started_at is None or run.finished_at is None:
        return ()
    return audit_external(
        artifacts,
        actions=run.actions,
        started_at=run.started_at,
        finished_at=run.finished_at,
        gateway_calls=gateway_calls,
    )


def _answer(artifacts: Sequence[DownloadedFile]) -> Any:
    for name in RESULT_FILES:
        data = next((item.data for item in artifacts if item.path == name), None)
        if data is None:
            continue
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, Mapping):
            return value.get("answer", value.get("response"))
    return None


def _trust(
    provider: str,
    handle: SandboxHandle | None,
    requirements: SandboxRequirements | None,
    app_isolation: Literal["os_user", "none"] | None,
    host_signed: bool | None,
    conformance: tuple[str, tuple[str, ...]],
) -> TrustAssessment | None:
    """The Trial's trust tier from what the engine observed.

    None when no episode started: before a sandbox, or before the App host.
    """
    if handle is None or requirements is None or app_isolation is None:
        return None
    status, failures = conformance
    return trust_tier(
        TrustFacts(
            provider=provider,
            app_isolation=app_isolation,
            network=requirements.network.value,
            image_identity=handle.image_identity,
            image_pinned=handle.image_pinned,
            snapshot=handle.metadata.get("snapshot"),
            conformance=cast(ConformanceStatus, status),
            conformance_failures=failures,
            host_report_signed=host_signed,
        )
    )


def _episode_totals(artifacts: Sequence[DownloadedFile], *, failed: bool) -> dict[str, Any]:
    """How the episode ended, its per-step reward total, and its turns, for the TrialResult.

    Returns:
        ``stop_reason``, ``step_reward_total``, ``reward_failures``, and ``turns``.
    """
    outcome = _episode_outcome(artifacts)
    ledger = next((item for item in artifacts if item.path == LEDGER_FILE), None)
    records = parse_ledger(ledger.data) if ledger is not None else []
    return {
        "stop_reason": outcome.stop_reason or ("error" if failed else ""),
        "step_reward_total": math.fsum(
            record.value * record.weight for record in records if record.source == "step"
        ),
        "reward_failures": reward_failures(_episode_records(artifacts)),
        "turns": max(outcome.turns, 0),
    }


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


@dataclass(eq=False)
class _Player:
    """One Harness in a Trial: the only one, or the one in a seat."""

    seat: str | None
    binding: AgentBinding
    package: HarnessPackage
    token: str | None = None
    user: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    source: Path | None = None
    execution: Any = None
    files: tuple[DownloadedFile, ...] = ()
    """What an External Agent's episode left, which no Runtime holds."""
    run: ExternalRun | None = None
    artifacts: tuple[DownloadedFile, ...] = ()
    stdout: bytes = b""
    stderr: bytes = b""
    error: str | None = None
    cost_usd: float | None = None

    @property
    def workspace(self) -> str:
        """The folder the Harness runs in and writes its output to."""
        return "/workspace/harness" if self.seat is None else seat_workspace(self.seat)

    @property
    def stage(self) -> str:
        """Where its package is uploaded: its folder, or a stage its seat's user copies."""
        return "/workspace/harness" if self.seat is None else seat_stage(self.seat)


def _joined(players: Sequence[_Player], stream: Literal["stdout", "stderr"]) -> bytes:
    if len(players) == 1:
        return bytes(getattr(players[0], stream))
    return b"".join(
        f"=== seat {player.seat} ===\n".encode() + bytes(getattr(player, stream))
        for player in players
        if getattr(player, stream)
    )


class TrialRunner:
    """Runs one immutable Trial, recording append-only TrialExecutions.

    Internal to the engine: :class:`plural.Job` plans and runs Trials. Formerly ``Trial``.
    """

    def __init__(
        self,
        spec: TrialSpec,
        *,
        job_spec: JobSpec,
        provider_for: Callable[[str], SandboxProvider],
        store: JobStore,
        environ: Mapping[str, str],
        project_policy: ProjectPolicy,
        resource_resolvers: Mapping[str, ResourceResolver] | None = None,
        credentials: Mapping[str, CredentialValue | str] | None = None,
        episode_server: EpisodeServer | None = None,
        gateway_keys: GatewayKeys | None = None,
        gateway_calls: GatewayCalls | None = None,
        model_identity: LocalModelIdentity | None = None,
    ) -> None:
        self.spec = spec
        self.job_spec = job_spec
        self.model_identity = model_identity
        self.identity_findings: list[IntegrityFinding] = []
        self.credentials = dict(credentials or {})
        self.episode_server = episode_server
        self.gateway_keys = gateway_keys
        self.gateway_calls = gateway_calls
        self._gateway_key: str | None = None
        self._job_environ = environ
        self._resource_files: dict[str, bytes] = {}
        self.provider_for = provider_for
        self.store = store
        self.environ = environ
        self.resource_resolvers = resource_resolvers or {}
        self.project_policy = project_policy
        self._active: dict[tuple[str, str], SandboxHandle] = {}
        self.episode_recorded = False
        """Whether the last execution's Harness timed out after the App host ran an action."""
        self.harness_killed = False
        """Whether the last execution's Harness was killed for running past its time."""
        self._cost_usd: float | None = None

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

    async def _check_model_identity(self, agent: AgentBinding) -> None:
        """Refuse to start when the endpoint now serves another model than the Job accepted.

        Answers are evidence, never grounds to fail: a model whose answers to
        the fixed prompts changed is recorded as an ``model_answers_changed``
        integrity finding on the Trial, and the Trial runs.

        Raises:
            ExecutionFailure: When what the server reports about the model
                changed, or the server cannot be reached.
        """
        accepted = self.model_identity
        if accepted is None or (accepted.method == "behavior" and accepted.behavior is None):
            return
        key_name = agent.agent.endpoint_key
        # Hosted answers vary by request, so only a local server's are worth re-asking.
        answers = accepted.behavior is not None and (
            accepted.method == "behavior" or on_this_machine(accepted.endpoint)
        )
        try:
            current = await asyncio.to_thread(
                inspect_local_model,
                accepted.endpoint,
                accepted.requested,
                api_key=self.environ.get(key_name) if key_name else None,
                probe=accepted.method in {"reported", "behavior"} or answers,
                answers=answers,
            )
        except LocalModelError as exc:
            raise ExecutionFailure(ErrorCode.PROVIDER_UNAVAILABLE, str(exc)) from None
        if answers and current.behavior != accepted.behavior:
            self.identity_findings.append(
                IntegrityFinding(
                    code="model_answers_changed",
                    message=(
                        f"The model at {accepted.endpoint} answered the fixed identity prompts "
                        "differently than when the Job started. It reports the same model, so "
                        "the Trial ran; check the server if you did not expect a change."
                    ),
                    severity="warning",
                    source="detector",
                )
            )
        if accepted.method == "behavior":
            return
        if current.fingerprint != accepted.fingerprint:
            raise ExecutionFailure(
                ErrorCode.CONFIGURATION,
                f"The model at {accepted.endpoint} changed after the Job started. It was "
                f"{accepted.weights or accepted.requested} ({accepted.fingerprint}) and is now "
                f"{current.weights or current.requested} ({current.fingerprint}), so this "
                "Trial did not run.",
            )

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
        players = self._players(task, agent, package)
        provider = self.provider_for(task.environment.runtime.provider)
        seed = trial_seed(task.content_hash, self.spec.attempt)
        started = datetime.now(timezone.utc)
        clock = time.monotonic()
        secrets: dict[str, str] = {}
        stdout = b""
        stderr = b""
        verifier_stdout = b""
        verifier_stderr = b""
        artifacts: tuple[DownloadedFile, ...] = ()
        environment_observation: dict[str, Any] = {}
        environment_view_doc: dict[str, Any] = {}
        app_report: dict[str, Any] = {}
        host_report = HostReport()
        host: AppHostSession | None = None
        app_isolation: Literal["os_user", "none"] | None = None
        seat_isolation: Literal["os_user", "none"] | None = None
        seats_out: tuple[SeatResult, ...] = ()
        trace_id: str | None = None
        verifier_results: tuple[VerifierResult, ...] = ()
        credential_uses: tuple[CredentialUse, ...] = ()
        tito: ArtifactReference | None = None
        cost_usd: float | None = None
        phases: list[PhaseTiming] = []
        sandbox: SandboxHandle | None = None
        sandbox_requirements: SandboxRequirements | None = None
        conformance: tuple[str, tuple[str, ...]] = ("missing", ())
        host_signed: bool | None = None

        @contextlib.asynccontextmanager
        async def phase(name: PhaseName) -> AsyncIterator[None]:
            began = datetime.now(timezone.utc)
            try:
                yield
            finally:
                phases.append(
                    PhaseTiming(
                        name=name, started_at=began, completed_at=datetime.now(timezone.utc)
                    )
                )

        self.episode_recorded = False
        self.harness_killed = False
        self._cost_usd = None
        self.identity_findings = []
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
            self.environ = await self._execution_environ(task, execution_id)
            await self._check_model_identity(agent)
            if self._gateway_key is not None:
                secrets["PLURAL_TRIAL_GATEWAY_KEY"] = self._gateway_key
            for player in players:
                player.env, player_secrets = _harness_environment(
                    player.binding, player.package, self.environ
                )
                secrets.update(player_secrets)
            host_env, runtime_secrets = runtime_values(task.environment, self.environ)
            # Lets the Job, and not the Harness, read the Apps' State or end the episode.
            control = token_source.token_urlsafe(32)
            try:
                app_secrets = app_secret_values(task.environment, self.environ)
                credential_values, credential_uses = resolve_credentials(
                    task.environment, agent.agent, self.credentials, self.environ
                )
            except ValueError as exc:
                raise ExecutionFailure(ErrorCode.AUTHENTICATION, str(exc)) from None
            app_secrets = {**app_secrets, **credential_values}
            secrets.update(self._verifier_secret_values())
            secrets.update(runtime_secrets)
            secrets.update(app_secrets)
            for player in players:
                player.env["PLURAL_RESOURCES_DIR"] = "/workspace/resources"
            host_env["PLURAL_RESOURCES_DIR"] = "/workspace/resources"
            async with phase("agent_setup"):
                for player in players:
                    if player is players[0] or player.package is not players[0].package:
                        await self._preflight_harness(provider, player.package)
                    if player.binding.external is None:
                        player.source = materialize_package(player.package)
                requirements = _requirements(task, package)
                if any(_requirements(task, item.package) != requirements for item in players):
                    raise ExecutionFailure(
                        ErrorCode.CONFIGURATION,
                        "The seats' Harnesses need different Runtime images, but every seat "
                        "of a Trial runs in one Runtime. Give their Agents Harnesses that "
                        "share one.",
                    )
            requirements = await self._execution_requirements(
                provider, task, requirements, execution_id
            )
            sandbox_requirements = requirements
            distribution = self._plural_distribution(provider, package)
            async with phase("environment_setup"):
                if distribution is not None:
                    requirements = await prepare_requirements(provider, requirements, distribution)
                handle = await provider.create(requirements)
            self._active[(provider.name, handle.sandbox_id)] = handle
            sandbox = handle
            conformance = await conformance_status(provider)
            self.store.emit(
                self.spec.job_id,
                "environment_ready",
                "running",
                trial_id=self.spec.trial_id,
                execution_id=execution_id,
                data={"provider": provider.name, "image": handle.image_identity},
            )
            try:
                async with phase("agent_setup"):
                    for player in players:
                        if player.source is not None:
                            await provider.upload_bundle(handle, player.source, root=player.stage)
                async with phase("environment_setup"):
                    staged_files = await self._stage_environment(provider, handle)
                    if agent.external is not None:
                        self._resource_files = {item.path: item.data for item in staged_files}
                    if distribution is not None:
                        plural_env = await install_plural(
                            provider, handle, distribution, network=requirements.network
                        )
                        for player in players:
                            player.env.update(plural_env)
                        host_env.update(plural_env)
                # Setup runs as root, so it runs before any App secret, seat token, or
                # other seat's file is in the Runtime for it to read.
                async with phase("agent_setup"):
                    for player in players:
                        await HarnessRunner(provider).setup(
                            handle,
                            player.package.definition,
                            self._run_request(task, player).model_copy(
                                update={"workspace": player.stage}
                            ),
                            env=player.env,
                            timeout_seconds=task.environment.limits.max_seconds,
                        )
                async with phase("environment_setup"):
                    if task.environment.apps:
                        try:
                            staged = host_files(task)
                        except ValueError as exc:
                            raise ExecutionFailure(ErrorCode.CONFIGURATION, str(exc)) from exc
                        isolation = await provider.isolate_apps(handle)
                        if isolation.app_user is None and requirements.isolation == "required":
                            raise ExecutionFailure(ErrorCode.ENVIRONMENT_FAILED, ISOLATION_REQUIRED)
                        await provider.upload_files(handle, staged, root=WORKSPACE)
                        isolated = self._seats_isolated(task)
                        if self.seat_names:
                            seat_users = (
                                await provider.isolate_seats(handle, self.seat_names)
                                if isolated
                                else {}
                            )
                            for player in players:
                                player.user = seat_users.get(str(player.seat)) or (
                                    isolation.agent_user
                                )
                            try:
                                separated = await prepare_seats(
                                    provider,
                                    handle,
                                    {str(item.seat): item.user for item in players},
                                    shared=(WORKSPACE, "/workspace/resources"),
                                )
                            except SeatSetupError as exc:
                                raise ExecutionFailure(
                                    ErrorCode.ENVIRONMENT_FAILED, str(exc)
                                ) from exc
                            if isolated and not separated:
                                raise ExecutionFailure(
                                    ErrorCode.ENVIRONMENT_FAILED,
                                    f"Runtime {provider.name} could not give each seat an "
                                    "OS user of its own that cannot read another seat's "
                                    "folder, so the party did not play. Docker and Daytona "
                                    "can; a Daytona image needs passwordless sudo and "
                                    "useradd.",
                                )
                            seat_isolation = "os_user" if isolated else "none"
                        else:
                            players[0].user = isolation.agent_user
                        host = AppHostSession(
                            provider,
                            handle,
                            env=host_env,
                            token=control,
                            isolation=isolation,
                            private_files=app_private_files(task.environment),
                        )
                        await host.start(
                            secrets=app_secrets,
                            inputs=host_inputs(task, seed=seed),
                            seats={
                                str(item.seat): str(item.token) for item in players if item.seat
                            },
                        )
                        app_isolation = "os_user" if host.isolated else "none"
                        if not host.isolated and requirements.isolation == "required":
                            raise ExecutionFailure(ErrorCode.ENVIRONMENT_FAILED, ISOLATION_REQUIRED)
                        if not self.seat_names:
                            await provider.open_workspace(
                                handle,
                                isolation,
                                ("/workspace/harness", WORKSPACE, "/workspace/resources"),
                            )
                        elif not isolated:
                            # Isolated seats share these read-only, so none can leave
                            # another a file outside the Apps; shared seats may.
                            await provider.open_workspace(
                                handle, isolation, (WORKSPACE, "/workspace/resources")
                            )
                        for player in players:
                            player.env[MANAGED] = "1"
                for player in players:
                    if player.seat is not None:
                        player.env.update(seat_environment(player.seat, str(player.token)))
                request = self._run_request(task, players[0])
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
                async with phase("agent_execution"):
                    outcomes = await asyncio.gather(
                        *(
                            self._run_player(provider, handle, task, player, secrets)
                            for player in players
                        ),
                        return_exceptions=True,
                    )
                failure: BaseException | None = None
                for player, outcome in zip(players, outcomes, strict=True):
                    if isinstance(outcome, BaseException):
                        if not isinstance(outcome, Exception):
                            raise outcome
                        if not self.seat_names:
                            failure = outcome
                            break
                        # One seat's Harness failing ends its part, not the others'.
                        player.error = _redact_bytes(str(outcome).encode(), secrets).decode(
                            errors="replace"
                        )[:1000]
                        if isinstance(outcome, HarnessExecutionError):
                            player.stdout, player.stderr = outcome.stdout, outcome.stderr
                        continue
                    player.execution = outcome
                    player.stdout, player.stderr = outcome.stdout, outcome.stderr
                if failure is None and all(player.execution is None for player in players):
                    failure = next(item for item in outcomes if isinstance(item, BaseException))
                # Whatever a Harness left running must neither act during verification
                # nor swap a declared file for a symlink while it is downloaded.
                with contextlib.suppress(Exception):
                    await provider.stop_user_processes(handle, [item.user for item in players])
                if failure is not None:
                    if _classify(failure) is ErrorCode.TIMEOUT:
                        self.harness_killed = True
                        if host is not None:
                            self.episode_recorded = await _episode_recorded(host)
                    raise failure
                collection_started = datetime.now(timezone.utc)
                stdout = _redact_bytes(_joined(players, "stdout"), secrets)
                stderr = _redact_bytes(_joined(players, "stderr"), secrets)
                trace_id = next(
                    (item.execution.trace_id for item in players if item.execution is not None),
                    None,
                )
                job_only = _JOB_ARTIFACTS | (_HOST_VIEWS if task.environment.apps else frozenset())
                for player in players:
                    if player.execution is None:
                        continue
                    if player.binding.external is not None:
                        player.artifacts = player.files
                        continue
                    paths = tuple(
                        dict.fromkeys(
                            (*player.execution.output_paths, *player.execution.artifact_paths)
                        )
                    )
                    player.artifacts = tuple(
                        item
                        for item in await provider.download_artifacts(
                            handle, paths, root=player.workspace, user=player.user
                        )
                        # Only the Job writes these; a Harness file by the same name is dropped.
                        if item.path not in job_only
                    )
                artifacts = () if self.seat_names else players[0].artifacts
                if host is not None:
                    try:
                        host_report = await host.finish()
                    except AppHostTampered as exc:
                        host_signed = False
                        raise ExecutionFailure(ErrorCode.ENVIRONMENT_FAILED, str(exc)) from exc
                    host_signed = True
                    app_report = host_report.apps
                    environment_observation = host_report.observation
                    environment_view_doc = host_report.view
                    # An App's error or a reward hook's exception can quote a secret; what
                    # is stored is masked, while the Verifiers below read the live report.
                    stored = HostReport.parse(_redact_json(asdict(host_report), secrets))
                    artifacts = _with_host_steps(artifacts, stored)
                    if self.seat_names:
                        for player in players:
                            artifacts = (
                                *artifacts,
                                *seat_files(
                                    str(player.seat),
                                    self._seat_artifacts(player, stored, execution_id),
                                ),
                            )
                else:
                    environment_observation = await _optional_json(
                        provider, handle, "observation.json", root="/workspace/harness"
                    )
                    environment_view_doc = await _optional_json(
                        provider, handle, "view.json", root="/workspace/harness"
                    )
                if app_report:
                    artifacts = _with_artifact(
                        artifacts, _json_artifact("apps.json", _redact_json(app_report, secrets))
                    )
                    state = Episode.from_apps(app_report).state
                    if state:
                        artifacts = _with_artifact(
                            artifacts, _json_artifact("state.json", _redact_json(state, secrets))
                        )
                if environment_observation:
                    artifacts = _with_artifact(
                        artifacts,
                        _json_artifact(
                            "observation.json", _redact_json(environment_observation, secrets)
                        ),
                    )
                if environment_view_doc:
                    artifacts = _with_artifact(
                        artifacts,
                        _json_artifact("view.json", _redact_json(environment_view_doc, secrets)),
                    )
                if self.seat_names:
                    # Each seat's transcript and cost are its own, under seats/<seat>/.
                    costs = [item.cost_usd for item in players if item.cost_usd is not None]
                    cost_usd = math.fsum(costs) if costs else None
                else:
                    artifacts, cost_usd = self._with_transcripts(
                        artifacts, execution_id, binding=agent, model=self.spec.model
                    )
                self._cost_usd = cost_usd
                phases.append(
                    PhaseTiming(
                        name="artifact_collection",
                        started_at=collection_started,
                        completed_at=datetime.now(timezone.utc),
                    )
                )

                if self.job_spec.mode is JobMode.TRAIN:
                    if self.seat_names:
                        references = [
                            _validate_tito(item.package, item.artifacts)
                            for item in players
                            if item.execution is not None
                        ]
                        first = next(item for item in players if item.execution is not None)
                        tito = references[0].model_copy(
                            update={"name": f"{SEAT_ARTIFACTS}/{first.seat}/{references[0].name}"}
                        )
                    else:
                        tito = _validate_tito(package, artifacts)

                self.store.emit(
                    self.spec.job_id,
                    "verifying",
                    "verifying",
                    trial_id=self.spec.trial_id,
                    execution_id=execution_id,
                )
                # Verifiers run while the Runtime is up, so they can query the Apps.
                async with phase("verification"):
                    (
                        verifier_results,
                        verifier_stdout,
                        verifier_stderr,
                    ) = await self._run_verifiers(
                        artifacts,
                        trace_id,
                        observation=environment_observation,
                        apps=app_report,
                        query=self._app_query(host) if host is not None else None,
                    )
            finally:
                self._active.pop((provider.name, handle.sandbox_id), None)
                async with phase("cleanup"):
                    try:
                        if host is not None:
                            await host.stop()
                    finally:
                        await provider.destroy(handle)
            awaiting = any(item.status == "awaiting_review" for item in verifier_results)
            score, scores = _aggregate(task, verifier_results)
            artifacts = self._with_ledger(
                artifacts,
                apps=app_report,
                score=None if awaiting else score,
                hindsight=not awaiting,
            )
            if self.seat_names:
                seats_out = self._seat_results(
                    players,
                    {} if awaiting else seat_scores(task, self.seat_names, verifier_results),
                    host_report,
                    artifacts,
                )
            integrity = (
                *self.identity_findings,
                *_integrity(
                    players[0],
                    artifacts,
                    gateway_calls=await self._gateway_call_count(execution_id),
                ),
                *detect(
                    TrialEvidence(
                        task=task,
                        artifacts=artifacts,
                        logs=stdout + stderr,
                        verifier_results=verifier_results,
                        answer=_answer(artifacts),
                        canary=self._canary(),
                    )
                ),
            )
            status: Literal["succeeded", "awaiting_review"] = (
                "awaiting_review" if awaiting else "succeeded"
            )
            totals = _episode_totals(artifacts, failed=False)
            receipt = self._receipt(
                execution_id=execution_id,
                retry=retry,
                started=started,
                artifacts=artifacts,
                trace_id=trace_id,
                tito=tito,
                timings={"total_seconds": time.monotonic() - clock},
                phases=phases,
                cost_usd=cost_usd,
            )
            result = TrialResult(
                status=status,
                receipt=receipt,
                score=None if awaiting else score,
                scores={} if awaiting else scores,
                verifier_results=verifier_results,
                trace_id=trace_id,
                credentials=credential_uses,
                app_isolation=app_isolation,
                seats=seats_out,
                seat_isolation=seat_isolation,
                seed=seed,
                integrity=integrity,
                trust=_trust(
                    provider.name,
                    sandbox,
                    sandbox_requirements,
                    app_isolation,
                    host_signed,
                    conformance,
                ),
                model_identity=self.model_identity,
                metrics=trial_metrics(
                    task,
                    verifier_results,
                    artifacts,
                    cost_usd=cost_usd,
                    latency_seconds=receipt.timings.get("total_seconds"),
                    turns=totals["turns"],
                    stop_reason=totals["stop_reason"],
                    succeeded=True,
                ),
                metric_failures=metric_failures(host_report.metric_failures),
                **totals,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, HarnessExecutionError):
                stdout = _redact_bytes(exc.stdout, secrets)
                stderr = _redact_bytes(exc.stderr, secrets)
            code = _classify(exc)
            if code is not ErrorCode.AUTHENTICATION and self.store.cancel_requested(
                self.spec.job_id
            ):
                # Killed by the cancel, so its failure is the cancel's, not its own.
                code = ErrorCode.CANCELLED
            if host_report.steps and not any(item.path == LEDGER_FILE for item in artifacts):
                # The episode ran, so its step rewards stand even when a check failed.
                with contextlib.suppress(Exception):
                    artifacts = self._with_ledger(artifacts, apps=app_report, score=None)
            receipt = self._receipt(
                execution_id=execution_id,
                retry=retry,
                started=started,
                artifacts=artifacts,
                trace_id=trace_id,
                tito=tito,
                timings={"total_seconds": time.monotonic() - clock},
                phases=phases,
                cost_usd=cost_usd,
            )
            totals = _episode_totals(artifacts, failed=code is not ErrorCode.CANCELLED)
            if self.harness_killed and code is ErrorCode.TIMEOUT:
                totals["stop_reason"] = "harness_timeout"
            result = TrialResult(
                status="cancelled" if code is ErrorCode.CANCELLED else "failed",
                receipt=receipt,
                verifier_results=verifier_results,
                trace_id=trace_id,
                credentials=credential_uses,
                app_isolation=app_isolation,
                seats=self._seat_results(players, {}, host_report, artifacts)
                if self.seat_names and host_report.steps
                else (),
                seat_isolation=seat_isolation,
                seed=seed,
                trust=_trust(
                    provider.name,
                    sandbox,
                    sandbox_requirements,
                    app_isolation,
                    host_signed,
                    conformance,
                ),
                model_identity=self.model_identity,
                metrics=trial_metrics(
                    self.task,
                    (),
                    artifacts,
                    cost_usd=cost_usd,
                    latency_seconds=receipt.timings.get("total_seconds"),
                    turns=totals["turns"],
                    stop_reason=totals["stop_reason"],
                    succeeded=False,
                    checked=False,
                ),
                metric_failures=metric_failures(host_report.metric_failures),
                **totals,
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
            verifier_stdout=_redact_bytes(verifier_stdout, secrets),
            verifier_stderr=_redact_bytes(verifier_stderr, secrets),
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
            data={"score": result.score, "scores": result.scores},
            secret_values=secrets.values(),
        )
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        return result

    async def _execution_requirements(
        self,
        provider: SandboxProvider,
        task: TaskDefinition,
        requirements: SandboxRequirements,
        execution_id: int,
    ) -> SandboxRequirements:
        """Stamp what the Runtime does not say: labels, a lifetime, isolation, and network.

        A recorded run on a provider that enforces an allowlist, in an
        Environment that leaves ``network`` unset, gets an allowlist with the
        gateway's hosts. Any other unset network stays public.

        Returns:
            The requirements this execution's sandbox is created with.
        """
        runtime = task.environment.runtime
        update: dict[str, Any] = {
            "isolation": runtime.isolation_policy,
            "labels": {
                **requirements.labels,
                **trial_labels(
                    job=self.spec.job_id,
                    trial=self.spec.trial_id,
                    execution=str(execution_id),
                    environ=self._job_environ,
                ),
            },
            "lifetime_seconds": sandbox_lifetime(task),
        }
        if runtime.network is None and self._gateway_key is not None:
            capabilities = await provider.capabilities()
            if SandboxCapability.NETWORK_ALLOWLIST in capabilities.capabilities:
                update["network"] = NetworkMode.ALLOWLIST
                update["network_allowlist"] = default_allowlist(
                    self._job_environ, runtime.allowed_hosts
                )
        return requirements.model_copy(update=update)

    async def _gateway_call_count(self, execution_id: int) -> int | None:
        """Model calls the gateway saw on this execution's key, for an External Agent."""
        if self.gateway_calls is None or self._gateway_key is None:
            return None
        if self.agent.external is None:
            return None
        try:
            return await asyncio.to_thread(self.gateway_calls, self.spec.trial_id, execution_id)
        except Exception:  # noqa: BLE001 - a missing count is no finding, not a failed Trial
            return None

    def _canary(self) -> str | None:
        source = self.job_spec.source
        benchmark = getattr(source, "benchmark", None)
        return getattr(benchmark, "canary", None)

    async def _execution_environ(
        self, task: TaskDefinition, execution_id: int
    ) -> Mapping[str, str]:
        """The Job's environment, with this execution's own gateway key when it has one.

        A recorded run mints a key that calls models for this execution alone, so
        the key a Harness or an External Agent holds is never the user's own.
        """
        self._gateway_key = None
        needed = self.agent.external is not None or bool(self._job_environ.get("PLURAL_API_KEY"))
        if self.gateway_keys is None or not needed:
            return self._job_environ
        ttl = min(max(math.ceil(sandbox_lifetime(task)), 600), GATEWAY_KEY_MAX_SECONDS)
        key = await asyncio.to_thread(self.gateway_keys, self.spec.trial_id, execution_id, ttl)
        if not key:
            return self._job_environ
        self._gateway_key = key
        return {**self._job_environ, "PLURAL_API_KEY": key}

    async def _run_player(
        self,
        provider: SandboxProvider,
        handle: SandboxHandle,
        task: TaskDefinition,
        player: _Player,
        secrets: dict[str, str],
    ) -> HarnessExecution:
        """Run one player's part of the episode: its Harness, or its External Agent."""
        request = self._run_request(task, player)
        external = player.binding.external
        if external is None:
            return await HarnessRunner(provider).run(
                handle,
                player.package.definition,
                request,
                env=_stop_env(task, player.package.definition, player.env),
                timeout_seconds=_harness_timeout(task, player.package.definition, player.env),
                user=player.user,
                setup=False,
                private=player.seat is not None and self._seats_isolated(task),
            )
        if self.episode_server is None:
            raise ExecutionFailure(
                ErrorCode.CONFIGURATION,
                f"Agent {player.binding.name!r} is external, and this Job serves no episodes.",
            )
        value = self.environ.get(external.signing_key, "")
        secrets[external.signing_key] = value
        run = await ExternalAgentRunner(provider, self.episode_server).run(
            handle,
            player.binding,
            request,
            key=signing_key(value),
            env=player.env,
            user=player.user,
            files=self._resource_files,
            gateway=self._episode_gateway(),
            timeout_seconds=task.environment.limits.max_seconds,
            on_token=lambda token: secrets.__setitem__("PLURAL_EPISODE_TOKEN", token),
        )
        player.run = run
        player.files = tuple(
            DownloadedFile(path=item.path, data=_redact_bytes(item.data, secrets))
            for item in run.artifacts
        )
        return run.execution

    def _episode_gateway(self) -> EpisodeGateway | None:
        """Where an External Agent may call models: only with this execution's own key."""
        if self._gateway_key is None:
            return None
        url = resolve_gateway_url(None, self._job_environ)
        return EpisodeGateway(url=url, key=self._gateway_key)

    @property
    def seat_names(self) -> tuple[str, ...]:
        """The party's seats, in order; empty for a Trial one Agent works alone."""
        return tuple(item.seat for item in self.spec.seats)

    def _players(
        self, task: TaskDefinition, agent: AgentBinding, package: HarnessPackage
    ) -> list[_Player]:
        """The Harnesses this Trial runs: one, or one per seat with its own seat token."""
        if task.party is None and self.seat_names:
            raise ExecutionFailure(
                ErrorCode.CONFIGURATION,
                f"Trial has seats, but Task {task.task_id!r}'s Environment has no party.",
            )
        if task.party is None:
            return [_Player(seat=None, binding=agent, package=package)]
        reason = (
            task.party.check(len(self.seat_names))
            if self.seat_names == party_seats(len(self.seat_names))
            else f"Trial seats {list(self.seat_names)} are not seat_1 to seat_N"
        )
        if reason is not None:
            raise ExecutionFailure(ErrorCode.CONFIGURATION, f"Task {task.task_id!r}: {reason}.")
        agents = {item.agent_id: item for item in self.job_spec.agents}
        players: list[_Player] = []
        for assignment in self.spec.seats:
            binding = agents[assignment.agent_id]
            players.append(
                _Player(
                    seat=assignment.seat,
                    binding=binding,
                    package=package if binding is agent else _package_for(binding, task),
                    token=token_source.token_urlsafe(32),
                )
            )
        return players

    @staticmethod
    def _seats_isolated(task: TaskDefinition) -> bool:
        party = task.environment.party
        return party is None or party.isolation == "isolated"

    def _run_request(self, task: TaskDefinition, player: _Player) -> HarnessRunRequest:
        """What one Harness is told: the Task as its seat sees it, and its own Agent."""
        binding = player.binding
        assignment = next((item for item in self.spec.seats if item.seat == player.seat), None)
        grant = assignment.harness_grant if assignment is not None else self.spec.harness_grant
        model = assignment.model if assignment is not None else self.spec.model
        return HarnessRunRequest(
            request_id=self.spec.trial_id
            if player.seat is None
            else f"{self.spec.trial_id}:{player.seat}",
            task=task.public_payload
            if player.seat is None
            else task.seat_payload(player.seat, self.seat_names),
            agent={
                "agent_id": binding.agent_id,
                "name": binding.name,
                "model": binding.model,
                "instructions": binding.agent.instructions,
                "routing": binding.routing.model_dump(mode="json", exclude_none=True),
                "harness": player.package.definition.name,
                "harness_config": binding.harness_config,
            },
            model_resolution=model.model_dump(mode="json"),
            environment=environment_payload(task),
            mode=self.job_spec.mode.value,
            capture_tito=self.job_spec.mode is JobMode.TRAIN,
            workspace=player.workspace,
            granted_capabilities=tuple(sorted(item.value for item in grant.granted))
            if grant
            else (),
            denied_capabilities=tuple(sorted(item.value for item in grant.denied)) if grant else (),
            capability_denials=grant.capability_denials if grant else (),
        )

    def _with_transcripts(
        self,
        artifacts: tuple[DownloadedFile, ...],
        execution_id: int,
        *,
        binding: AgentBinding,
        model: Any,
    ) -> tuple[tuple[DownloadedFile, ...], float | None]:
        """Add the chat transcript and ATIF trajectory a Harness's episode yields.

        Returns:
            The artifacts, and the model cost they record.
        """
        transcript = _transcript(artifacts)
        if transcript is not None:
            artifacts = _with_artifact(artifacts, _json_artifact(TRAJECTORY_FILE, transcript))
        atif = self._atif(artifacts, execution_id, binding=binding, model=model)
        if atif is not None:
            artifacts = _with_artifact(artifacts, _json_artifact(ATIF_FILE, atif))
            return artifacts, atif["final_metrics"].get("total_cost_usd")
        normalized_trajectory = _normalized_trajectory_artifact(artifacts)
        if normalized_trajectory is not None:
            artifacts = _with_artifact(artifacts, normalized_trajectory)
        return artifacts, _trajectory_cost(artifacts)

    def _seat_artifacts(
        self, player: _Player, report: HostReport, execution_id: int
    ) -> tuple[DownloadedFile, ...]:
        """One seat's output, its App steps as the host recorded them, and its transcript.

        Returns:
            The seat's artifacts, at paths relative to its own folder.
        """
        seat = str(player.seat)
        own = _with_host_steps(player.artifacts, HostReport(steps=seat_steps(report.steps, seat)))
        assignment = next(item for item in self.spec.seats if item.seat == seat)
        own, player.cost_usd = self._with_transcripts(
            own, execution_id, binding=player.binding, model=assignment.model
        )
        player.artifacts = own
        return own

    def _seat_results(
        self,
        players: Sequence[_Player],
        scores: Mapping[str, float | None],
        report: HostReport,
        artifacts: Sequence[DownloadedFile],
    ) -> tuple[SeatResult, ...]:
        ledger_file = next((item for item in artifacts if item.path == LEDGER_FILE), None)
        return seat_results(
            self.seat_names,
            agents={
                str(item.seat): (
                    item.binding.agent_id,
                    item.binding.name,
                    item.binding.content_hash,
                )
                for item in players
            },
            scores=scores,
            steps=report.steps,
            ledger=parse_ledger(ledger_file.data) if ledger_file is not None else [],
            traces={
                str(item.seat): item.execution.trace_id if item.execution is not None else None
                for item in players
            },
            costs={str(item.seat): item.cost_usd for item in players},
            errors={str(item.seat): item.error for item in players if item.error},
        )

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
        packages = self.task.environment.runtime.packages.python
        if provider.name == "local" and packages:
            missing = missing_packages(packages)
            if missing:
                quoted = " ".join(shlex.quote(item) for item in missing)
                raise ExecutionFailure(
                    ErrorCode.CONFIGURATION,
                    "The Environment needs Python packages this Python does not have: "
                    f"{', '.join(missing)}. The local Runtime installs nothing, so install "
                    f"them into {sys.executable}, such as with `pip install {quoted}`.",
                )
        if agent.external is not None:
            return
        source = materialize_package(package)
        if (
            source is not None
            and package.source.digest is not None
            and source_digest(source) != package.source.digest
        ):
            raise ValueError(f"Harness source lock mismatch for {agent.name!r}")

    def _plural_distribution(
        self, provider: SandboxProvider, package: HarnessPackage
    ) -> PluralDistribution | None:
        """The Plural a non-local sandbox needs for this Trial, and the
        Environment's packages, if it runs Plural code or installs any."""
        packages = self.task.environment.runtime.packages.python
        if provider.name == "local" or not (packages or needs_plural(self.task, package)):
            return None
        return resolve_distribution(
            self.environ.get(RUNTIME_VERSION_VARIABLE), needed_extras(self.task), packages
        )

    async def _stage_environment(
        self, provider: SandboxProvider, handle: SandboxHandle
    ) -> Sequence[FileUpload]:
        """Upload the Environment's source and files, and the Task's.

        Returns:
            The files under ``/workspace/resources``.
        """
        source = self.task.environment.source
        root = None
        if source is not None:
            if source.kind == "oci":
                raise ExecutionFailure(
                    ErrorCode.CONFIGURATION, "OCI Environment source staging is unsupported"
                )
            root = (
                Path(source.uri).expanduser().resolve()
                if source.kind == "local"
                else retrieve_archive(source.uri, source.digest or "")
            )
            if source.digest is not None and source_digest(root) != source.digest:
                raise ValueError("Environment source lock mismatch")
            await provider.upload_files(
                handle, self._environment_uploads(root), root="/workspace/environment"
            )
        uploads = await asyncio.to_thread(
            resource_uploads,
            self.task.environment.resources,
            self.task.resources,
            root,
            self.resource_resolvers,
        )
        await provider.upload_files(handle, uploads, root="/workspace/resources")
        if self.task.state:
            validate_task_state(
                task_id=self.task.task_id,
                environment=self.task.environment,
                state=self.task.state,
            )
        return uploads

    def _environment_uploads(self, root: Path) -> list[FileUpload]:
        """The Environment's source files, without any Verifier's code or reference.

        The Agent can read the Environment's workspace, so a Verifier or a
        reference policy kept in the same folder is left out.

        Returns:
            The files to upload.

        Raises:
            ExecutionFailure: When an App's own file is also a Verifier's.
            ValueError: When the source holds a symlink.
        """
        root = root.resolve()
        hidden = [path for path in verifier_sources(self.task) if path.is_relative_to(root)]
        hidden.extend(root / name for name in reference_files(root))
        _refuse_shared_files(self.task, root)
        uploads: list[FileUpload] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"bundle contains a symlink: {path.relative_to(root)}")
            if not path.is_file() or any(
                path == item or path.is_relative_to(item) for item in hidden
            ):
                continue
            uploads.append(
                FileUpload(
                    path=path.relative_to(root).as_posix(),
                    data=path.read_bytes(),
                    mode=path.stat().st_mode & 0o777,
                )
            )
        return uploads

    def _app_query(self, host: AppHostSession) -> Callable[[str, str, dict[str, Any]], Any]:
        """A blocking App query for function Verifiers, which run in a worker thread."""
        loop = asyncio.get_running_loop()
        timeouts = {
            (item.app, item.action): item.timeout_seconds for item in self.task.environment.actions
        }

        def query(app: str, action: str, arguments: dict[str, Any]) -> Any:
            future = asyncio.run_coroutine_threadsafe(
                host.query(app, action, arguments, timeout=timeouts.get((app, action), 60.0)),
                loop,
            )
            return future.result()

        return query

    def _verifier_secret_values(self) -> dict[str, str]:
        """Secret values the Task's Verifiers declared.

        Returns:
            Name to value.

        Raises:
            ExecutionFailure: When a required one is missing.
        """
        values: dict[str, str] = {}
        missing: list[str] = []
        for binding in self.task.verifiers:
            for item in binding.verifier.secrets:
                value = self.environ.get(item.name)
                if value:
                    values[item.name] = value
                elif item.required:
                    missing.append(f"Verifier {binding.verifier.name!r} needs {item.name}")
        if missing:
            raise ExecutionFailure(
                ErrorCode.AUTHENTICATION,
                "Missing Verifier secrets:\n  " + "\n  ".join(missing),
            )
        return values

    def _reward_ledger(
        self,
        artifacts: Sequence[DownloadedFile],
        *,
        apps: Mapping[str, Any] | None,
        score: float | None,
        hindsight: bool = True,
    ) -> list[RewardRecord]:
        """Online rewards from the episode, then each Verifier's ``hindsight`` credit.

        A hindsight hook that fails is reported and skipped; rewards never fail
        a Trial or change its score.

        Returns:
            The Trial's reward ledger.
        """
        events = _episode_records(artifacts)
        ledger = online_records(events)
        hooks = hindsight_hooks(self.task.verifiers) if hindsight else ()
        if not hooks or not events:
            return ledger
        trial = HindsightTrial(
            events,
            apps=Episode.from_apps(apps).apps if apps else {},
            score=score,
            rewards=ledger,
            task_id=self.task.task_id,
            trial_id=self.spec.trial_id,
        )
        for verifier in hooks:
            try:
                ledger.extend(verifier.apply(trial))
            except Exception as exc:  # noqa: BLE001 - a reward label never fails a Trial
                self.store.emit(
                    self.spec.job_id,
                    "log",
                    "running",
                    trial_id=self.spec.trial_id,
                    data={
                        "message": f"Verifier {verifier.name!r} hindsight failed",
                        "verifier": verifier.name,
                        "error": str(exc)[:1000],
                    },
                )
        return ledger

    def _with_ledger(
        self,
        artifacts: tuple[DownloadedFile, ...],
        *,
        apps: Mapping[str, Any] | None,
        score: float | None,
        hindsight: bool = True,
    ) -> tuple[DownloadedFile, ...]:
        """Add the reward ledger to the artifacts, and stream it for training.

        Without ``hindsight``, as for a Trial awaiting review, hindsight hooks
        wait until the review has scored it.

        Returns:
            The artifacts, with ``rewards.jsonl`` when there are any rewards.
        """
        ledger = self._reward_ledger(artifacts, apps=apps, score=score, hindsight=hindsight)
        if ledger:
            artifacts = _with_artifact(
                artifacts, DownloadedFile(path=LEDGER_FILE, data=dump_ledger(ledger))
            )
        self._emit_rewards(ledger)
        return artifacts

    def _emit_rewards(self, ledger: Sequence[RewardRecord]) -> None:
        """Publish reward records as training signal.

        Rewards are recorded on every Trial. Only train-mode Jobs stream them
        as events, because only training consumes them.
        """
        if self.job_spec.mode is not JobMode.TRAIN:
            return
        for record in ledger:
            self.store.emit(
                self.spec.job_id,
                "reward",
                "running",
                trial_id=self.spec.trial_id,
                data=record.model_dump(mode="json"),
            )

    async def _run_verifiers(
        self,
        artifacts: Sequence[DownloadedFile],
        trace_id: str | None,
        *,
        observation: Mapping[str, Any] | None = None,
        apps: Mapping[str, Any] | None = None,
        query: Callable[[str, str, dict[str, Any]], Any] | None = None,
    ) -> tuple[tuple[VerifierResult, ...], bytes, bytes]:
        results: list[VerifierResult] = []
        stdout = bytearray()
        stderr = bytearray()
        for binding in self.task.verifiers:
            verifier = binding.verifier
            began = datetime.now(timezone.utc)
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
            if not verifier.scores:
                continue
            if isinstance(verifier, DeterministicVerifier) and verifier.check_fn is not None:
                episode = self._episode(
                    artifacts,
                    observation=observation,
                    apps=apps,
                    query=query,
                    verifier=verifier.name,
                )
                try:
                    scored = await asyncio.to_thread(verifier.invoke, episode)
                    parsed = scored.validated_finite()
                except ValueError as exc:
                    raise ExecutionFailure(ErrorCode.VERIFIER_FAILED, str(exc)) from exc
                self._check_seats(verifier.name, parsed.seats)
                results.append(
                    VerifierResult(
                        verifier_name=verifier.name,
                        verifier_digest=verifier.content_hash,
                        kind="deterministic",
                        status="succeeded",
                        score=parsed.score,
                        scores=parsed.scores,
                        metrics=parsed.metrics,
                        evidence=parsed.evidence,
                        feedback=parsed.feedback,
                        seats=parsed.seats,
                        started_at=began,
                        completed_at=datetime.now(timezone.utc),
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
                evidence_required = True
            else:
                command = verifier.command
                result_path = verifier.result_path
                evidence_required = verifier.evidence_required
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
                apps=apps,
            )
            results.append(
                result.model_copy(
                    update={"started_at": began, "completed_at": datetime.now(timezone.utc)}
                )
            )
            stdout.extend(out)
            stderr.extend(err)
        return tuple(results), bytes(stdout), bytes(stderr)

    def _check_seats(self, verifier: str, scored: Mapping[str, float]) -> None:
        unknown = unknown_seats(self.seat_names, scored)
        if unknown:
            raise ExecutionFailure(
                ErrorCode.VERIFIER_FAILED,
                f"Verifier {verifier!r} scored seats the party does not have: "
                f"{', '.join(unknown)}. Its seats are {', '.join(self.seat_names) or 'none'}.",
            )

    def _episode(
        self,
        artifacts: Sequence[DownloadedFile],
        *,
        observation: Mapping[str, Any] | None = None,
        apps: Mapping[str, Any] | None = None,
        query: Callable[[str, str, dict[str, Any]], Any] | None = None,
        verifier: str | None = None,
    ) -> Episode:
        hosted = bool(self.task.environment.apps)
        # With Apps the Harness's own files never stand in for what the host saw.
        view_observation = dict(observation or {}) or (
            {}
            if hosted
            else first_json_mapping(artifacts, ("final-observation.json", "observation.json"))
        )
        trajectory: list[Any] = list(_episode_records(artifacts))
        for item in () if trajectory else artifacts:
            if item.path in {"trajectory.normalized.json", "trajectory.jsonl", "trajectory.json"}:
                try:
                    text = item.data.decode()
                    if item.path.endswith(".jsonl"):
                        trajectory = [
                            json.loads(line) for line in text.splitlines() if line.strip()
                        ]
                    else:
                        parsed = json.loads(text)
                        trajectory = parsed if isinstance(parsed, list) else [parsed]
                except (UnicodeDecodeError, ValueError):
                    continue
                break
        outcome = _episode_outcome(artifacts)
        own = (
            [
                record
                for record in online_records(_episode_records(artifacts))
                if record.verifier == verifier
            ]
            if verifier
            else []
        )
        rewards = tuple(record.value for record in own)
        seat_rewards = {
            seat: tuple(record.value for record in own if record.seat == seat)
            for seat in self.seat_names
        }
        if hosted:
            # The Harness reports these; with Apps the host saw what happened.
            terminated, truncated = episode_terminated(_jsonl_artifact(artifacts, STEPS_FILE))
            outcome = outcome.model_copy(
                update={
                    "total_reward": math.fsum(rewards),
                    "terminated": terminated,
                    "truncated": truncated,
                }
            )
        episode = Episode.from_apps(
            apps or {},
            observation=view_observation,
            answer=first_json_mapping(artifacts, RESULT_FILES).get("response"),
            expected=self.task.expected,
            trajectory=trajectory,
            artifacts={item.path: item.path for item in artifacts},
            usage=EpisodeUsage(
                turns=outcome.turns,
                cost_usd=self._cost_usd,
            ),
            outcome=outcome,
            rewards=rewards,
            seats=self.seat_names,
            seat_rewards=seat_rewards,
            metric_series={
                key: tuple(points)
                for key, points in series_by_metric(metric_lines(artifacts)).items()
            },
        )
        if not hosted and not episode.apps and not episode.state:
            fallback = first_json_mapping(artifacts, ("final-state.json", "state.json"))
            if fallback:
                episode = episode.model_copy(update={"state": fallback})
        if query is not None:
            for name, snapshot in episode.apps.items():
                snapshot._query = functools.partial(_bound_query, query, name)
        return episode

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
        apps: Mapping[str, Any] | None = None,
    ) -> tuple[VerifierResult, bytes, bytes]:
        provider_name, requirements = verifier_score_sandbox(self.task.environment, runtime)
        provider = self.provider_for(provider_name)
        await provider.preflight(requirements)
        distribution = (
            resolve_distribution(self.environ.get(RUNTIME_VERSION_VARIABLE))
            if provider.name != "local" and needs_plural(self.task, None, command)
            else None
        )
        if distribution is not None:
            requirements = await prepare_requirements(provider, requirements, distribution)
        handle = await provider.create(requirements)
        self._active[(provider.name, handle.sandbox_id)] = handle
        try:
            plural_env = (
                await install_plural(provider, handle, distribution, network=requirements.network)
                if distribution is not None
                else {}
            )
            episode = self._episode(
                artifacts,
                observation=observation,
                apps=apps,
                verifier=verifier.name if verifier is not None else None,
            )
            payload: dict[str, Any] = {
                "task": self.task.public_payload,
                "trace_id": trace_id,
                "artifacts": [item.path for item in artifacts],
                "episode": episode.model_dump(mode="json"),
                "environment_view": {
                    "observation": episode.observation,
                    "state": episode.state,
                },
            }
            if isinstance(verifier, AgentVerifier):
                payload["agent_verifier"] = verifier.model_dump(mode="json")
                payload["judge_input"] = {
                    "task": self.task.public_payload,
                    "trace_id": trace_id,
                    "episode": payload["episode"],
                    "environment_view": payload["environment_view"],
                    "final": _final_evidence(artifacts),
                    "requested_artifacts": _bounded_artifact_evidence(
                        artifacts,
                        tuple(item.path for item in artifacts),
                    ),
                }
            uploads = [
                FileUpload(path=".plural/verifier-input.json", data=json.dumps(payload).encode()),
                *(FileUpload(path=f"artifacts/{item.path}", data=item.data) for item in artifacts),
            ]
            await provider.upload_files(handle, uploads)
            verifier_env = {**self._verifier_env(verifier), **plural_env}
            execution = await provider.exec(
                handle,
                ExecRequest(
                    command=command,
                    cwd="/workspace",
                    env=verifier_env,
                    timeout_seconds=runtime.timeout_seconds,
                ),
            )
            declared = {item.name for item in verifier.secrets} if verifier is not None else set()
            verifier_secrets = {
                name: value
                for name, value in verifier_env.items()
                if name.endswith("_API_KEY") or name in declared
            }
            verifier_stdout = _redact_bytes(execution.stdout, verifier_secrets)
            verifier_stderr = _redact_bytes(execution.stderr, verifier_secrets)
            if execution.timed_out:
                raise ExecutionFailure(ErrorCode.TIMEOUT, f"Verifier {name!r} timed out")
            if execution.exit_code != 0:
                detail = verifier_stderr.decode(errors="replace").strip()[-2000:]
                raise ExecutionFailure(
                    ErrorCode.VERIFIER_FAILED,
                    f"Verifier {name!r} exited with code {execution.exit_code}"
                    + (f": {detail}" if detail else ""),
                )
            files = await provider.download_files(handle, (result_path,))
            if len(files) != 1:
                raise ExecutionFailure(
                    ErrorCode.EVIDENCE_MISSING, f"Verifier {name!r} result is missing"
                )
            try:
                output = VerifierOutput.model_validate_json(files[0].data).validated_finite()
                if isinstance(verifier, AgentVerifier):
                    judged = rubric_score(verifier.criteria, output.scores)
                    rated = criterion_metrics(verifier, output.scores)
                    output = output.model_copy(
                        update={"score": judged, "metrics": {**rated, **output.metrics}}
                    )
                elif verifier is not None:
                    output = resolve_metrics(
                        output, verifier.metric_specs, verifier_name=verifier.name
                    )
            except ValueError as exc:
                raise ExecutionFailure(
                    ErrorCode.VERIFIER_FAILED, f"Verifier {name!r}: {exc}"
                ) from exc
            self._check_seats(name, output.seats)
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
                    score=output.score,
                    scores=output.scores,
                    metrics=output.metrics,
                    evidence=output.evidence,
                    feedback=output.feedback,
                    seats=output.seats,
                ),
                verifier_stdout,
                verifier_stderr,
            )
        finally:
            self._active.pop((provider.name, handle.sandbox_id), None)
            await provider.destroy(handle)

    def _verifier_env(self, verifier: VerifierDefinition | None) -> dict[str, str]:
        declared = {item.name for item in verifier.secrets} if verifier is not None else set()
        values = {name: self.environ[name] for name in declared if self.environ.get(name)}
        if isinstance(verifier, AgentVerifier):
            names = ("PLURAL_GATEWAY_URL", "PLURAL_API_KEY", "PLURAL_PROJECT_ID")
            values.update({name: self.environ[name] for name in names if self.environ.get(name)})
        return values

    def _atif(
        self,
        artifacts: Sequence[DownloadedFile],
        execution_id: int,
        *,
        binding: AgentBinding | None = None,
        model: Any = None,
    ) -> dict[str, Any] | None:
        """The ATIF trajectory of this execution, built from its ``episode.jsonl``.

        ``None`` when the Harness wrote its own ``atif-trajectory.json`` or recorded
        no episode.
        """
        if any(item.path == ATIF_FILE for item in artifacts):
            return None
        records = _episode_records(artifacts)
        if not records:
            return None
        binding = binding or self.agent
        resolution = model or self.spec.model
        return episode_to_atif(
            records,
            agent_name=binding.name,
            agent_version=binding.agent.revision,
            model_name=resolution.catalog_model_id,
            session_id=self.spec.trial_id,
            trajectory_id=f"{self.spec.job_id}:{self.spec.trial_id}:{execution_id}",
            extra={
                "plural": {
                    "job_id": self.spec.job_id,
                    "trial_id": self.spec.trial_id,
                    "execution_id": execution_id,
                    "task": self.task.task_id,
                    "harness": self.spec.harness.name if self.spec.harness else "native",
                }
            },
        )

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
        phases: Sequence[PhaseTiming] = (),
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
            phases=tuple(sorted(phases, key=lambda item: item.started_at)),
            cost_usd=cost_usd,
        )


def _bound_query(
    query: Callable[[str, str, dict[str, Any]], Any],
    app: str,
    action: str,
    arguments: dict[str, Any],
) -> Any:
    return query(app, action, arguments)


def _aggregate(
    task: TaskDefinition,
    results: Sequence[VerifierResult],
) -> tuple[float | None, dict[str, float]]:
    """Aggregate final Verifiers and train Verifiers deterministically."""
    final = [
        item
        for item in results
        if item.verifier_digest in {binding.verifier.content_hash for binding in task.verifiers}
    ]
    if any(item.status == "awaiting_review" for item in final):
        return None, {}
    weights = {binding.verifier.content_hash: binding.weight for binding in task.verifiers}
    weighted = [
        (item.score, weights[item.verifier_digest])
        for item in final
        if item.status == "succeeded" and item.score is not None
    ]
    total = sum(weight for _, weight in weighted)
    score = sum(value * weight for value, weight in weighted) / total if total else None
    scores: dict[str, float] = {}
    for item in final:
        if item.score is not None:
            scores[f"verifier.{item.verifier_name}"] = item.score
        for key, value in item.scores.items():
            scores[f"{item.verifier_name}.{key}"] = value
    return score, scores


def _agent_aggregates(
    spec: JobSpec,
    results: Sequence[TrialResult],
) -> tuple[AgentAggregate, ...]:
    source = spec.source
    release = source.benchmark if isinstance(source, BenchmarkJobSource) else None
    scoring = release.scoring if release is not None else BenchmarkScoring()
    categories = release.categories if release is not None else ()
    tasks = [task.task_id for task in spec.tasks]
    rows: list[AgentAggregate] = []
    for agent in spec.agents:
        selected = [
            item
            for item in results
            if any(seat.agent_digest == agent.content_hash for seat in item.seats)
            or (not item.seats and item.receipt.agent_digest == agent.content_hash)
        ]
        costs = [item.receipt.cost_usd for item in selected if item.receipt.cost_usd is not None]
        latencies = [
            item.receipt.timings["total_seconds"]
            for item in selected
            if "total_seconds" in item.receipt.timings
        ]
        # At a Task with seats an Agent is scored by each seat it played.
        played: list[tuple[TrialResult, float | None]] = []
        for item in selected:
            mine = [seat.score for seat in item.seats if seat.agent_digest == agent.content_hash]
            played.extend((item, score) for score in (mine if item.seats else [item.score]))
        combined = aggregate_configuration(
            tasks,
            [
                AttemptEvidence(
                    task=item.receipt.task_pin.name,
                    attempt=item.receipt.attempt,
                    status=item.status,
                    score=score,
                    error_code=item.error_code.value if item.error_code else None,
                    stop_reason=item.stop_reason or None,
                    cost_usd=item.receipt.cost_usd,
                    latency_seconds=item.receipt.timings.get("total_seconds"),
                    trial_id=item.receipt.trial_id,
                )
                for item, score in played
            ],
            scoring=scoring,
            categories=categories,
            required_attempts=spec.attempts,
            declared=release is not None,
        )
        metrics = _metric_aggregates(spec, selected)
        primary_metric = release.primary_metric if release is not None else "score"
        primary = (
            combined.score
            if primary_metric == "score"
            else metrics[primary_metric].mean
            if primary_metric in metrics
            else None
        )
        rows.append(
            AgentAggregate(
                agent_name=agent.name,
                agent_digest=agent.content_hash,
                model_id=agent.model,
                count=len(selected),
                successes=sum(item.status == "succeeded" for item in selected),
                mean_score=combined.score,
                coverage=combined.coverage,
                total_cost=sum(costs) if costs else None,
                mean_latency_seconds=sum(latencies) / len(latencies) if latencies else None,
                metrics=metrics,
                primary_metric=primary_metric,
                primary=primary,
            )
        )
    return tuple(rows)


def _metric_aggregates(spec: JobSpec, trials: Sequence[TrialResult]) -> dict[str, MetricAggregate]:
    """Each metric across one Agent's Trials, grouped by Task for pass^k and pass@k.

    A Trial without a value, because the metric did not apply or the Trial
    failed before its checks, counts toward the total and not toward ``n``.

    Returns:
        Each metric's aggregate, the built-ins first.
    """
    specs: dict[str, MetricSpec] = dict(BUILTIN_METRICS)
    for task in spec.tasks:
        for name, item in task_metric_specs(task).items():
            specs.setdefault(name, item)
    rows: dict[str, MetricAggregate] = {}
    for name, item in specs.items():
        by_task: dict[str, list[float | None]] = {}
        for trial in trials:
            by_task.setdefault(trial.receipt.task_pin.name, []).append(trial.metrics.get(name))
        if any(value is not None for values in by_task.values() for value in values):
            rows[name] = aggregate_metric(item, by_task)
    return rows


@dataclass(frozen=True)
class JobProgress:
    """A Job's standing so far, read from its store while Trials still run.

    The aggregates use the same Benchmark scoring as the final result, over the
    Trials that have finished, so ``coverage`` shows how much of it they cover.
    """

    planned: int
    finished: int
    running: int
    succeeded: int
    failed: int
    trials: tuple[TrialResult, ...]
    aggregates: tuple[AgentAggregate, ...]


def job_progress(store: JobStore, job_id: str) -> JobProgress:
    """Summarize a local Job from its per-Trial results and events.

    Returns:
        Counts and partial aggregates for the Trials recorded so far.
    """
    spec = store.load_spec(job_id)
    planned: int | None = None
    order: dict[str, int] = {}
    started: set[str] = set()
    for event in store.events(job_id):
        if event.type == "planned" and planned is None:
            planned = int(event.data.get("trial_count") or 0)
        if event.trial_id is None:
            continue
        order.setdefault(event.trial_id, event.sequence)
        if event.type == "provisioning":
            started.add(event.trial_id)
    trials = tuple(
        sorted(
            store.trial_results(job_id),
            key=lambda item: order.get(item.receipt.trial_id, math.inf),
        )
    )
    finished = {item.receipt.trial_id for item in trials}
    return JobProgress(
        planned=planned if planned is not None else spec.plan().trial_count,
        finished=len(trials),
        running=len(started - finished),
        succeeded=sum(item.status == "succeeded" for item in trials),
        failed=sum(item.status == "failed" for item in trials),
        trials=trials,
        aggregates=_agent_aggregates(spec, trials),
    )


STOP_GRACE_SECONDS = 30.0
"""How long past its own deadline the native runner has to stop before it is killed."""


def _harness_timeout(
    task: TaskDefinition, definition: HarnessProtocol, env: Mapping[str, str]
) -> float:
    """Seconds a Harness may run before it is killed.

    The episode's ``max_seconds`` governs the Harness, however long it is; the
    Runtime's ``timeout_seconds`` governs every other command. Another Harness
    is killed at ``max_seconds``. The native runner stops itself at that
    deadline, timed from when it starts, so it gets a grace period to end the
    episode and write its files; a Trial it ends that way is still verified.
    """
    limits = task.environment.limits
    allowed = limits.max_seconds + (STOP_GRACE_SECONDS if is_native_runner(definition) else 0.0)
    return allowed + _credit_pause(definition, env)


def _stop_env(
    task: TaskDefinition, definition: HarnessProtocol, env: Mapping[str, str]
) -> dict[str, str]:
    """A Harness's environment, told how many seconds the episode has.

    The native runner stops at that deadline and is killed a grace period
    later, so the kill never cuts it off mid-episode.
    """
    del definition
    stop = max(1.0, task.environment.limits.max_seconds)
    return {**env, STOP_VARIABLE: f"{stop:g}"}


def _credit_pause(definition: HarnessProtocol, env: Mapping[str, str]) -> float:
    """Extra time for a Harness that waits for credits without spending its own.

    The native runner leaves time spent waiting for credits out of the
    episode's max_seconds, so the Runtime's limit must allow for it. Other
    Harnesses keep their limit, and fail when the account runs out.
    """
    if not is_native_runner(definition):
        return 0.0
    if not env.get("PLURAL_GATEWAY_URL") or env.get("PLURAL_AGENT_ENDPOINT"):
        return 0.0
    return float(env.get(CREDIT_PAUSE_VARIABLE) or DEFAULT_CREDIT_PAUSE_SECONDS)


def _check_external(agent: AgentBinding, environ: Mapping[str, str]) -> None:
    """Refuse an External Agent whose signing key or CA bundle the Job lacks.

    Raises:
        ExecutionFailure: Naming the key, never its value.
    """
    external = agent.external
    assert external is not None
    value = environ.get(external.signing_key)
    if not value:
        raise ExecutionFailure(
            ErrorCode.AUTHENTICATION,
            f"Agent {agent.name!r} signs its episodes with {external.signing_key}. Export it, "
            f"or store it in the hosted project with `plural secret set {external.signing_key}`.",
        )
    try:
        signing_key(value)
    except ValueError as exc:
        raise ExecutionFailure(
            ErrorCode.CONFIGURATION, f"Agent {agent.name!r}: {external.signing_key}: {exc}"
        ) from None
    if external.ca_bundle is not None and not Path(external.ca_bundle).is_file():
        raise ExecutionFailure(
            ErrorCode.CONFIGURATION,
            f"Agent {agent.name!r}: the CA bundle {external.ca_bundle} does not exist.",
        )


def _refuse_shared_files(task: TaskDefinition, root: Path) -> None:
    """Refuse a file that holds both an App and a Verifier.

    The Agent can read the Environment's files, so a Verifier there is left
    out, and an App in the same file would be left out with it.

    Raises:
        ExecutionFailure: When an App's own file is also a Verifier's.
    """
    hidden = [path for path in verifier_sources(task) if path.is_relative_to(root)]
    needed = {
        (root / app.python.split(":", 1)[0]).resolve()
        for app in task.environment.apps
        if app.python
    }
    for path in hidden:
        if any(item == path or item.is_relative_to(path) for item in needed):
            raise ExecutionFailure(
                ErrorCode.CONFIGURATION,
                f"{path.relative_to(root)} holds both an App and Verifier code. The Agent "
                "can read the Environment's files, so move the Verifier into a file of "
                "its own.",
            )


class JobRunner:
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
        resource_resolvers: Mapping[str, ResourceResolver] | None = None,
        progress: Callable[[TrialSpec, TrialResult], None] | None = None,
        project_policy: ProjectPolicy | None = None,
        catalog: ModelCatalog | None = None,
        credentials: Mapping[str, Mapping[str, CredentialValue | str]] | None = None,
        episode_server: EpisodeServerOptions | None = None,
        gateway_keys: GatewayKeys | None = None,
        gateway_calls: GatewayCalls | None = None,
        model_identities: Mapping[str, LocalModelIdentity] | None = None,
        key_check: Callable[[str, str], None] | None = check_gateway_key,
    ) -> None:
        self.spec = spec
        self.key_check = key_check
        self.model_identities = dict(model_identities or {})
        self.credentials = dict(credentials or {})
        self.gateway_keys = gateway_keys
        self.gateway_calls = gateway_calls
        self.episode_server_options = episode_server
        self._episode_server: EpisodeServer | None = None
        self.catalog = catalog or ModelCatalog()
        self.plan = spec.plan(self.catalog)
        self._provider_override = provider
        self._providers = dict(providers or {})
        self.registry = registry
        self.store = store or JobStore()
        self.environ = os.environ if environ is None else environ
        self.resource_resolvers = resource_resolvers or {}
        self.progress = progress
        allow_local = any(task.environment.runtime.allow_unsafe_local for task in spec.tasks)
        self.project_policy = project_policy or ProjectPolicy.permissive(
            allow_unsafe_local=allow_local
        )
        self._trials: set[TrialRunner] = set()
        self.stopped: str | None = None
        """Why the Job stopped early, when a Trial's failure means every Trial would fail."""

    def _model_identity(self, trial: TrialSpec) -> LocalModelIdentity | None:
        agent = next(item for item in self.spec.agents if item.agent_id == trial.agent_id)
        return self.model_identities.get(agent.name)

    def _agent_credentials(self, trial: TrialSpec) -> Mapping[str, CredentialValue | str]:
        agent = next(item for item in self.spec.agents if item.agent_id == trial.agent_id)
        return self.credentials.get(agent.name, {})

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
        """Validate every Environment/Harness/Verifier runtime before launching.

        Raises:
            ExecutionFailure: When any Environment's Apps are missing secrets.
        """
        for task in self.spec.tasks:
            source = task.environment.source
            if source is not None and source.kind == "local":
                _refuse_shared_files(task, Path(source.uri).expanduser().resolve())
        missing: dict[str, list[str]] = {}
        for task in self.spec.tasks:
            for app, names in missing_app_secrets(task.environment, self.environ).items():
                missing.setdefault(app, [])
                missing[app].extend(name for name in names if name not in missing[app])
        if missing:
            raise ExecutionFailure(ErrorCode.AUTHENTICATION, describe_missing(missing))
        await self._check_gateway_key()
        for agent in self.spec.agents:
            if agent.external is not None:
                _check_external(agent, self.environ)
        for task in self.spec.tasks:
            for agent in self.spec.agents:
                try:
                    resolve_credentials(
                        task.environment,
                        agent.agent,
                        self.credentials.get(agent.name, {}),
                        self.environ,
                    )
                except CredentialError as exc:
                    raise ExecutionFailure(ErrorCode.AUTHENTICATION, str(exc)) from None
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
                    if item.task_digest == task.content_hash and agent.agent_id in item.agent_ids
                )
                runtime = TrialRunner(
                    trial,
                    job_spec=self.spec,
                    provider_for=self._provider_for,
                    store=self.store,
                    environ=self.environ,
                    resource_resolvers=self.resource_resolvers,
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
                provider_name, requirements = verifier_score_sandbox(
                    task.environment, verifier.runtime
                )
                provider = self._provider_for(provider_name)
                await provider.preflight(requirements)

    async def _check_gateway_key(self) -> None:
        """Check the Plural key once, before any Trial, when the Job calls the gateway.

        Raises:
            ExecutionFailure: When the gateway rejects the key or has locked
                this address out.
        """
        key = self.environ.get("PLURAL_API_KEY")
        if not key or self.key_check is None:
            return
        judged = any(
            binding.verifier.kind == "agent"
            for task in self.spec.tasks
            for binding in task.verifiers
        )
        native = any(
            agent.external is None and agent.agent.endpoint is None and agent.auth != "none"
            for agent in self.spec.agents
        )
        if not (judged or native):
            return
        gateway = resolve_gateway_url(None, self.environ)
        try:
            await asyncio.to_thread(self.key_check, gateway, key)
        except AuthHTTPError as exc:
            raise ExecutionFailure(ErrorCode.AUTHENTICATION, str(exc)) from None

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
                    trial = TrialRunner(
                        trial_spec,
                        job_spec=self.spec,
                        provider_for=self._provider_for,
                        store=self.store,
                        environ=self.environ,
                        resource_resolvers=self.resource_resolvers,
                        project_policy=self.project_policy,
                        credentials=self._agent_credentials(trial_spec),
                        episode_server=self._episode_server,
                        gateway_keys=self.gateway_keys,
                        gateway_calls=self.gateway_calls,
                        model_identity=self._model_identity(trial_spec),
                    )
                    self._trials.add(trial)
                    try:
                        result = await self._run_with_retries(trial)
                    finally:
                        self._trials.discard(trial)
                results[trial_spec.trial_id] = result
                if self.progress:
                    self.progress(trial_spec, result)
            if result.error_code is ErrorCode.AUTHENTICATION and self.stopped is None:
                # A rejected key fails every Trial alike, and each retry from the same
                # address counts toward the gateway's lockout, so stop them all now.
                self.stopped = (
                    f"Stopped the Job: Trial {trial_spec.trial_id} failed to authenticate, "
                    "so the others were cancelled rather than fail the same way. "
                    f"{(result.error_message or '').strip()[:500]}"
                ).strip()
                self.store.emit(
                    self.plan.job_id,
                    "cancelled",
                    "cancelled",
                    message=self.stopped,
                    data={"reason": "authentication", "trial_id": trial_spec.trial_id},
                )
                await self.cancel()

        async with contextlib.AsyncExitStack() as stack:
            if any(agent.external is not None for agent in self.spec.agents):
                self._episode_server = await stack.enter_async_context(
                    EpisodeServer(self.episode_server_options)
                )
            await drain(self.spec.concurrency, self.plan.trials, execute)
        self._episode_server = None
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
            stopped=self.stopped,
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
        try:
            review_score = rubric_score(binding.verifier.rubric, scores)
        except ValueError as exc:
            raise ValueError(f"review {exc}") from exc
        source = next(item for item in aggregate.trials if item.receipt.trial_id == trial_id)
        replacements = tuple(
            VerifierResult(
                verifier_name=item.verifier_name,
                verifier_digest=item.verifier_digest,
                kind="human",
                status="succeeded",
                score=review_score,
                scores={str(key): float(value) for key, value in scores.items()},
                feedback=feedback,
            )
            if item.verifier_name == verifier_name and item.status == "awaiting_review"
            else item
            for item in source.verifier_results
        )
        score, aggregate_scores = _aggregate(task, replacements)
        still_pending = any(item.status == "awaiting_review" for item in replacements)
        updated_trial = source.model_copy(
            update={
                "status": "awaiting_review" if still_pending else "succeeded",
                "score": None if still_pending else score,
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
                "score": review_score,
            },
            updated_trial,
        )
        self.store.write_job_result(updated)
        if not still_pending:
            self._review_hindsight(task, trial_spec, updated_trial)
        self.store.emit(
            self.plan.job_id,
            "succeeded" if not still_pending else "awaiting_review",
            updated_trial.status,
            trial_id=trial_id,
            data={"verifier": verifier_name, "score": review_score},
        )
        return updated

    def _review_hindsight(
        self, task: TaskDefinition, trial_spec: TrialSpec, trial: TrialResult
    ) -> None:
        """Run each ``hindsight`` hook once review has scored the Trial.

        A Trial awaiting review had no score when it ran, so hindsight that
        reads ``trial.score`` waits for the review. A hook that fails is
        reported and skipped.
        """
        hooks = hindsight_hooks(task.verifiers)
        if not hooks:
            return
        artifacts = (
            self.store.trial_path(trial_spec)
            / "executions"
            / str(trial.receipt.execution_id)
            / "artifacts"
        )
        if not (artifacts / EPISODE_FILE).is_file():
            return
        view = trial_from_artifacts(artifacts, score=trial.score)
        view.trial_id = trial_spec.trial_id
        for hook in hooks:
            try:
                append_ledger(artifacts / LEDGER_FILE, hook.apply(view))
            except Exception as exc:  # noqa: BLE001 - a reward label never fails a Trial
                self.store.emit(
                    self.plan.job_id,
                    "log",
                    trial.status,
                    trial_id=trial_spec.trial_id,
                    data={
                        "message": f"Verifier {hook.name!r} hindsight failed",
                        "verifier": hook.name,
                        "error": str(exc)[:1000],
                    },
                )

    async def _run_with_retries(self, trial: TrialRunner) -> TrialResult:
        result: TrialResult | None = None
        for retry in range(self.spec.retry.max_retries + 1):
            execution_id = self.store.next_execution_id(trial.spec)
            result = await trial.run(retry, execution_id)
            if (
                result.status != "failed"
                or result.error_code not in self.spec.retry.retryable_codes
                # A Harness that timed out mid-episode keeps its outcome rather than a re-roll.
                or (result.error_code is ErrorCode.TIMEOUT and trial.episode_recorded)
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
import json, math, os, urllib.error, urllib.request
data = json.load(open(".plural/verifier-input.json"))
spec = data["agent_verifier"]
base = (os.getenv("PLURAL_GATEWAY_URL") or "").rstrip("/")
if not base:
    raise SystemExit("AgentVerifier requires PLURAL_GATEWAY_URL for its model call")
judge_input = data["judge_input"]
prompt = json.dumps({
    "instructions": spec["instructions"],
    "criteria": spec["criteria"],
    "evidence": judge_input,
    "output_contract": {
        "scores": "object mapping each criterion name to a number in its min_score..max_score",
        "evidence": "non-empty list of concise strings citing supplied evidence",
        "feedback": "string",
    },
})
names = [criterion["name"] for criterion in spec["criteria"]]
schema = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {name: {"type": "number"} for name in names},
            "required": names,
            "additionalProperties": False,
        },
        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "feedback": {"type": "string"},
    },
    "required": ["scores", "evidence", "feedback"],
    "additionalProperties": False,
}
body = json.dumps({
    "model": spec["model"],
    "messages": [{"role": "user", "content": prompt}],
    "response_format": {
        "type": "json_schema",
        "json_schema": {"name": "verifier_output", "strict": True, "schema": schema},
    },
}).encode()
headers = {"Content-Type": "application/json"}
key = os.getenv("PLURAL_API_KEY")
if key: headers["Authorization"] = "Bearer " + key
if os.getenv("PLURAL_PROJECT_ID"): headers["X-Plural-Project"] = os.getenv("PLURAL_PROJECT_ID")
req = urllib.request.Request(base + "/chat/completions", data=body, headers=headers)
try:
    response = json.load(urllib.request.urlopen(req))
except urllib.error.HTTPError as exc:
    raise SystemExit(f"AgentVerifier model call failed ({exc.code}): {exc.read()[:1000]!r}")
content = response["choices"][0]["message"]["content"]
result = json.loads(content)
def finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
if set(result) != {"scores", "evidence", "feedback"}:
    raise ValueError("AgentVerifier output must have exactly scores, evidence, and feedback")
if not isinstance(result["scores"], dict) or any(
    not isinstance(name, str) or not finite_number(value)
    for name, value in result["scores"].items()
):
    raise ValueError("AgentVerifier scores must map names to finite numbers")
if set(result["scores"]) != set(names):
    raise ValueError(f"AgentVerifier scores must name exactly the criteria {sorted(names)!r}")
weighted = total = 0.0
for criterion in spec["criteria"]:
    low, high, weight = criterion["min_score"], criterion["max_score"], criterion["weight"]
    value = result["scores"][criterion["name"]]
    if not low <= value <= high:
        raise ValueError(f"criterion {criterion['name']!r} must be between {low} and {high}")
    weighted += (value - low) / (high - low) * weight
    total += weight
result["score"] = weighted / total
if not isinstance(result["evidence"], list) or not result["evidence"] or any(
    not isinstance(item, str) for item in result["evidence"]
):
    raise ValueError("AgentVerifier evidence must be a non-empty list of strings")
if not isinstance(result["feedback"], str):
    raise ValueError("AgentVerifier feedback must be a string")
json.dump(result, open("agent-verifier-result.json", "w"))
"""


__all__ = [
    "ExecutionFailure",
    "JobProgress",
    "JobRunner",
    "TrialRunner",
    "VerifierOutput",
    "job_progress",
]

_renamed = module_getattr(
    "plural.execution.engine", {"Trial": ("TrialRunner", lambda: TrialRunner)}
)


def __getattr__(name: str) -> Any:
    return _renamed(name)
