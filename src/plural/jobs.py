"""Schema-v2 Job, Trial, event, result, and TITO orchestration contracts."""

from __future__ import annotations

import asyncio
import json
import math
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from plural.agents import Agent, AgentBinding, AgentDefinition
from plural.catalog import ModelCatalog
from plural.checkpoints import Checkpoint, History
from plural.common import (
    SHA256_PATTERN,
    ErrorCode,
    FrozenModel,
    HarnessBinding,
    HarnessCapability,
    canonical_json,
    content_hash,
    stable_id,
)
from plural.config import resolve_gateway_url
from plural.credentials import CredentialUse, CredentialValue
from plural.environments.definition import (
    EnvironmentDefinition,
    EnvironmentIdentity,
    HarnessGrant,
    party_seats,
)
from plural.local_models import LocalModelError, LocalModelIdentity, Status
from plural.metrics import MetricAggregate, MetricFailure
from plural.rewards import RewardFailure
from plural.sandbox.models import NetworkMode
from plural.tasks import Benchmark, BenchmarkDefinition, Task, TaskDefinition, TaskPin
from plural.trust import TrustAssessment
from plural.volumes import VolumeVersion


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
    """A Job selecting one Benchmark revision.

    It runs the Benchmark's dev Tasks, or, with ``include_heldout``, its
    held-out Tasks alone: each such run is a peek, and is counted. Dev results
    come from the ordinary run, so a proof never pays for the dev Tasks twice.
    """

    kind: Literal["benchmark"] = "benchmark"
    benchmark: BenchmarkDefinition
    include_heldout: bool = False

    @model_serializer(mode="wrap")
    def _omit_dev_only(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        # A dev-only run serializes, and so hashes, as every run did before held-out Tasks.
        if isinstance(data, dict) and not self.include_heldout:
            data.pop("include_heldout", None)
        return data

    @property
    def tasks(self) -> tuple[TaskDefinition, ...]:
        """Selected Tasks: the dev Tasks, or with ``include_heldout`` the held-out ones alone."""
        if self.include_heldout:
            return self.benchmark.heldout_definitions
        return self.benchmark.dev_tasks

    @property
    def heldout_tasks(self) -> tuple[str, ...]:
        """The held-out Tasks this Job runs, by name: none unless included."""
        return self.benchmark.heldout if self.include_heldout else ()


JobSource = Annotated[TaskJobSource | BenchmarkJobSource, Field(discriminator="kind")]


def _without_local_paths(value: Any) -> Any:
    """Name every local source that has a digest by that digest alone.

    Returns:
        The value, without those sources' paths.
    """
    if isinstance(value, dict):
        if value.get("kind") == "local" and value.get("digest") and "uri" in value:
            value = {key: item for key, item in value.items() if key != "uri"}
        return {key: _without_local_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_local_paths(item) for item in value]
    return value


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
    if agent.external is not None:
        return ModelResolution(
            catalog_model_id=agent.model,
            provider="external",
            endpoint=f"external:{urlsplit(agent.external.url).hostname}",
            upstream_id=agent.model,
        )
    if agent.agent.endpoint is not None:
        return ModelResolution(
            catalog_model_id=agent.model,
            provider="endpoint",
            endpoint=f"endpoint:{urlsplit(agent.agent.endpoint).netloc}",
            upstream_id=agent.model,
        )
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


def _check_external_agent(mode: JobMode, task: TaskDefinition, agent: AgentBinding) -> None:
    if mode is JobMode.TRAIN:
        raise ValueError(
            f"A train Job cannot use external Agent {agent.name!r}: training needs the "
            "exact tokens of every model call, which a service of its own does not report."
        )
    if task.party is not None:
        raise ValueError(
            f"External Agent {agent.name!r} cannot take a seat in Task {task.task_id!r} "
            "yet; it can work Tasks one Agent works alone."
        )
    policy = task.environment.harness_policy
    if policy.mode == "allowlist" and "external" not in policy.allowed_harnesses:
        raise ValueError(
            f"Environment {task.environment.name!r} allows only the Harnesses it lists; add "
            "'external' to them to let an external Agent work it."
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
    event_id: str | None = None
    """The ``event_id`` of the model call this record captured."""
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
    output_token_offsets: tuple[tuple[int, int], ...] | None = None
    """Each output token's character range in ``output_text``, when the Harness knows it.

    A training export uses it to turn a character span reward into a token range.
    """

    @model_validator(mode="after")
    def _validated_lengths(self) -> TITORecord:
        size = len(self.output_token_ids)
        if self.output_token_offsets is not None and len(self.output_token_offsets) != size:
            raise ValueError("output_token_offsets must have one range per output token")
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
    seats: dict[str, float] = Field(default_factory=dict)
    """Each seat's score, for a Task several Agents share."""
    metrics: dict[str, float | None] = Field(default_factory=dict)
    """The metrics its ``check`` returned; ``None`` where one does not apply."""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def _finite(self) -> VerifierResult:
        values = [
            *self.scores.values(),
            *self.seats.values(),
            *(item for item in self.metrics.values() if item is not None),
        ]
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


JobPurpose = Literal["eval", "diagnose", "fork", "confirm", "learn"]
REFUSE_HELDOUT: frozenset[str] = frozenset({"diagnose", "fork", "learn"})
"""Job purposes that may never run, or read, a held-out Task.

A ``learn`` Job lets an Agent keep what it learns across episodes, so a
held-out Task it learned from could no longer confirm anything.
"""

ForkRole = Literal["candidate", "control"]


class ForkChange(FrozenModel):
    """One change applied at the fork point, which makes the fork diagnostic."""

    name: str = Field(min_length=1)
    payload: Any = None


class ForkSpec(FrozenModel):
    """A fork Job: Trials that continue one Trial from its checkpoint after ``step``.

    Each candidate Agent gets ``attempts`` forks, and the original Agent, the
    control, as many again. With ``seat``, only that seat's Agent is replaced;
    the other seats continue with their original Agents.
    """

    trial_id: str
    job_id: str = ""
    checkpoint: Checkpoint
    control_agent_id: str
    candidate_agent_ids: tuple[str, ...] = Field(min_length=1)
    seat: str | None = None
    change: ForkChange | None = None
    bundle: str | None = Field(
        default=None,
        description="Path of the original Trial's workspace.bundle, read by the Job only.",
    )
    hosted_trial_id: str | None = Field(
        default=None,
        description="The original Trial's id in the hosted project, when it was recorded.",
    )

    @property
    def step(self) -> int:
        """The step the fork continues after."""
        return self.checkpoint.step

    @property
    def controls_follow(self) -> bool:
        """Whether the controls' attempts follow the candidates'.

        A diagnostic fork of the original Agent runs it twice per attempt, with
        the change and without, so the two can't share attempt numbers.
        """
        return self.change is not None and self.control_agent_id in self.candidate_agent_ids

    @property
    def diagnostic(self) -> bool:
        """Whether a change makes this fork a diagnosis rather than something to ship."""
        return self.change is not None


class TrialFork(FrozenModel):
    """A Trial's place in a fork Job."""

    trial_id: str
    step: int = Field(ge=0)
    role: ForkRole
    checkpoint_digest: str
    seat: str | None = None
    change: str | None = None


class ResumeRecord(FrozenModel):
    """What a resumed execution records: the run checkpoint it continued from.

    A resumed execution is the same Trial, not a fork: its steps, States, and
    metric points before ``step`` are the interrupted execution's, and its
    cost and turns include what that execution spent.
    """

    from_execution_id: int = Field(ge=0)
    step: int = Field(ge=0)
    sim_time: float | None = None
    checkpoint_digest: str
    history: Literal["native", "transcript", "none"] = "native"
    carried_cost_usd: float | None = Field(default=None, ge=0)
    carried_turns: int = Field(default=0, ge=0)
    carried_seconds: float = Field(default=0.0, ge=0)


class ForkRecord(FrozenModel):
    """What a fork Trial records: where it started and how the history reached its Agent."""

    of_trial_id: str
    step: int = Field(ge=0)
    role: ForkRole | None = None
    history: History
    checkpoint_digest: str
    warnings: tuple[str, ...] = ()
    seat: str | None = None
    change: str | None = None
    from_checkpoint: str | None = None
    """``TRIAL/NAME`` when the Task, not a fork Job, named the checkpoint."""
    of_hosted_trial_id: str | None = None
    """The original Trial's id in the hosted project, when it was recorded."""
    volume: VolumeVersion | None = None
    """The Volume version restored at the fork point, once Volumes exist."""


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
    party: tuple[str, ...] = Field(
        default=(),
        description=(
            "For a Task whose Environment has a party: the Agents, by name, that share "
            "each episode, in seat order. Name an Agent more than once for self-play. "
            "Empty, every Agent of the Job plays, once each."
        ),
    )
    opponents: tuple[str, ...] = Field(
        default=(),
        description=(
            "For a Benchmark Job: the Agents, by name, that fill the other seats at a Task "
            "several Agents share, the Benchmark's fixed opponents. They play and are not "
            "ranked, and run no other Task."
        ),
    )
    purpose: JobPurpose = Field(
        default="eval",
        description=(
            "Why the Job runs: eval, diagnose, fork, confirm, or learn. Diagnosis, "
            "forks, and learning never run held-out Tasks."
        ),
    )
    fork: ForkSpec | None = Field(
        default=None,
        description="For a fork Job: the checkpoint, the candidates, and the control.",
    )
    portable: bool = Field(
        default=False,
        description=(
            "The Job's identity names its local sources by content, not by path, so the "
            "same project plans the same Job and Trial ids in any folder on any machine."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_no_party(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        # A Job without a party or a purpose serializes, and so hashes, as it did
        # before each existed.
        if isinstance(data, dict):
            if not self.party:
                data.pop("party", None)
            if not self.opponents:
                data.pop("opponents", None)
            if self.purpose == "eval":
                data.pop("purpose", None)
            if self.fork is None:
                data.pop("fork", None)
            if not self.portable:
                data.pop("portable", None)
        return data

    @model_validator(mode="after")
    def _compatible(self) -> JobSpec:
        agent_ids = [agent.agent_id for agent in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("agents must have unique identities")
        heldout = self.source.heldout_tasks if isinstance(self.source, BenchmarkJobSource) else ()
        if heldout and self.purpose in REFUSE_HELDOUT:
            why = (
                "an Agent that learned from them could no longer be confirmed on them"
                if self.purpose == "learn"
                else "diagnosis never sees them"
            )
            raise ValueError(
                f"A {self.purpose} Job cannot run held-out Tasks ({', '.join(heldout)}): "
                f"held-out Tasks are kept for confirming a fix, so {why}.\nNext: "
                "plural run --benchmark BENCHMARK --heldout runs them, as a counted peek."
            )
        if self.fork is not None:
            self._check_fork(self.fork)
        names = {agent.name for agent in self.agents}
        unknown = sorted(set(self.party) - names)
        if unknown:
            raise ValueError(
                f"party names {', '.join(map(repr, unknown))}, which are not Agents of the "
                f"Job; its Agents are {', '.join(sorted(names))}"
            )
        unknown = sorted(set(self.opponents) - names)
        if unknown:
            raise ValueError(
                f"opponents names {', '.join(map(repr, unknown))}, which are not Agents of the "
                "Job; add each opponent to agents"
            )
        if self.opponents and not self.evaluated_agents:
            raise ValueError("every Agent of the Job is an opponent, so none would be ranked")
        for task in self.tasks:
            if task.party is None:
                continue
            size = task.party_size if self.rotates else None
            reason = task.party.check(size or len(self.party_agents))
            if reason is not None:
                raise ValueError(f"Task {task.task_id!r}: {reason}.")
        for task in self.tasks:
            target = task.environment.runtime.requested_target
            if target not in task.environment.runtime.available_targets():
                reason = task.environment.runtime.target_exclusions().get(
                    target, "target unavailable"
                )
                raise ValueError(
                    f"Environment {task.environment.name!r} provider is not enforceable: {reason}"
                )
            if self.mode is JobMode.TRAIN:
                live = [item.name for item in task.environment.apps if item.control == "live"]
                if live:
                    raise ValueError(
                        f"A train Job cannot use Task {task.task_id!r}: its Environment has "
                        f"live Apps ({', '.join(live)}) that Plural cannot reset, so episodes "
                        "would not start from the Task's state. Give each a reset hook."
                    )
            for agent in self.agents:
                resolve_trial_harness_grant(task.environment, agent.agent)
                if agent.external is not None:
                    _check_external_agent(self.mode, task, agent)
        return self

    def _check_fork(self, fork: ForkSpec) -> None:
        if self.purpose != "fork":
            raise ValueError("A Job with a fork must have purpose fork.")
        if fork.checkpoint.heldout:
            raise ValueError(
                f"Trial {fork.trial_id} ran a held-out Task, so it cannot be forked: held-out "
                "Tasks are kept for confirming a fix."
            )
        if len(self.tasks) != 1:
            raise ValueError("A fork Job continues one Trial, so it has exactly one Task.")
        ids = {agent.agent_id for agent in self.agents}
        named = {fork.control_agent_id, *fork.candidate_agent_ids}
        if not named <= ids:
            raise ValueError("A fork names Agents that are not in the Job.")
        if fork.control_agent_id in fork.candidate_agent_ids and fork.change is None:
            raise ValueError(
                "A fork's candidate is the original Agent, which already runs as the control. "
                "Change the Agent, or use --change for a diagnostic fork."
            )
        if self.tasks[0].party is not None and fork.seat is None:
            raise ValueError("A fork of a Trial several Agents share must name a --seat.")

    @property
    def tasks(self) -> tuple[TaskDefinition, ...]:
        """Selected Tasks in deterministic order."""
        return self.source.tasks

    @property
    def rotates(self) -> bool:
        """Whether Tasks several Agents share are seated by the Benchmark's rules.

        A Benchmark Job seats each evaluated Agent in turn, against its
        opponents; a Job that names its ``party`` plays exactly that party.
        """
        return isinstance(self.source, BenchmarkJobSource) and not self.party

    @property
    def evaluated_agents(self) -> tuple[AgentBinding, ...]:
        """The Agents being ranked: every Agent but the opponents."""
        return tuple(agent for agent in self.agents if agent.name not in set(self.opponents))

    def seatings(self, task: TaskDefinition) -> tuple[tuple[AgentBinding, ...], ...]:
        """The parties that play a Task several Agents share, each in seat order.

        In a Benchmark Job, each evaluated Agent plays with the opponents in
        the other seats, in their order and repeated if there are too few,
        once from every seat with ``seatings: rotate``, or from ``seat_1``.
        Without opponents, a cooperative Task seats the Agent in every seat.
        Any other Job plays its :attr:`party_agents`.

        Returns:
            The parties, without repeats.
        """
        if not self.rotates:
            return (self.party_agents,)
        assert isinstance(self.source, BenchmarkJobSource)
        size = task.party_size or len(self.party_agents)
        by_name = {agent.name: agent for agent in self.agents}
        opponents = [by_name[name] for name in self.opponents]
        rotate = self.source.benchmark.seatings == "rotate"
        parties: list[tuple[AgentBinding, ...]] = []
        for agent in self.evaluated_agents:
            if not opponents:
                parties.append((agent,) * size)
                continue
            others = [opponents[index % len(opponents)] for index in range(size - 1)]
            for position in range(size if rotate else 1):
                parties.append(tuple(others[:position] + [agent] + others[position:]))
        unique = {tuple(agent.name for agent in party): party for party in parties}
        return tuple(unique.values())

    @property
    def party_agents(self) -> tuple[AgentBinding, ...]:
        """The Agents that share each episode of a Task with a party, in seat order."""
        if not self.party:
            return self.agents
        by_name = {agent.name: agent for agent in self.agents}
        return tuple(by_name[name] for name in self.party)

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
        if self.party:
            identity["party"] = self.party
        if self.opponents:
            identity["opponents"] = self.opponents
        if self.purpose != "eval":
            identity["purpose"] = self.purpose
        if self.fork is not None:
            identity["fork"] = {
                "trial": self.fork.trial_id,
                "checkpoint": self.fork.checkpoint.digest,
                "candidates": self.fork.candidate_agent_ids,
                "seat": self.fork.seat,
                "change": self.fork.change,
            }
        if self.portable:
            return stable_id("job", _without_local_paths(json.loads(canonical_json(identity))))
        return stable_id("job", identity)

    @property
    def max_attempt(self) -> int:
        """The highest attempt number the plan uses.

        That is ``attempts``, or twice it when a diagnostic fork's controls follow
        its candidates.
        """
        if self.fork is not None and self.fork.controls_follow:
            return self.attempts * 2
        return self.attempts

    @property
    def agent_attempts(self) -> dict[str, int]:
        """Agents whose Trials stop short of :attr:`max_attempt`, with their highest attempt.

        Empty except in a diagnostic fork whose controls follow its candidates:
        there the original Agent runs to twice ``attempts`` and the others to
        ``attempts``.
        """
        if self.fork is None or not self.fork.controls_follow:
            return {}
        highest: dict[str, int] = {}
        for trial in self.plan().trials:
            highest[trial.agent_id] = max(highest.get(trial.agent_id, 0), trial.attempt)
        return {key: value for key, value in highest.items() if value < self.max_attempt}

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

        def trial(
            task: TaskDefinition,
            attempt: int,
            party: Sequence[AgentBinding],
            role: ForkRole | None = None,
        ) -> TrialSpec:
            agent = party[0]
            seats = tuple(
                SeatAssignment(
                    seat=seat,
                    agent_id=player.agent_id,
                    agent_name=player.name,
                    model=resolutions[player.agent_id],
                    harness=player.harness,
                    harness_grant=resolve_trial_harness_grant(task.environment, player.agent),
                )
                for seat, player in zip(party_seats(len(party)), party, strict=True)
                if task.party is not None
            )
            return TrialSpec(
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
                seats=seats,
                fork=(
                    TrialFork(
                        trial_id=self.fork.trial_id,
                        step=self.fork.step,
                        role=role,
                        checkpoint_digest=self.fork.checkpoint.digest,
                        seat=self.fork.seat,
                        change=self.fork.change.name
                        if self.fork.change is not None and role == "candidate"
                        else None,
                    )
                    if self.fork is not None and role is not None
                    else None
                ),
            )

        solo = [task for task in self.tasks if task.party is None]
        shared = [task for task in self.tasks if task.party is not None]
        if self.fork is not None:
            trials = self._fork_trials(trial)
        else:
            trials = tuple(
                trial(task, attempt, (agent,))
                for agent in self.evaluated_agents
                for task in solo
                for attempt in range(1, self.attempts + 1)
            ) + tuple(
                trial(task, attempt, party)
                for task in shared
                for party in self.seatings(task)
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

    def _fork_trials(self, trial: Any) -> tuple[TrialSpec, ...]:
        """Each candidate's forks, then the controls: the original Agent from the same point.

        Returns:
            The Trials, in order.
        """
        fork = self.fork
        assert fork is not None
        task = self.tasks[0]
        by_id = {agent.agent_id: agent for agent in self.agents}
        attempts = range(1, self.attempts + 1)

        def seated(agent: AgentBinding) -> tuple[AgentBinding, ...]:
            if task.party is None:
                return (agent,)
            seats = party_seats(len(self.party_agents))
            index = seats.index(str(fork.seat))
            party = list(self.party_agents)
            party[index] = agent
            return tuple(party)

        candidates = tuple(
            trial(task, attempt, seated(by_id[agent_id]), "candidate")
            for agent_id in fork.candidate_agent_ids
            for attempt in attempts
        )
        control = by_id[fork.control_agent_id]
        shift = self.attempts if fork.controls_follow else 0
        controls = tuple(
            trial(
                task,
                attempt + shift,
                seated(control) if task.party is None else self.party_agents,
                "control",
            )
            for attempt in attempts
        )
        return candidates + controls


class SeatAssignment(FrozenModel):
    """Which Agent plays one seat of a Trial several Agents share."""

    seat: str
    agent_id: str
    agent_name: str
    model: ModelResolution
    harness: HarnessBinding | None = None
    harness_grant: HarnessGrant | None = None


class TrialSpec(FrozenModel):
    """One independent Agent attempt.

    For a Task with seats, ``seats`` names the Agent in each, and ``agent_id``
    is the first seat's.
    """

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
    seats: tuple[SeatAssignment, ...] = ()
    fork: TrialFork | None = None

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @model_serializer(mode="wrap")
    def _omit_no_fork(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        if isinstance(data, dict) and self.fork is None:
            data.pop("fork", None)
        return data

    @property
    def trial_id(self) -> str:
        """Stable identity independent of TrialExecution retries."""
        identity: dict[str, Any] = {
            "job_id": self.job_id,
            "agent_id": self.agent_id,
            "task_digest": self.task_digest,
            "attempt": self.attempt,
        }
        if self.seats:
            identity["seats"] = [[item.seat, item.agent_id] for item in self.seats]
        if self.fork is not None:
            identity["fork"] = self.fork.role
        return stable_id("trl", identity)

    @property
    def agent_ids(self) -> tuple[str, ...]:
        """Every Agent in the Trial, once each, in seat order."""
        if not self.seats:
            return (self.agent_id,)
        return tuple(dict.fromkeys(item.agent_id for item in self.seats))


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


class SeatResult(FrozenModel):
    """How one seat of a Trial several Agents share did.

    ``score`` weighs each Verifier's score for this seat as the Trial's own
    score weighs theirs; a Verifier that scores no seats gives every seat
    its episode score. ``artifact_root`` is where the seat's Harness output,
    its trace from its own side of the table, sits among the Trial's artifacts.
    ``metrics`` holds the running metrics a ``measure`` hook gave per seat, and
    ``passed`` the seat's own gates on them.
    """

    seat: str
    agent_id: str
    agent_name: str
    agent_digest: str
    score: float | None = None
    step_reward_total: float = 0.0
    steps: int = Field(default=0, ge=0)
    trace_id: str | None = None
    artifact_root: str = ""
    cost_usd: float | None = Field(default=None, ge=0)
    error_message: str | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    """This seat's value of each running metric measured per seat."""
    gates: dict[str, bool] = Field(default_factory=dict)
    """Each per-seat gate's verdict for this seat."""
    passed: bool | None = None
    """Whether this seat passed every applicable per-seat gate; ``None`` when none applied."""


def _stored_api_key() -> str | None:
    """The API key ``plural auth login`` stored, read as :class:`plural.Client` reads it.

    Returns:
        The key, or ``None`` when no login holds one.
    """
    from plural.auth import resolve_session

    try:
        return resolve_session().api_key
    except (OSError, ValueError):
        return None


IntegrityCode = Literal[
    "no_trace",
    "actions_not_observed",
    "actions_not_traced",
    "answer_differs",
    "trace_outside_episode",
    "model_calls_differ",
    "forbidden_read",
    "egress_denied",
    "suspicious_success",
    "grader_file_touch",
    "canary_seen",
    "solution_lookup",
    "grader_special_casing",
    "false_claim",
    "instruction_violation",
    "model_answers_changed",
    "sim_leak",
    "eval_awareness",
]

IntegritySeverity = Literal["info", "warning", "critical"]
IntegritySource = Literal["external_trace", "detector", "judge"]


class IntegrityFinding(FrozenModel):
    """One sign that a Trial's result may not mean what its score says.

    Findings cover every Agent: an External Agent's self-reported trace
    departing from what Plural observed, a deterministic detector over the
    recorded episode, or the hack judge. Evidence for a person to read; a
    finding never changes a score on its own. A Benchmark's ``integrity``
    rule decides whether ``critical`` findings exclude or zero a Trial, and
    results then carry both the raw and the adjusted numbers.

    Attributes:
        code: What kind of problem this is.
        message: One line a person can act on.
        severity: ``info``, ``warning`` (the default), or ``critical``.
        steps: Step indexes, from 1, that show the problem.
        source: What found it: ``external_trace``, ``detector``, or ``judge``.
    """

    code: IntegrityCode
    message: str
    severity: IntegritySeverity = "warning"
    steps: tuple[int, ...] = ()
    source: IntegritySource = "external_trace"


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
    credentials: tuple[CredentialUse, ...] = ()
    """Which Agent credentials the Apps used, for audit. Never their values."""
    app_isolation: Literal["os_user", "none"] | None = None
    """How the App host was kept from the Harness: ``os_user`` when it ran as
    its own OS user and the Harness could not read its folder, ``none`` when
    they shared one, as on the local Runtime. ``None`` without Apps."""
    seats: tuple[SeatResult, ...] = ()
    """Each seat's Agent and score, for a Task several Agents share."""
    seat_isolation: Literal["os_user", "none"] | None = None
    """How seats were kept from one another: ``os_user`` when each seat's
    Harness ran as its own OS user, unable to read another's files or
    process. ``None`` without seats."""
    seed: int | None = None
    """The seed the Apps started from, the same for every Agent on this attempt
    of the Task. ``None`` for a Trial run before seeds were recorded."""
    stop_reason: str = ""
    """How the episode ended, one of :data:`plural.STOP_REASONS`; ``error``
    for a failed Trial whose Harness reported none, empty when unreported."""
    step_reward_total: float = 0.0
    """The episode total of per-step rewards in the reward ledger, each
    times its weight. Only ``check: total_reward`` turns it into a score."""
    reward_failures: tuple[RewardFailure, ...] = ()
    """Each Verifier whose ``reward`` function raised, on how many steps, and
    the first error. Those steps earned it no reward."""
    turns: int = Field(default=0, ge=0)
    """Model turns the Harness reported taking."""
    integrity: tuple[IntegrityFinding, ...] = ()
    """Signs the result may be gamed or leaked: an External Agent's trace that
    departs from what Plural observed, and what the deterministic detectors
    found in the recorded episode. Never a score."""
    trust: TrustAssessment | None = None
    """How far this result can be trusted, from how it ran: its tier and the
    reasons it is not higher. ``None`` when the Trial never reached a sandbox."""
    model_identity: LocalModelIdentity | None = None
    """For an endpoint Agent, what its model server was running when the
    Trial started, its fingerprint, and how the run came to trust it."""
    metrics: dict[str, float | None] = Field(default_factory=dict)
    """Every metric's value on this Trial: the built-ins, what each Verifier's
    ``check`` returned, and each running metric's aggregate. ``None`` means it
    does not apply here, and is left out of every aggregate."""
    metric_failures: tuple[MetricFailure, ...] = ()
    """Each Verifier whose ``measure`` hook failed, on how many steps. Never fatal."""
    gates: dict[str, bool] = Field(default_factory=dict)
    """Each applicable gate's verdict, for the metrics the Task's Verifiers mark
    ``gate: true``. A gate whose value is ``None`` does not apply and is left out."""
    passed: bool | None = None
    """Whether every applicable gate passed. ``None`` when no gate applies (the
    Trial is not judged) or while a Verifier awaits review; ``False`` for a
    Trial that failed and has gates."""
    tools_offered: tuple[str, ...] = ()
    """Every tool the Agent was offered: the Environment's actions and its
    Harness's own tools."""
    fork: ForkRecord | None = None
    """For a Trial that started from a checkpoint: where, and how the history
    reached its Agent."""
    environment_cost_usd: float | None = Field(default=None, ge=0)
    """What the Environment's simulated people (``plural.sim.Persona``) cost.
    Never part of the Agent's cost. ``None`` when no persona called a model."""
    resumed: ResumeRecord | None = None
    """For an execution that continued an interrupted one from its latest run
    checkpoint: where, and what it carried over."""
    volume_in: VolumeVersion | None = None
    """The Volume version the Agent started from. ``None`` until Volumes exist."""
    volume_out: VolumeVersion | None = None
    """The Volume version a ``learn`` Trial wrote. ``None`` for every other Trial."""

    @model_validator(mode="after")
    def _shape(self) -> TrialResult:
        from plural.verifiers import STOP_REASONS

        if self.status == "failed" and self.error_code is None:
            raise ValueError("failed trials require a stable error_code")
        if self.status != "failed" and self.error_code is not None:
            raise ValueError("only failed trials may carry error_code")
        if self.stop_reason and self.stop_reason not in STOP_REASONS:
            raise ValueError(f"unknown stop_reason {self.stop_reason!r}")
        return self


class SeatAggregate(FrozenModel):
    """One Agent's results from one seat, across the Trials it sat there."""

    count: int = Field(ge=0)
    mean_score: float | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    """Each metric's mean over the Trials it applied to, from this seat's own values."""
    pass_rate: float | None = None
    """The share of this seat's judged Trials that passed: by the seat's own gates where
    one applied to it, else by the Trial's. ``None`` when none was judged."""
    gates: dict[str, float] = Field(default_factory=dict)
    """Each per-seat gate's pass rate over the seats it judged."""


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
    metrics: dict[str, MetricAggregate] = Field(default_factory=dict)
    """Every metric across this Agent's Trials, by name, with how many it applied to."""
    primary_metric: str = "score"
    """What the leaderboard ranks on: ``score``, or a metric the Benchmark names."""
    primary: float | None = None
    """This Agent's value of ``primary_metric``: ``mean_score`` for ``score``, else
    the metric's mean (the share of 1s, for a binary metric)."""
    pass_rate: float | None = None
    """The pass rate: the share of this Agent's judged Trials that passed every
    applicable gate. ``None`` when no Trial was judged. At a Task several Agents
    share, each seat it played counts once, judged by the seat's own gates where one
    applied to it. The success rate, which counts scores at the success threshold, is
    separate."""
    seats: dict[str, SeatAggregate] = Field(default_factory=dict)
    """At Tasks several Agents share: this Agent's results from each seat it played."""
    opponent: bool = False
    """A Benchmark's fixed opponent: it played, and is not ranked."""

    @model_serializer(mode="wrap")
    def _omit_solo(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        if isinstance(data, dict):
            if not self.seats:
                data.pop("seats", None)
            if not self.opponent:
                data.pop("opponent", None)
        return data


class JobResult(FrozenModel):
    """Collected Trial outcomes and optional Benchmark leaderboard."""

    job_id: str
    plan_hash: str
    status: Literal["succeeded", "failed", "cancelled", "awaiting_review"]
    trials: tuple[TrialResult, ...]
    benchmark: BenchmarkPin | None = None
    aggregates: tuple[AgentAggregate, ...] = ()
    stopped: str | None = None
    """Why the Job stopped before every Trial ran, such as a rejected API key,
    which would fail every Trial alike. ``None`` when it ran to the end."""


class Job:
    """Simple public runner for a Task or Benchmark and catalog-backed Agents.

    ``credentials`` gives each Agent's credential values by Agent name, such as
    ``{"sales-bot": {"SALESFORCE_TOKEN": token}}``. A credential an Agent
    declares and is not given here is read from the exported variable of the
    same name.

    For a Task whose Environment has a party, ``party`` lists the Agents that
    share each episode, in seat order; list one Agent more than once for
    self-play. Left out, every Agent in ``agents`` plays, once each.

    A Benchmark Job seats its party Tasks by the Benchmark's ``seatings``:
    each Agent in ``agents`` plays from every seat, with ``opponents``, the
    Benchmark's fixed opponents, in the others. Opponents are not ranked.

    ``episode_server`` says where the Job serves an external Agent's episodes;
    by default it listens on a free loopback port.

    An Agent with its own ``endpoint`` runs whatever model its server
    answers with, whatever the Agent's ``model`` says. Before the first Trial
    the Job asks the server what it is running and refuses a model whose
    fingerprint nobody has accepted, naming what it found. ``plural run``
    asks once and remembers the answer; ``allow_local_models=True`` goes
    ahead without one. Each Trial records the identity either way, as
    ``TrialResult.model_identity``.

    A Benchmark Job runs its dev Tasks. ``heldout=True`` runs its held-out
    Tasks alone; each such run is a peek, and ``plural run`` counts it.
    ``purpose`` says why the Job runs; ``diagnose`` and ``fork`` Jobs refuse
    held-out Tasks. Each Trial records its ``gates``, from the
    metrics its Task's Verifiers mark ``gate: true``, and whether it ``passed``.
    """

    def __init__(
        self,
        source: Task | Benchmark,
        agents: Sequence[Agent],
        *,
        party: Sequence[Agent] | None = None,
        opponents: Sequence[Agent] | None = None,
        mode: JobMode = JobMode.EVAL,
        attempts: int = 1,
        concurrency: int | Literal["auto"] = 1,
        per_runtime_concurrency: int | None = None,
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
        credentials: Mapping[str, Mapping[str, str]] | None = None,
        episode_server: Any = None,
        allow_local_models: bool = False,
        heldout: bool = False,
        purpose: JobPurpose = "eval",
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
                "Both select the Plural gateway; api_key is a Plural API key."
            )
        if opponents and not isinstance(source, Benchmark):
            raise ValueError(
                "Cannot create Job.\nopponents are a Benchmark's; a Job of one Task names "
                "its party instead."
            )
        if any(
            member is agent or (member.name and member.name == agent.name)
            for member in opponents or ()
            for agent in agents
        ):
            raise ValueError(
                "Cannot create Job.\nAn Agent can't be both ranked and an opponent; name it "
                "in agents or in opponents."
            )
        self.source = source
        self.agents = tuple(agents) + tuple(opponents or ())
        self.allow_local_models = allow_local_models
        self.client = client
        self.api_key = api_key
        job_source: JobSource
        if isinstance(source, Task):
            if heldout:
                raise ValueError("Cannot create Job.\nheldout applies to a Benchmark, not a Task.")
            job_source = TaskJobSource(task=source._definition())
        else:
            job_source = BenchmarkJobSource(benchmark=source._definition(), include_heldout=heldout)
        bindings = tuple(AgentBinding(agent=agent._definition()) for agent in self.agents)
        members: list[str] = []
        for member in party or ():
            index = next((i for i, agent in enumerate(self.agents) if agent is member), None)
            if index is None:
                raise ValueError("Cannot create Job.\nEvery Agent in party must also be in agents.")
            members.append(bindings[index].name)
        self.spec = JobSpec(
            source=job_source,
            agents=bindings,
            party=tuple(members),
            opponents=tuple(binding.name for binding in bindings[len(agents) :]),
            mode=mode,
            attempts=attempts,
            priority=priority,
            retry=retry or RetryPolicy(),
            purpose=purpose,
            portable=True,
        )
        self.catalog = catalog or ModelCatalog()
        self.plan = self.spec.plan(self.catalog)
        self.concurrency_reason: str | None = None
        if concurrency == "auto":
            from plural.execution.capacity import recommend_concurrency

            advice = recommend_concurrency(
                self.spec, trial_count=self.plan.trial_count, environ=environ
            )
            concurrency = advice.trials
            self.concurrency_reason = advice.reason
        elif not isinstance(concurrency, int) or concurrency < 1:
            raise ValueError("Cannot create Job.\nconcurrency must be 'auto' or at least 1.")
        if per_runtime_concurrency is not None and per_runtime_concurrency < 1:
            raise ValueError("Cannot create Job.\nper_runtime_concurrency must be at least 1.")
        self.spec = self.spec.model_copy(
            update={
                "concurrency": concurrency,
                "per_runtime_concurrency": per_runtime_concurrency or concurrency,
            }
        )
        self.plan = self.spec.plan(self.catalog)
        self._runner_options = {
            "provider": provider,
            "providers": providers,
            "store": store,
            "environ": environ,
            "resource_resolvers": resource_resolvers,
            "credentials": {
                agent: {name: CredentialValue(value) for name, value in values.items()}
                for agent, values in (credentials or {}).items()
            }
            or None,
            "progress": progress,
            "project_policy": project_policy,
            "catalog": self.catalog,
            "episode_server": episode_server,
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
        judged = any(
            getattr(binding.verifier, "kind", None) == "agent"
            for task in getattr(self.spec, "tasks", ())
            for binding in task.verifiers
        )
        if agents and not judged and all(binding.auth == "none" for binding in agents):
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
            current.setdefault("PLURAL_API_KEY", self.api_key)
        if current.get("PLURAL_API_KEY"):
            current.setdefault("PLURAL_GATEWAY_URL", resolve_gateway_url(None, current))
            return current
        if (
            agents
            and not judged
            and all(
                binding.auth == "none"
                or binding.agent.endpoint is not None
                or binding.external is not None
                for binding in agents
            )
        ):
            # Agents with their own endpoint call it directly, not the gateway.
            return current
        stored = _stored_api_key()
        if stored:
            current.setdefault("PLURAL_API_KEY", stored)
            current.setdefault("PLURAL_GATEWAY_URL", resolve_gateway_url(None, current))
            return current
        raise ValueError(
            "Cannot run Job.\n"
            "A live model call, by an Agent or a model-judge Verifier, goes through the "
            "Plural gateway and needs a Plural API key.\n"
            "Sign in:  plural auth login\n"
            "Or pass:  Job(task, agents=[agent], api_key='...')"
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
        options["model_identities"] = await asyncio.to_thread(
            self._local_models, options["environ"]
        )
        return await JobRunner(self.spec, **options).run(resume=resume)

    def _local_models(self, environ: Mapping[str, str]) -> dict[str, LocalModelIdentity]:
        """Each endpoint Agent's model, refused unless accepted before or allowed.

        Returns:
            The identities by Agent name.

        Raises:
            LocalModelError: When a model is unreachable, or nobody accepted it
                and ``allow_local_models`` is off.
        """
        from plural.local_models import review_local_models, unverified_message

        def decide(
            name: str,
            identity: LocalModelIdentity,
            status: Status,
            record: dict[str, Any] | None,
        ) -> Literal["known", "allowed"]:
            if status == "known":
                return "known"
            if self.allow_local_models:
                return "allowed"
            raise LocalModelError(unverified_message(name, identity, status, record))

        return review_local_models(self.spec.agents, environ, decide)

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
    "BenchmarkJobSource",
    "BenchmarkPin",
    "ExecutionStatus",
    "ForkChange",
    "ForkRecord",
    "ResumeRecord",
    "ForkRole",
    "ForkSpec",
    "IntegrityFinding",
    "Job",
    "JobLock",
    "JobMode",
    "JobPlan",
    "JobPurpose",
    "JobResult",
    "JobSource",
    "JobSpec",
    "ModelResolution",
    "PhaseName",
    "PhaseTiming",
    "ProgressEvent",
    "REFUSE_HELDOUT",
    "RetryPolicy",
    "SeatAggregate",
    "SeatAssignment",
    "SeatResult",
    "TITORecord",
    "TaskJobSource",
    "TrialExecution",
    "TrialFork",
    "TrialReceipt",
    "TrialResult",
    "TrialSpec",
    "TrialStatus",
    "VerifierResult",
    "resolve_trial_harness_grant",
]
