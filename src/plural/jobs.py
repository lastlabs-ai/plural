"""Schema-v2 Job, Trial, event, result, and TITO orchestration contracts."""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from plural.agents import Agent, AgentBinding, AgentDefinition
from plural.catalog import ModelCatalog
from plural.common import (
    SHA256_PATTERN,
    ErrorCode,
    FrozenModel,
    HarnessBinding,
    HarnessCapability,
    content_hash,
    stable_id,
)
from plural.environments.definition import EnvironmentDefinition, EnvironmentIdentity, HarnessGrant
from plural.sandbox.models import NetworkMode
from plural.tasks import Benchmark, BenchmarkDefinition, Task, TaskDefinition, TaskPin


class RetryPolicy(FrozenModel):
    """TrialExecution retry policy."""

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
    def _bounded(self) -> RetryPolicy:
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must be at least initial_backoff_seconds")
        return self


class TaskJobSource(FrozenModel):
    """A Job selecting one Task revision."""

    kind: Literal["task"] = "task"
    task: TaskDefinition

    @property
    def tasks(self) -> tuple[TaskDefinition, ...]:
        """Selected Tasks."""
        return (self.task,)


class BenchmarkJobSource(FrozenModel):
    """A Job selecting one Benchmark revision."""

    kind: Literal["benchmark"] = "benchmark"
    benchmark: BenchmarkDefinition

    @property
    def tasks(self) -> tuple[TaskDefinition, ...]:
        """Selected Tasks."""
        return self.benchmark.tasks


JobSource = Annotated[TaskJobSource | BenchmarkJobSource, Field(discriminator="kind")]


def _task_pin(task: TaskDefinition) -> TaskPin:
    return TaskPin(name=task.task_id, version=task.revision, content_hash=task.content_hash)


def _benchmark_pin(source: JobSource) -> BenchmarkPin | None:
    if not isinstance(source, BenchmarkJobSource):
        return None
    benchmark = source.benchmark
    return BenchmarkPin(
        name=benchmark.name,
        version=benchmark.revision,
        content_hash=benchmark.content_hash,
    )


def _resolve_model(agent: AgentBinding, catalog: ModelCatalog) -> ModelResolution:
    model = catalog.get(agent.model)
    if model is None:
        provider = agent.routing.provider or agent.model.partition("/")[0]
        upstream_id = agent.model.partition("/")[2] or agent.model
        return ModelResolution(
            catalog_model_id=agent.model,
            provider=provider,
            endpoint=f"{provider}:unknown",
            upstream_id=upstream_id,
            catalog_updated_at=catalog.updated_at,
        )
    endpoints = model.ordered_endpoints()
    if agent.routing.provider is not None:
        endpoint = next(
            (item for item in endpoints if item.provider == agent.routing.provider),
            None,
        )
        if endpoint is None:
            raise ValueError(
                f"provider {agent.routing.provider!r} is not a catalog endpoint "
                f"for model {agent.model!r}"
            )
    else:
        endpoint = endpoints[0]
    return ModelResolution(
        catalog_model_id=agent.model,
        provider=endpoint.provider,
        endpoint=f"{endpoint.provider}:{endpoint.region}",
        upstream_id=endpoint.upstream_id,
        catalog_updated_at=catalog.updated_at,
    )


class JobMode(str, Enum):
    """Execution mode."""

    EVAL = "eval"
    TRAIN = "train"


