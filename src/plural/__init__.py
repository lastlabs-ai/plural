"""Plural: unified LLM routing with first-class traces, environments, and benchmarks.

Examples:
    >>> from plural import __version__
    >>> isinstance(__version__, str)
    True
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from plural.benchmarks import (
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
from plural.catalog import ModelCatalog, ModelSpec, estimate_cost
from plural.client import Client, Plural
from plural.environments import (
    ActionResult,
    Dataset,
    Environment,
    PluralPolicy,
    Policy,
    ScriptedPolicy,
    StopReason,
    TaskData,
    TaskDataset,
    TraceDataset,
    TraceFilter,
)
from plural.errors import (
    AuthenticationError,
    BudgetExceededError,
    ConfigurationError,
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
from plural.studio import RemoteAgent as Agent
from plural.studio import Studio
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
from plural.types import ChatRequest, ChatResponse, Message, Tool, Usage

try:
    __version__ = version("plural")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "ActionResult",
    "Agent",
    "AuthenticationError",
    "Benchmark",
    "BudgetExceededError",
    "CaseKey",
    "CaseResult",
    "ChatRequest",
    "ChatResponse",
    "Client",
    "ConfigurationError",
    "ContentFilterError",
    "ContextLengthError",
    "Dataset",
    "Environment",
    "InvalidRequestError",
    "JSONLSink",
    "Message",
    "ModelCatalog",
    "ModelSpec",
    "ModelStats",
    "NotFoundError",
    "Outcome",
    "Plural",
    "PluralError",
    "PluralPolicy",
    "Policy",
    "ProviderUnavailable",
    "RateLimitError",
    "Redactor",
    "Report",
    "RunManifest",
    "SQLiteSink",
    "Sampler",
    "Studio",
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
