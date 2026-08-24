"""Unified tracing: the same Trace object for production traffic and environments.

Examples:
    >>> from enroute.tracing import Trace, JSONLSink
    >>> Trace(trace_id="t1").trace_id
    't1'
"""

from __future__ import annotations

from enroute.tracing.redaction import Redactor, Sampler
from enroute.tracing.resources import trace_json_schema
from enroute.tracing.schema import (
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
from enroute.tracing.sinks import JSONLSink, MultiSink, OTelSink, Sink, SQLiteSink
from enroute.tracing.writer import TraceWriter

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
