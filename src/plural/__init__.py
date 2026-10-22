"""Plural: build Environments, write Tasks, and benchmark and train Agents on them.

The names here are the ones a project needs. Everything else lives in its
submodule, such as :mod:`plural.harness` for the Harness protocol and
:mod:`plural.sandbox` for Runtime providers.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from plural.agents import Agent
from plural.apps import App
from plural.benchmarks import (
    BenchmarkCategory,
    BenchmarkScoring,
    EvaluationTrack,
)
from plural.catalog import CatalogContext, ModelCatalog
from plural.client import Client
from plural.environments import (
    Environment,
    ExecutionLimits,
    HarnessPolicy,
    Party,
    Resource,
    Runtime,
    RuntimeVariable,
    Secret,
    State,
    action,
    initial,
)
from plural.errors import PluralError
from plural.harness import (
    Harness,
    HarnessAgent,
    HarnessEnvironment,
    HarnessResult,
    HarnessTask,
)
from plural.jobs import (
    Job,
    JobResult,
    RetryPolicy,
    TrialResult,
)
from plural.rewards import Credit, HindsightTrial, RewardTarget
from plural.tasks import Benchmark, Task
from plural.types import (
    ChatRequest,
    ChatResponse,
    Message,
    Tool,
)
from plural.verifiers import (
    STOP_REASONS,
    AgentVerifier,
    DeterministicVerifier,
    Episode,
    HumanVerifier,
    RubricCriterion,
    Step,
    Verifier,
    VerifierOutput,
    total_reward,
)

_DEPRECATED: dict[str, tuple[str, str]] = {
    "Capability": ("SandboxCapability", "plural.sandbox.models"),
    "Outcome": ("TraceOutcome", "plural.tracing.schema"),
    "Plural": ("Client", "plural.client"),
    "TimeoutError": ("PluralTimeoutError", "plural.errors"),
    "Trial": ("TrialRunner", "plural.execution.engine"),
}

# Names that left the top level; each still imports from here, with a warning,
# for one release.
_MOVED: dict[str, str] = {
    "ActionCall": "plural.environments",
    "AgentAggregate": "plural.jobs",
    "AppDefinition": "plural.apps",
    "ArtifactManifest": "plural.jobs",
    "ArtifactManifestEntry": "plural.jobs",
    "ArtifactReference": "plural.jobs",
    "AuthenticationError": "plural.errors",
    "BenchmarkDiff": "plural.tasks",
    "BudgetExceededError": "plural.errors",
    "ConfigurationError": "plural.errors",
    "ConflictError": "plural.errors",
    "ContentFilterError": "plural.errors",
    "ContextLengthError": "plural.errors",
    "DaytonaProvider": "plural.sandbox",
    "DeclarativeImage": "plural.sandbox",
    "DockerProvider": "plural.sandbox",
    "EpisodeOutcome": "plural.verifiers",
    "EpisodeUsage": "plural.verifiers",
    "ErrorCode": "plural.common",
    "ExecutionStatus": "plural.jobs",
    "ExecutionTarget": "plural.common",
    "HarnessCapability": "plural.common",
    "HarnessCompletion": "plural.harness",
    "HarnessDefinition": "plural.harness",
    "HarnessStep": "plural.harness",
    "InvalidRequestError": "plural.errors",
    "JSONLSink": "plural.tracing",
    "JobMode": "plural.jobs",
    "JobPlan": "plural.jobs",
    "JobStore": "plural.execution",
    "LocalProvider": "plural.sandbox",
    "ModelSpec": "plural.catalog",
    "NetworkMode": "plural.sandbox",
    "NotFoundError": "plural.errors",
    "Observation": "plural.environments",
    "PluralTimeoutError": "plural.errors",
    "ProgressEvent": "plural.jobs",
    "Project": "plural.project",
    "ProjectError": "plural.project",
    "ProviderRegistry": "plural.sandbox",
    "ProviderUnavailable": "plural.errors",
    "RateLimitError": "plural.errors",
    "Redactor": "plural.tracing",
    "ResourceRef": "plural.project",
    "RewardRecord": "plural.rewards",
    "RuntimePackages": "plural.environments",
    "SQLiteSink": "plural.tracing",
    "Sampler": "plural.tracing",
    "SandboxCapability": "plural.sandbox",
    "SandboxProvider": "plural.sandbox",
    "SandboxRequirements": "plural.sandbox",
    "SeatTurn": "plural.harness",
    "SessionSnapshot": "plural.sessions",
    "Studio": "plural.studio",
    "TITORecord": "plural.jobs",
    "TaskPin": "plural.tasks",
    "Trace": "plural.tracing",
    "TraceContext": "plural.tracing",
    "TraceDataset": "plural.environments",
    "TraceFilter": "plural.environments",
    "TraceKind": "plural.tracing",
    "TraceOutcome": "plural.tracing",
    "TraceWriter": "plural.tracing",
    "Trajectory": "plural.trajectory",
    "TrajectoryEvent": "plural.trajectory",
    "TrialExecution": "plural.jobs",
    "TrialReceipt": "plural.jobs",
    "TrialSpec": "plural.jobs",
    "TrialStatus": "plural.jobs",
    "Usage": "plural.types",
    "VerifierResult": "plural.jobs",
    "VerifierRuntime": "plural.verifiers",
    "Workspace": "plural.project",
    "content_hash": "plural.common",
    "estimate_cost": "plural.catalog",
    "is_retryable": "plural.errors",
    "normalize_trajectory": "plural.trajectory",
    "stable_id": "plural.common",
}


def __getattr__(name: str) -> Any:
    import importlib

    from plural._deprecation import warn_renamed

    module = _MOVED.get(name)
    if module is not None:
        warn_renamed(f"plural.{name}", f"{module}.{name}")
        return getattr(importlib.import_module(module), name)
    renamed = _DEPRECATED.get(name)
    if renamed is None:
        raise AttributeError(f"module 'plural' has no attribute {name!r}")
    new, module = renamed
    warn_renamed(f"plural.{name}", f"plural.{new}" if new in __all__ else f"{module}.{new}")
    return getattr(importlib.import_module(module), new)


try:
    __version__ = version("plural")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "STOP_REASONS",
    "Agent",
    "AgentVerifier",
    "App",
    "Benchmark",
    "BenchmarkCategory",
    "BenchmarkScoring",
    "CatalogContext",
    "ChatRequest",
    "ChatResponse",
    "Client",
    "Credit",
    "DeterministicVerifier",
    "Environment",
    "Episode",
    "EvaluationTrack",
    "ExecutionLimits",
    "Harness",
    "HarnessAgent",
    "HarnessEnvironment",
    "HarnessPolicy",
    "HarnessResult",
    "HarnessTask",
    "HindsightTrial",
    "HumanVerifier",
    "Job",
    "JobResult",
    "Message",
    "ModelCatalog",
    "Party",
    "PluralError",
    "Resource",
    "RewardTarget",
    "RetryPolicy",
    "RubricCriterion",
    "Runtime",
    "RuntimeVariable",
    "Secret",
    "State",
    "Step",
    "Task",
    "Tool",
    "TrialResult",
    "Verifier",
    "VerifierOutput",
    "action",
    "initial",
    "total_reward",
    "__version__",
]
