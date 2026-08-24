"""enroute: unified LLM routing with first-class traces, environments, and benchmarks.

Examples:
    >>> from enroute import __version__
    >>> isinstance(__version__, str)
    True
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from enroute.benchmarks import (
    Benchmark,
    CaseKey,
    CaseResult,
    ModelStats,
    Report,
    RunManifest,
    TaskDatasetMetadata,
    TaskSetMetadata,
    WinRatePair,
)
from enroute.catalog import ModelCatalog, ModelSpec, estimate_cost
from enroute.client import Enroute
from enroute.environments import (
    ActionResult,
    Dataset,
    EnroutePolicy,
    Environment,
    Policy,
    ScriptedPolicy,
    StopReason,
    TaskData,
    TaskDataset,
    TraceDataset,
    TraceFilter,
)
from enroute.errors import (
    AuthenticationError,
    BudgetExceededError,
    ConfigurationError,
    ContentFilterError,
    ContextLengthError,
    EnrouteError,
    InvalidRequestError,
    NotFoundError,
    ProviderUnavailable,
    RateLimitError,
    TimeoutError,
    is_retryable,
)
from enroute.tracing import (
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
from enroute.types import ChatRequest, ChatResponse, Message, Tool, Usage

try:
    __version__ = version("enroute")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "ActionResult",
    "AuthenticationError",
    "Benchmark",
    "BudgetExceededError",
    "CaseKey",
    "CaseResult",
    "ChatRequest",
    "ChatResponse",
    "ConfigurationError",
    "ContentFilterError",
    "ContextLengthError",
    "Dataset",
    "Enroute",
    "EnroutePolicy",
    "EnrouteError",
    "Environment",
    "InvalidRequestError",
    "JSONLSink",
    "Message",
    "ModelStats",
    "ModelCatalog",
    "ModelSpec",
    "NotFoundError",
    "Outcome",
    "Policy",
    "ProviderUnavailable",
    "RateLimitError",
    "Redactor",
    "Report",
    "RunManifest",
    "SQLiteSink",
    "Sampler",
    "ScriptedPolicy",
    "StopReason",
    "TaskData",
    "TaskDataset",
    "TaskDatasetMetadata",
    "TaskSetMetadata",
    "TimeoutError",
    "Tool",
    "Trace",
    "TraceContext",
    "TraceDataset",
    "TraceFilter",
    "TraceKind",
    "TraceWriter",
    "Usage",
    "WinRatePair",
    "__version__",
    "estimate_cost",
    "is_retryable",
]