class TrialStatus(str, Enum):
    """Durable Trial state machine."""

    PLANNED = "planned"
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    VERIFYING = "verifying"
    AWAITING_REVIEW = "awaiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStatus(str, Enum):
    """Durable TrialExecution state machine."""

    QUEUED = "queued"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    VERIFYING = "verifying"
    AWAITING_REVIEW = "awaiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProgressEvent(FrozenModel):
    """Append-only, sanitized execution progress event."""

    schema_version: Literal["2"] = "2"
    sequence: int = Field(ge=1)
    timestamp: datetime
    job_id: str = Field(min_length=1)
    type: Literal[
        "planned",
        "queued",
        "provisioning",
        "environment_ready",
        "running",
        "heartbeat",
        "model_turn",
        "action",
        "observation",
        "reward",
        "log",
        "verifying",
        "awaiting_review",
        "retrying",
        "succeeded",
        "failed",
        "cancelled",
        "completed",
    ]
    status: str
    trial_id: str | None = None
    execution_id: int | None = Field(default=None, ge=0)
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class TITORecord(FrozenModel):
    """Exact token-in/token-out training record stored as an artifact."""

    schema_version: Literal["1"] = "1"
    step: int = Field(ge=0)
    tokenizer: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_token_ids: tuple[int, ...]
    output_token_ids: tuple[int, ...]
    observation_token_ids: tuple[int, ...]
    output_logprobs: tuple[float, ...]
    output_top_logprobs: tuple[dict[str, float], ...]
    output_text: str
    assistant_message: dict[str, Any]
    input_len: int = Field(ge=0)
    output_len: int = Field(ge=0)
    observation_len: int = Field(ge=0)

    @model_validator(mode="after")
    def _validated_lengths(self) -> TITORecord:
        size = len(self.output_token_ids)
        if len(self.output_logprobs) != size or len(self.output_top_logprobs) != size:
            raise ValueError(
                "output_token_ids, output_logprobs, and output_top_logprobs lengths must match"
            )
        declared = (self.input_len, self.output_len, self.observation_len)
        actual = (
            len(self.input_token_ids),
            len(self.output_token_ids),
            len(self.observation_token_ids),
        )
        if declared != actual:
            raise ValueError(
                "input_len, output_len, and observation_len must match their token arrays"
            )
        if any(not math.isfinite(value) for value in self.output_logprobs):
            raise ValueError("output_logprobs must be finite")
        if any(
            not math.isfinite(value)
            for candidates in self.output_top_logprobs
            for value in candidates.values()
        ):
            raise ValueError("output_top_logprobs must be finite")
        return self


class ArtifactReference(FrozenModel):
    """Hashed artifact reference; large content is never embedded."""

    name: str = Field(min_length=1)
    digest: str
    media_type: str
    size_bytes: int = Field(ge=0)

    @field_validator("digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must be sha256:<64 lowercase hex characters>")
        return value


