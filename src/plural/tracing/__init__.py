"""Unified tracing: the same Trace object for production traffic and environments.

Examples:
    >>> from plural.tracing import Trace, JSONLSink
    >>> Trace(trace_id="t1").trace_id
    't1'
"""

from __future__ import annotations

from typing import Any

from plural._deprecation import module_getattr
from plural.tracing.redaction import Redactor, Sampler
from plural.tracing.resources import trace_json_schema
from plural.tracing.schema import (
    ActionStep,
    CapabilityDenial,
    Event,
    LLMCall,
    ParsedAction,
    ReasoningBlock,
    RewardEvent,
    Step,
    Trace,
    TraceArtifactReference,
    TraceContext,
    TraceKind,
    TraceOutcome,
    TraceVerifierResult,
    Transition,
    Turn,
)
from plural.tracing.sinks import JSONLSink, MultiSink, OTelSink, Sink, SQLiteSink
from plural.tracing.writer import TraceWriter

__all__ = [
    "ActionStep",
    "CapabilityDenial",
    "Event",
    "JSONLSink",
    "LLMCall",
    "MultiSink",
    "OTelSink",
    "TraceOutcome",
    "ParsedAction",
    "ReasoningBlock",
    "Redactor",
    "RewardEvent",
    "SQLiteSink",
    "Sampler",
    "Sink",
    "Step",
    "Trace",
    "TraceArtifactReference",
    "TraceContext",
    "TraceKind",
    "TraceVerifierResult",
    "TraceWriter",
    "Transition",
    "Turn",
    "trace_json_schema",
]

_renamed = module_getattr("plural.tracing", {"Outcome": ("TraceOutcome", lambda: TraceOutcome)})


def __getattr__(name: str) -> Any:
    return _renamed(name)
