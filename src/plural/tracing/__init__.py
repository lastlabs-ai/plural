"""Unified tracing: the same Trace object for production traffic and environments.

Examples:
    >>> from plural.tracing import Trace, JSONLSink
    >>> Trace(trace_id="t1").trace_id
    't1'
"""

from __future__ import annotations

from plural.tracing.redaction import Redactor, Sampler
from plural.tracing.resources import trace_json_schema
from plural.tracing.schema import (
    Decision,
    Event,
    LLMCall,
    Outcome,
    ParsedAction,
    RewardEvent,
    Step,
    ToolCallStep,
    Trace,
    TraceContext,
    TraceKind,
    Transition,
)
from plural.tracing.sinks import JSONLSink, MultiSink, OTelSink, Sink, SQLiteSink
from plural.tracing.writer import TraceWriter

__all__ = [
    "Decision",
    "Event",
    "JSONLSink",
    "LLMCall",
    "MultiSink",
    "OTelSink",
    "Outcome",
    "ParsedAction",
    "Redactor",
    "RewardEvent",
    "SQLiteSink",
    "Sampler",
    "Sink",
    "Step",
    "ToolCallStep",
    "Trace",
    "TraceContext",
    "TraceKind",
    "TraceWriter",
    "Transition",
    "trace_json_schema",
]