class ArtifactManifestEntry(FrozenModel):
    """One content-addressed file in an execution artifact directory."""

    path: str = Field(min_length=1)
    sha256: str
    media_type: str = Field(min_length=1)
    size: int = Field(ge=0)
    role: str | None = None

    @field_validator("sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("sha256 must be sha256:<64 lowercase hex characters>")
        return value


class ArtifactManifest(FrozenModel):
    """Stable manifest for the files persisted under ``artifacts/``."""

    schema_version: Literal["1"] = "1"
    artifacts: tuple[ArtifactManifestEntry, ...] = ()


class BenchmarkPin(FrozenModel):
    """Exact Benchmark revision audited by a Job."""

    name: str
    version: str
    content_hash: str


class ModelResolution(FrozenModel):
    """Catalog model and endpoint selected at planning time."""

    catalog_model_id: str
    provider: str
    endpoint: str
    upstream_id: str
    catalog_updated_at: str | None = None


class VerifierResult(FrozenModel):
    """One immutable Verifier outcome."""

    verifier_name: str
    verifier_digest: str
    kind: Literal["deterministic", "agent", "human"]
    status: Literal["succeeded", "failed", "awaiting_review"]
    score: float | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    feedback: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def _finite(self) -> VerifierResult:
        values = [*self.scores.values()]
        if self.score is not None:
            values.append(self.score)
        if any(not math.isfinite(item) for item in values):
            raise ValueError("verifier result contains a non-finite score")
        if self.status == "succeeded" and self.score is None:
            raise ValueError("successful verifier result requires a score")
        return self


_NETWORK_NONE_DENIALS = frozenset(
    {
        HarnessCapability.WEB_SEARCH,
        HarnessCapability.BROWSER,
        HarnessCapability.NETWORK_FETCH,
        HarnessCapability.MCP,
    }
)
_NETWORK_RESTRICTED_DENIALS = frozenset({HarnessCapability.WEB_SEARCH, HarnessCapability.BROWSER})


def resolve_trial_harness_grant(
    environment: EnvironmentDefinition,
    agent: AgentDefinition,
) -> HarnessGrant | None:
    """Resolve Agent Harness compatibility against one Trial Environment.

    Returns:
        Per-Trial stamp, or ``None`` for a native Agent.
    """
    package = agent.harness_package
    binding = agent.harness
    if binding is None:
        return None
    if package is None:
        raise ValueError(f"Agent {agent.name!r} harness requires an executable package")
    if package.definition.implementation != "runnable":
        raise ValueError(f"Harness {package.definition.name!r} is declared but not runnable")
    if HarnessBinding.from_package(package) != binding:
        raise ValueError("Agent Harness package does not match binding")
    allowed = set(environment.harness_policy.allowed_harnesses)
    if environment.harness_policy.mode == "allowlist" and binding.name not in allowed:
        raise ValueError(
            f"Harness {binding.name!r} is not allowed by Environment {environment.name!r}"
        )
    declared = package.definition.capabilities
    denied: set[HarnessCapability] = set()
    reasons: dict[str, str] = {}

    def deny(capability: HarnessCapability, reason: str) -> None:
        if capability in declared and capability not in denied:
            denied.add(capability)
            reasons[capability.value] = reason

    for capability in environment.harness_policy.denied_capabilities:
        deny(capability, "Environment denied")
    ceiling = environment.harness_policy.allowed_capabilities
    if ceiling is not None:
        for capability in declared - ceiling:
            deny(capability, "not in Environment allowlist")
    if environment.runtime.network is NetworkMode.NONE:
        for capability in _NETWORK_NONE_DENIALS:
            deny(capability, "Environment network=none")
    elif environment.runtime.network is NetworkMode.RESTRICTED:
        for capability in _NETWORK_RESTRICTED_DENIALS:
            deny(capability, "Environment network=restricted")
    if environment.runtime.read_only_root:
        deny(HarnessCapability.FILE_EDIT, "Environment read_only_root")
    return HarnessGrant(
        environment=environment.identity,
        harness=binding,
        declared=declared,
        granted=declared - denied,
        denied=frozenset(denied),
        denial_reasons=reasons,
    )


class JobSpec(FrozenModel):
    """Complete schema-v2 Job orchestration input."""

    schema_version: Literal["2"] = "2"
    source: JobSource
    agents: tuple[AgentBinding, ...] = Field(min_length=1)
    mode: JobMode = JobMode.EVAL
    attempts: int = Field(default=1, ge=1)
    concurrency: int = Field(default=1, ge=1)
    per_runtime_concurrency: int = Field(default=1, ge=1)
    priority: int = 0
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    run_id: str | None = Field(
        default=None,
        description=(
            "Distinguishes separate executions of the same configuration, so each run "
            "and rerun gets its own Job and Trial ids and never overwrites another."
        ),
    )

    @model_validator(mode="after")
    def _compatible(self) -> JobSpec:
        agent_ids = [agent.agent_id for agent in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("agents must have unique identities")
        for task in self.tasks:
            target = task.environment.runtime.requested_target
            if target not in task.environment.runtime.available_targets():
                reason = task.environment.runtime.target_exclusions().get(
                    target, "target unavailable"
                )
                raise ValueError(
                    f"Environment {task.environment.name!r} provider is not enforceable: {reason}"
                )
            for agent in self.agents:
                resolve_trial_harness_grant(task.environment, agent.agent)
        return self

    @property
    def tasks(self) -> tuple[TaskDefinition, ...]:
        """Selected Tasks in deterministic order."""
        return self.source.tasks

    @property
    def content_hash(self) -> str:
        """Stable Job configuration digest."""
        if self.run_id is None:
            return content_hash(self.model_dump(mode="json", exclude={"run_id"}))
        return content_hash(self)

    @property
    def job_id(self) -> str:
        """Stable Trial-set identity excluding retries and scheduling."""
        identity: dict[str, Any] = {
            "source": self.source,
            "agents": self.agents,
            "mode": self.mode,
            "attempts": self.attempts,
        }
        if self.run_id is not None:
            identity["run_id"] = self.run_id
        return stable_id("job", identity)

    def plan(self, catalog: ModelCatalog | None = None) -> JobPlan:
        """Expand Agent x Task x attempt and freeze per-Trial compatibility.

        Returns:
            The deterministic Trial plan and revision lock.
        """
        effective_catalog = catalog or ModelCatalog()
        benchmark = _benchmark_pin(self.source)
        task_pins = tuple(_task_pin(task) for task in self.tasks)
        resolutions = {
            agent.agent_id: _resolve_model(agent, effective_catalog) for agent in self.agents
        }
        trials = tuple(
            TrialSpec(
                job_id=self.job_id,
                agent_id=agent.agent_id,
                agent_name=agent.name,
                task_id=task.task_id,
                task_digest=task.content_hash,
                task_pin=_task_pin(task),
                benchmark=benchmark,
                attempt=attempt,
                model=resolutions[agent.agent_id],
                environment=task.environment.identity,
                verifier_digests=tuple(item.verifier.content_hash for item in task.verifiers),
                harness=agent.harness,
                harness_grant=resolve_trial_harness_grant(task.environment, agent.agent),
                mode=self.mode,
                runtime_provider=task.environment.runtime.provider,
                placement=task.environment.runtime.placement,
            )
            for agent in self.agents
            for task in self.tasks
            for attempt in range(1, self.attempts + 1)
        )
        lock = JobLock(
            job_id=self.job_id,
            spec_hash=self.content_hash,
            source_digest=(
                self.source.task.content_hash
                if isinstance(self.source, TaskJobSource)
                else self.source.benchmark.content_hash
            ),
            benchmark=benchmark,
            task_pins=task_pins,
            model_resolutions=tuple(resolutions[agent.agent_id] for agent in self.agents),
            task_digests=tuple(task.content_hash for task in self.tasks),
            environment_digests=tuple(task.environment.content_hash for task in self.tasks),
            verifier_digests=tuple(
                item.verifier.content_hash for task in self.tasks for item in task.verifiers
            ),
            agent_digests=tuple(agent.content_hash for agent in self.agents),
            harness_digests=tuple(
                agent.harness.digest for agent in self.agents if agent.harness is not None
            ),
            mode=self.mode,
        )
        return JobPlan(job_id=self.job_id, spec_hash=self.content_hash, lock=lock, trials=trials)


class TrialSpec(FrozenModel):
    """One independent Agent attempt."""

    job_id: str
    agent_id: str
    agent_name: str
    task_id: str
    task_digest: str
    task_pin: TaskPin
    benchmark: BenchmarkPin | None = None
    attempt: int = Field(ge=1)
    model: ModelResolution
    environment: EnvironmentIdentity
    verifier_digests: tuple[str, ...]
    harness: HarnessBinding | None = None
    harness_grant: HarnessGrant | None = Field(
        default=None, validation_alias=AliasChoices("harness_grant", "harness_stamp")
    )
    mode: JobMode
    runtime_provider: str
    placement: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @property
    def trial_id(self) -> str:
        """Stable identity independent of TrialExecution retries."""
        return stable_id(
            "trl",
            {
                "job_id": self.job_id,
                "agent_id": self.agent_id,
                "task_digest": self.task_digest,
                "attempt": self.attempt,
            },
        )


class TrialExecution(FrozenModel):
    """One retry execution of a Trial."""

    trial_id: str
    execution_id: int = Field(ge=0)
    status: ExecutionStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: ErrorCode | None = None


class JobLock(FrozenModel):
    """Complete immutable revision graph lock."""

    job_id: str
    spec_hash: str
    source_digest: str
    benchmark: BenchmarkPin | None = None
    task_pins: tuple[TaskPin, ...]
    model_resolutions: tuple[ModelResolution, ...]
    task_digests: tuple[str, ...]
    environment_digests: tuple[str, ...]
    verifier_digests: tuple[str, ...]
    agent_digests: tuple[str, ...]
    harness_digests: tuple[str, ...]
    mode: JobMode


class JobPlan(FrozenModel):
    """Deterministic Trial expansion."""

    job_id: str
    spec_hash: str
    lock: JobLock
    trials: tuple[TrialSpec, ...]

    @property
    def trial_count(self) -> int:
        """Number of independent Trials."""
        return len(self.trials)

    def __call__(self) -> JobPlan:
        """Return this plan, allowing property and legacy call-style access."""
        return self


PhaseName = Literal[
    "agent_setup",
    "environment_setup",
    "agent_execution",
    "artifact_collection",
    "verification",
    "cleanup",
]


class PhaseTiming(FrozenModel):
    """One timed phase of a TrialExecution, measured by the execution engine.

    Phases are recorded in the order they started. A phase may appear more than
    once, for example Agent setup before and after the sandbox exists, and
    phases may overlap. Their durations therefore describe accumulated work;
    wall-clock time is ``completed_at - started_at`` on the receipt.
    """

    name: PhaseName
    started_at: datetime
    completed_at: datetime

    @property
    def seconds(self) -> float:
        """Duration of this phase in seconds."""
        return (self.completed_at - self.started_at).total_seconds()


class TrialReceipt(FrozenModel):
    """Immutable TrialExecution provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    trial_id: str
    job_id: str
    execution_id: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1)
    task_digest: str
    task_pin: TaskPin
    benchmark: BenchmarkPin | None = None
    model: ModelResolution
    environment_digest: str
    verifier_digests: tuple[str, ...]
    agent_digest: str
    harness_digest: str = ""
    harness_grant: HarnessGrant | None = Field(
        default=None, validation_alias=AliasChoices("harness_grant", "harness_stamp")
    )
    mode: JobMode
    runtime_provider: str
    placement: dict[str, str] = Field(default_factory=dict)
    runtime_identity: str = ""
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    tito_artifact: ArtifactReference | None = None
    trace_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    phases: tuple[PhaseTiming, ...] = ()
    cost_usd: float | None = Field(default=None, ge=0)
    trust: Literal["self_reported", "imported_unverified"] = "self_reported"

    @property
    def receipt_hash(self) -> str:
        """Integrity digest.

        A receipt without phase timings hashes as it did before phases were
        recorded, so receipts written by earlier versions still verify.
        """
        payload = self.model_dump(mode="json")
        if not self.phases:
            payload.pop("phases")
        return content_hash(payload)


class TrialResult(FrozenModel):
    """Typed Trial outcome."""

    status: Literal["succeeded", "failed", "cancelled", "awaiting_review"]
    receipt: TrialReceipt
    score: float | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    verifier_results: tuple[VerifierResult, ...] = ()
    trace_id: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> TrialResult:
        if self.status == "failed" and self.error_code is None:
            raise ValueError("failed trials require a stable error_code")
        if self.status != "failed" and self.error_code is not None:
            raise ValueError("only failed trials may carry error_code")
        return self


class AgentAggregate(FrozenModel):
    """Minimal leaderboard row for one exact Agent revision.

    ``mean_score`` averages repeated attempts within each Task first, then
    combines Tasks with the Benchmark's declared weights, over the Tasks that
    have a score. ``coverage`` is the weighted share of Tasks that do. See
    :func:`plural.benchmarks.aggregate_configuration`.
    """

    agent_name: str
    agent_digest: str
    model_id: str
    count: int = Field(ge=0)
    successes: int = Field(ge=0)
    mean_score: float | None = None
    coverage: float = 0
    total_cost: float | None = None
    mean_latency_seconds: float | None = None


class JobResult(FrozenModel):
    """Collected Trial outcomes and optional Benchmark leaderboard."""

    job_id: str
    plan_hash: str
    status: Literal["succeeded", "failed", "cancelled", "awaiting_review"]
    trials: tuple[TrialResult, ...]
    benchmark: BenchmarkPin | None = None
    aggregates: tuple[AgentAggregate, ...] = ()


class Job:
    """Simple public runner for a Task or Benchmark and catalog-backed Agents."""

    def __init__(
        self,
        source: Task | Benchmark,
        agents: Sequence[Agent],
        *,
        mode: JobMode = JobMode.EVAL,
        attempts: int = 1,
        concurrency: int = 1,
        per_runtime_concurrency: int = 1,
        priority: int = 0,
        retry: RetryPolicy | None = None,
        provider: Any = None,
        providers: Mapping[str, Any] | None = None,
        registry: Any = None,
        store: Any = None,
        environ: Mapping[str, str] | None = None,
        resource_resolvers: Mapping[str, Any] | None = None,
        progress: Any = None,
        project_policy: Any = None,
        catalog: ModelCatalog | None = None,
        client: Any = None,
        api_key: str | None = None,
    ) -> None:
        if not isinstance(source, (Task, Benchmark)):
            raise TypeError(
                "Cannot create Job.\n"
                "source must be a Task or Benchmark.\n"
                f"Got {type(source).__name__}."
            )
        if not agents:
            raise ValueError(
                "Cannot create Job.\n"
                "A Job needs at least one Agent to run against the Task or Benchmark."
            )
        if any(not isinstance(agent, Agent) for agent in agents):
            raise TypeError(
                "Cannot create Job.\nagents must be Agent instances created from a catalog model."
            )
        if client is not None and api_key:
            raise ValueError(
                "Cannot create Job.\n"
                "Pass client=Client() or api_key=..., not both.\n"
                "Client uses your Plural login. api_key is a bring-your-own "
                "OpenAI-compatible key."
            )
        self.source = source
        self.agents = tuple(agents)
        self.client = client
        self.api_key = api_key
        job_source: JobSource
        if isinstance(source, Task):
            job_source = TaskJobSource(task=source._definition())
        else:
            job_source = BenchmarkJobSource(benchmark=source._definition())
        self.spec = JobSpec(
            source=job_source,
            agents=tuple(AgentBinding(agent=agent._definition()) for agent in self.agents),
            mode=mode,
            attempts=attempts,
            concurrency=concurrency,
            per_runtime_concurrency=per_runtime_concurrency,
            priority=priority,
            retry=retry or RetryPolicy(),
        )
        self.catalog = catalog or ModelCatalog()
        self.plan = self.spec.plan(self.catalog)
        self._runner_options = {
            "provider": provider,
            "providers": providers,
            "store": store,
            "environ": environ,
            "resource_resolvers": resource_resolvers,
            "progress": progress,
            "project_policy": project_policy,
            "catalog": self.catalog,
        }
        if registry is not None:
            self._runner_options["registry"] = registry
        self._runner_options = {
            key: value for key, value in self._runner_options.items() if value is not None
        }

    def _credential_environ(self) -> dict[str, str]:
        configured = self._runner_options.get("environ")
        current = dict(os.environ if configured is None else configured)
        if (
            self._runner_options.get("provider") is not None
            or self._runner_options.get("providers") is not None
        ):
            return current
        agents = getattr(self.spec, "agents", ())
        if agents and all(binding.auth_mode == "none" for binding in agents):
            # Credential-free Jobs never call a live model endpoint, so no
            # Plural or provider key is required to run them.
            return current
        if self.client is not None:
            key = getattr(self.client, "api_key", None)
            if not key:
                raise ValueError(
                    "Cannot run Job.\n"
                    "client= was passed but the Client has no API key.\n"
                    "Run `plural auth login`, export PLURAL_API_KEY, or "
                    "construct Client(api_key=...)."
                )
            current.setdefault("PLURAL_API_KEY", str(key))
            gateway = getattr(self.client, "base_url", None)
            if gateway:
                current.setdefault("PLURAL_GATEWAY_URL", str(gateway))
            return current
        if self.api_key:
            current.setdefault("OPENAI_API_KEY", self.api_key)
            return current
        if current.get("PLURAL_API_KEY") or current.get("OPENAI_API_KEY"):
            return current
        raise ValueError(
            "Cannot run Job.\n"
            "A live model call needs Plural or a bring-your-own key.\n"
            "SDK:  Job(task, agents=[agent], client=Client())\n"
            "SDK:  Job(task, agents=[agent], api_key='...')\n"
            "CLI:  plural auth login && plural run --task <name> --model <model>"
        )

    @property
    def content_hash(self) -> str:
        """Stable hash of this resolved public Job configuration."""
        return self.spec.content_hash

    async def run_async(self, *, resume: bool = False) -> JobResult:
        """Execute this Job without blocking the caller's event loop.

        Returns:
            The collected Trial outcomes.
        """
        from plural.execution.engine import JobRunner

        options = dict(self._runner_options)
        options["environ"] = self._credential_environ()
        return await JobRunner(self.spec, **options).run(resume=resume)

    def run(self, *, resume: bool = False) -> JobResult:
        """Execute synchronously when no event loop is already running.

        Returns:
            The collected Trial outcomes.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(resume=resume))
        raise RuntimeError(
            "Job.run() cannot be called inside a running event loop; "
            "use 'await job.run_async()' instead"
        )


__all__ = [
    "AgentAggregate",
    "ArtifactManifest",
    "ArtifactManifestEntry",
    "ArtifactReference",
    "BenchmarkPin",
    "BenchmarkJobSource",
    "ExecutionStatus",
    "Job",
    "JobLock",
    "JobMode",
    "JobPlan",
    "JobResult",
    "JobSource",
    "JobSpec",
    "ModelResolution",
    "ProgressEvent",
    "RetryPolicy",
    "TITORecord",
    "TaskJobSource",
    "TrialExecution",
    "PhaseName",
    "PhaseTiming",
    "TrialReceipt",
    "TrialResult",
    "TrialSpec",
    "TrialStatus",
    "VerifierResult",
    "resolve_trial_harness_grant",
]
