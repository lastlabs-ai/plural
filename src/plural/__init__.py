"""Plural environments, evaluation, routing, and tracing.

Import order follows the authoring story: worlds, cases, scores, agents,
then runs, then hosting and advanced machinery.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from plural.agents import Agent
from plural.apps import App, AppDefinition
from plural.benchmarks import BenchmarkCategory, BenchmarkScoring, EvaluationTrack

# Hosting and models.
from plural.catalog import CatalogContext, ModelCatalog, ModelSpec, estimate_cost
from plural.client import Client

# Advanced: harness protocol, sandbox providers, tracing, errors, utilities.
from plural.common import (
    ErrorCode,
    ExecutionTarget,
    HarnessCapability,
    content_hash,
    stable_id,
)

# Authoring: worlds (Environment owns Runtime, Resources, Verifiers).
from plural.environments import (  # noqa: I001 - Environments load before Apps
    ActionCall,
    Environment,
    ExecutionLimits,
    HarnessPolicy,
    Observation,
    Party,
    Resource,
    Runtime,
    RuntimePackages,
    RuntimeVariable,
    Secret,
    State,
    TraceDataset,
    TraceFilter,
    action,
    initial,
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
    PluralTimeoutError,
    ProviderUnavailable,
    RateLimitError,
    is_retryable,
)

# Running: jobs, trials, and their results.
from plural.execution import JobStore
from plural.harness import (
    Harness,
    HarnessAgent,
    HarnessCompletion,
    HarnessDefinition,
    HarnessEnvironment,
    HarnessResult,
    HarnessStep,
    HarnessTask,
    SeatTurn,
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
from plural.rewards import (
    Credit,
    HindsightTrial,
    RewardRecord,
    RewardTarget,
)
from plural.sandbox import (
    DaytonaProvider,
    DeclarativeImage,
    DockerProvider,
    LocalProvider,
    NetworkMode,
    ProviderRegistry,
    SandboxCapability,
    SandboxProvider,
    SandboxRequirements,
)
from plural.sessions import SessionSnapshot
from plural.studio import Studio
from plural.tasks import Benchmark, BenchmarkDiff, Task, TaskPin
from plural.tracing import (
    JSONLSink,
    Redactor,
    Sampler,
    SQLiteSink,
    Trace,
    TraceContext,
    TraceKind,
    TraceOutcome,
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
    Step,
    Verifier,
    VerifierOutput,
    VerifierRuntime,
    total_reward,
)

_DEPRECATED: dict[str, tuple[str, str]] = {
    "Capability": ("SandboxCapability", "plural.sandbox.models"),
    "Outcome": ("TraceOutcome", "plural.tracing.schema"),
    "Plural": ("Client", "plural.client"),
    "TimeoutError": ("PluralTimeoutError", "plural.errors"),
    "Trial": ("TrialRunner", "plural.execution.engine"),
}


def __getattr__(name: str) -> Any:
    renamed = _DEPRECATED.get(name)
    if renamed is None:
        raise AttributeError(f"module 'plural' has no attribute {name!r}")
    import importlib

    from plural._deprecation import warn_renamed

    new, module = renamed
    warn_renamed(f"plural.{name}", f"{module}.{new}" if name == "Trial" else f"plural.{new}")
    return getattr(importlib.import_module(module), new)


try:
    __version__ = version("plural")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    # Authoring.
    "ActionCall",
    "Agent",
    "App",
    "AppDefinition",
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
    "Party",
    "Harness",
    "HarnessPolicy",
    "HumanVerifier",
    "Observation",
    "Resource",
    "RubricCriterion",
    "Step",
    "Runtime",
    "RuntimePackages",
    "RuntimeVariable",
    "Secret",
    "State",
    "Task",
    "Verifier",
    "VerifierOutput",
    "action",
    "total_reward",
    "initial",
    "Credit",
    "HindsightTrial",
    "RewardRecord",
    "RewardTarget",
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
    "TrialResult",
    # Hosting and models.
    "Client",
    "ModelCatalog",
    "ModelSpec",
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
    "SandboxCapability",
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
    "TraceOutcome",
    "STOP_REASONS",
    "PluralError",
    "PluralTimeoutError",
    "ProgressEvent",
    "ProviderRegistry",
    "ProviderUnavailable",
    "RateLimitError",
    "Redactor",
    "SQLiteSink",
    "Sampler",
    "SandboxProvider",
    "SandboxRequirements",
    "SeatTurn",
    "TITORecord",
    "TaskPin",
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
