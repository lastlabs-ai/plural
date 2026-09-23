"""Plural environments, evaluation, routing, and tracing.

Import order follows the authoring story: worlds, cases, scores, agents,
then runs, then hosting and advanced machinery.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

# Authoring: worlds (Environment owns Runtime, Resources, Rewarders).
from plural.agents import Agent
from plural.benchmarks import BenchmarkCategory, BenchmarkScoring, EvaluationTrack

# Hosting and models.
from plural.catalog import CatalogContext, ModelCatalog, ModelSpec, estimate_cost
from plural.client import Client, Plural

# Advanced: harness protocol, sandbox providers, tracing, errors, utilities.
from plural.common import (
    ErrorCode,
    ExecutionTarget,
    HarnessCapability,
    content_hash,
    stable_id,
)
from plural.environments import (
    Action,
    Environment,
    ExecutionLimits,
    HarnessPolicy,
    Observation,
    Resource,
    Runtime,
    RuntimeVariable,
    Secret,
    State,
    TraceDataset,
    TraceFilter,
    action,
    initial,
    rewarder,
)
from plural.errors import (
    AuthenticationError,
    BudgetExceededError,
    ConfigurationError,
    ConflictError,
    ContentFilterError,
    ContextLengthError,
    InvalidRequestError,
    NotFoundError,
    PluralError,
    ProviderUnavailable,
    RateLimitError,
    TimeoutError,
    is_retryable,
)

# Running: jobs, trials, and their results.
from plural.execution import JobStore, Trial
from plural.harness import (
    Harness,
    HarnessAgent,
    HarnessCompletion,
    HarnessDefinition,
    HarnessEnvironment,
    HarnessResult,
    HarnessStep,
    HarnessTask,
)
from plural.jobs import (
    AgentAggregate,
    ArtifactManifest,
    ArtifactManifestEntry,
    ArtifactReference,
    ExecutionStatus,
    Job,
    JobMode,
    JobPlan,
    JobResult,
    ProgressEvent,
    RetryPolicy,
    TITORecord,
    TrialExecution,
    TrialReceipt,
    TrialResult,
    TrialSpec,
    TrialStatus,
    VerifierResult,
)
from plural.project import Project, ProjectError, ResourceRef, Workspace
from plural.sandbox import (
    Capability,
    DaytonaProvider,
    DeclarativeImage,
    DockerProvider,
    LocalProvider,
    NetworkMode,
    ProviderRegistry,
    SandboxProvider,
    SandboxRequirements,
)
from plural.sessions import SessionSnapshot
from plural.studio import Studio
from plural.tasks import Benchmark, BenchmarkDiff, Task, TaskPin
from plural.tracing import (
    JSONLSink,
    Outcome,
    Redactor,
    Sampler,
    SQLiteSink,
    Trace,
    TraceContext,
    TraceKind,
    TraceWriter,
)
from plural.trajectory import Trajectory, TrajectoryEvent, normalize_trajectory
from plural.types import ChatRequest, ChatResponse, Message, Tool, Usage
from plural.verifiers import (
    STOP_REASONS,
    AgentVerifier,
    DeterministicVerifier,
    Episode,
    EpisodeOutcome,
    EpisodeUsage,
    HumanVerifier,
    RubricCriterion,
    Verifier,
    VerifierOutput,
    VerifierRuntime,
)

try:
    __version__ = version("plural")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    # Authoring.
    "Action",
    "Agent",
    "AgentVerifier",
    "Benchmark",
    "BenchmarkCategory",
    "BenchmarkScoring",
    "CatalogContext",
    "DeterministicVerifier",
    "Environment",
    "EvaluationTrack",
    "Episode",
    "ExecutionLimits",
    "Harness",
    "HarnessPolicy",
    "HumanVerifier",
    "Observation",
    "Resource",
    "RubricCriterion",
    "Runtime",
    "RuntimeVariable",
    "Secret",
    "State",
    "Task",
    "Verifier",
    "VerifierOutput",
    "action",
    "initial",
    "rewarder",
    # Projects.
    "Project",
    "ProjectError",
    "ResourceRef",
    "Workspace",
    # Running.
    "Job",
    "JobMode",
    "JobPlan",
    "JobResult",
    "JobStore",
    "RetryPolicy",
    "SessionSnapshot",
    "Trial",
    "TrialResult",
    # Hosting and models.
    "Client",
    "ModelCatalog",
    "ModelSpec",
    "Plural",
    "Studio",
    "estimate_cost",
    # Advanced.
    "AgentAggregate",
    "ArtifactManifest",
    "ArtifactManifestEntry",
    "ArtifactReference",
    "AuthenticationError",
    "BenchmarkDiff",
    "BudgetExceededError",
    "Capability",
    "ChatRequest",
    "ChatResponse",
    "ConfigurationError",
    "ConflictError",
    "ContentFilterError",
    "ContextLengthError",
    "DaytonaProvider",
    "DeclarativeImage",
    "DockerProvider",
    "EpisodeOutcome",
    "EpisodeUsage",
    "ErrorCode",
    "ExecutionStatus",
    "ExecutionTarget",
    "HarnessAgent",
    "HarnessCapability",
    "HarnessCompletion",
    "HarnessDefinition",
    "HarnessEnvironment",
    "HarnessResult",
    "HarnessStep",
    "HarnessTask",
    "InvalidRequestError",
    "JSONLSink",
    "LocalProvider",
    "Message",
    "NetworkMode",
    "NotFoundError",
    "Outcome",
    "STOP_REASONS",
    "PluralError",
    "ProgressEvent",
    "ProviderRegistry",
    "ProviderUnavailable",
    "RateLimitError",
    "Redactor",
    "SQLiteSink",
    "Sampler",
    "SandboxProvider",
    "SandboxRequirements",
    "TITORecord",
    "TaskPin",
    "TimeoutError",
    "Tool",
    "Trace",
    "TraceContext",
    "TraceDataset",
    "TraceFilter",
    "TraceKind",
    "TraceWriter",
    "Trajectory",
    "TrajectoryEvent",
    "TrialExecution",
    "TrialReceipt",
    "TrialSpec",
    "TrialStatus",
    "Usage",
    "VerifierResult",
    "VerifierRuntime",
    "__version__",
    "content_hash",
    "is_retryable",
    "normalize_trajectory",
    "stable_id",
]
