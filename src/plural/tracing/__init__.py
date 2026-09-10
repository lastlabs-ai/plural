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
    ActionStep,
    CapabilityDenial,
    Event,
    LLMCall,
    Outcome,
    ParsedAction,
    ReasoningBlock,
    RewardEvent,
    Step,
    Trace,
    TraceContext,
    TraceKind,
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
    "Outcome",
    "ParsedAction",
    "ReasoningBlock",
    "Redactor",
    "RewardEvent",
    "SQLiteSink",
    "Sampler",
    "Sink",
    "Step",
    "Trace",
    "TraceContext",
    "TraceKind",
    "TraceWriter",
    "Transition",
    "Turn",
    "trace_json_schema",
]
