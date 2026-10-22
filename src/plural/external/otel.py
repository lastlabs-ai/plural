"""Trace any OpenTelemetry-instrumented agent to Plural.

Most agent frameworks emit OpenTelemetry spans: CrewAI, Pydantic AI, Google ADK,
AutoGen, smolagents, LlamaIndex, Strands, and anything instrumented with
OpenLLMetry or OpenInference. This span processor reads the GenAI semantic
conventions, OpenLLMetry's ``gen_ai.prompt.*`` attributes, and OpenInference's
``llm.*`` attributes, and records each model and tool call into the current
Plural run, or into a run per trace when there is none::

    from plural.external.otel import instrument

    instrument()  # adds the processor to the global TracerProvider

Install the SDK with ``pip install "plural[external]"``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from plural.external._adapters import Roots, from_nanoseconds, loads, text_of, usage
from plural.external.tracing import Run, ToolCall, Tracer

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.context import Context
    from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
    from opentelemetry.trace import StatusCode
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        'The OpenTelemetry adapter needs the SDK: pip install "plural[external]"'
    ) from exc

_LLM_OPERATIONS = {"chat", "text_completion", "generate_content", "completion"}
_INDEX = re.compile(r"^(\d+)\.(.+)$")


class PluralSpanProcessor(SpanProcessor):
    """Records model and tool spans into Plural runs.

    Args:
        tracer: The Plural tracer; defaults to the process's
            (:func:`plural.external.tracer`).
    """

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._roots = Roots(tracer)
        self._root_spans: dict[int, int] = {}

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Open a Plural run for a new trace."""
        context = span.get_span_context()
        if context is None:
            return
        trace_id = context.trace_id
        if self._roots.get(trace_id) is None:
            self._roots.open(trace_id)
            self._root_spans[trace_id] = context.span_id

    def on_end(self, span: ReadableSpan) -> None:
        """Record a model or tool span, and finish the run with its trace's root span."""
        context = span.get_span_context()
        if context is None:
            return
        run = self._roots.get(context.trace_id)
        if run is None:
            return
        attributes = dict(span.attributes or {})
        kind = _kind(attributes)
        if kind == "llm":
            _record_llm(run, span, attributes)
        elif kind == "tool":
            _record_tool(run, span, attributes)
        if self._root_spans.get(context.trace_id) == context.span_id:
            del self._root_spans[context.trace_id]
            failed = span.status.status_code is StatusCode.ERROR
            self._roots.close(
                context.trace_id,
                answer=None if failed else _answer(attributes),
                error=(span.status.description or span.name) if failed else None,
            )

    def shutdown(self) -> None:
        """Write pending traces."""
        self._roots.tracer().flush()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        """Write pending traces.

        Returns:
            Whether they were written within ``timeout_millis``.
        """
        return self._roots.tracer().flush(timeout_millis / 1000)


def instrument(
    tracer: Tracer | None = None, *, provider: TracerProvider | None = None
) -> PluralSpanProcessor:
    """Add a :class:`PluralSpanProcessor` to ``provider``, or to the global one.

    When the global provider is not the OpenTelemetry SDK's yet, a new one is
    installed as global, so frameworks that emit spans to it are traced.

    Returns:
        The processor.
    """
    processor = PluralSpanProcessor(tracer)
    if provider is None:
        current = otel_trace.get_tracer_provider()
        if isinstance(current, TracerProvider):
            provider = current
        else:
            provider = TracerProvider()
            otel_trace.set_tracer_provider(provider)
    provider.add_span_processor(processor)
    return processor


def _kind(attributes: Mapping[str, Any]) -> str | None:
    operation = str(attributes.get("gen_ai.operation.name") or "")
    inference = str(attributes.get("openinference.span.kind") or "").upper()
    traceloop = str(attributes.get("traceloop.span.kind") or "")
    if operation == "execute_tool" or inference == "TOOL" or traceloop == "tool":
        return "tool"
    if (
        operation in _LLM_OPERATIONS
        or inference == "LLM"
        or attributes.get("llm.request.type") in {"chat", "completion"}
    ):
        return "llm"
    return None


def _record_llm(run: Run, span: ReadableSpan, attributes: Mapping[str, Any]) -> None:
    messages = (
        _semconv_messages(attributes.get("gen_ai.input.messages"))
        or _indexed_messages(attributes, "gen_ai.prompt", nested=False)
        or _indexed_messages(attributes, "llm.input_messages", nested=True)
        or _event_messages(span)
    )
    system = _semconv_parts(loads(attributes.get("gen_ai.system_instructions")))
    if system:
        messages = [{"role": "system", "content": system}, *messages]
    outputs = (
        _semconv_messages(attributes.get("gen_ai.output.messages"))
        or _indexed_messages(attributes, "gen_ai.completion", nested=False)
        or _indexed_messages(attributes, "llm.output_messages", nested=True)
        or _event_messages(span, choices=True)
    )
    reply = next((item for item in reversed(outputs) if item.get("role") == "assistant"), {})
    started, ended = span.start_time, span.end_time
    run.llm(
        model=str(
            attributes.get("gen_ai.response.model")
            or attributes.get("gen_ai.request.model")
            or attributes.get("llm.model_name")
            or ""
        )
        or None,
        messages=messages,
        output=text_of(reply.get("content")),
        tool_calls=[
            ToolCall(
                id=str(call.get("id") or f"call-{index}"),
                name=str(call["function"]["name"]),
                arguments=_arguments(call["function"].get("arguments")),
            )
            for index, call in enumerate(reply.get("tool_calls") or [])
        ],
        usage=usage(
            attributes.get("gen_ai.usage.input_tokens")
            or attributes.get("gen_ai.usage.prompt_tokens")
            or attributes.get("llm.token_count.prompt"),
            attributes.get("gen_ai.usage.output_tokens")
            or attributes.get("gen_ai.usage.completion_tokens")
            or attributes.get("llm.token_count.completion"),
            attributes.get("gen_ai.usage.cache_read.input_tokens")
            or attributes.get("llm.token_count.prompt_details.cache_read"),
        ),
        latency_ms=(ended - started) / 1e6 if started and ended else None,
        error=span.status.description or "error"
        if span.status.status_code is StatusCode.ERROR
        else None,
        started_at=from_nanoseconds(started),
    )


def _record_tool(run: Run, span: ReadableSpan, attributes: Mapping[str, Any]) -> None:
    started, ended = span.start_time, span.end_time
    arguments = loads(
        attributes.get("gen_ai.tool.call.arguments")
        or attributes.get("tool.parameters")
        or attributes.get("traceloop.entity.input")
        or attributes.get("input.value")
    )
    result = loads(
        attributes.get("gen_ai.tool.call.result")
        or attributes.get("traceloop.entity.output")
        or attributes.get("output.value")
    )
    failed = span.status.status_code is StatusCode.ERROR
    run.tool(
        str(
            attributes.get("gen_ai.tool.name")
            or attributes.get("tool.name")
            or attributes.get("traceloop.entity.name")
            or span.name
        ),
        _arguments(arguments),
        result,
        call_id=str(attributes["gen_ai.tool.call.id"])
        if attributes.get("gen_ai.tool.call.id")
        else None,
        error=(span.status.description or "error") if failed else None,
        latency_ms=(ended - started) / 1e6 if started and ended else None,
        started_at=from_nanoseconds(started),
    )


def _answer(attributes: Mapping[str, Any]) -> str | None:
    outputs = _semconv_messages(attributes.get("gen_ai.output.messages"))
    if outputs:
        return text_of(outputs[-1].get("content")) or None
    value = attributes.get("output.value") or attributes.get("traceloop.entity.output")
    if not value:
        return None
    return text_of(loads(value)) or None


def _arguments(value: Any) -> dict[str, Any]:
    parsed = loads(value)
    if isinstance(parsed, Mapping):
        return dict(parsed)
    return {} if parsed in (None, "") else {"input": parsed}


def _semconv_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    return "\n".join(
        str(part.get("content"))
        for part in parts
        if isinstance(part, Mapping) and part.get("type") == "text" and part.get("content")
    )


def _semconv_messages(raw: Any) -> list[dict[str, Any]]:
    """Messages in the GenAI conventions' ``parts`` shape, as OpenAI chat messages.

    Returns:
        The messages; empty when ``raw`` holds none.
    """
    value = loads(raw)
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for message in value:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "")
        parts = message.get("parts")
        if not isinstance(parts, list):
            out.append({"role": role, "content": text_of(message.get("content"))})
            continue
        calls = [
            {
                "id": str(part.get("id") or ""),
                "type": "function",
                "function": {
                    "name": str(part.get("name") or ""),
                    "arguments": part.get("arguments"),
                },
            }
            for part in parts
            if isinstance(part, Mapping) and part.get("type") == "tool_call"
        ]
        responses = [
            part
            for part in parts
            if isinstance(part, Mapping) and part.get("type") == "tool_call_response"
        ]
        for response in responses:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": str(response.get("id") or ""),
                    "content": text_of(response.get("response")),
                }
            )
        if responses and not calls:
            continue
        entry: dict[str, Any] = {"role": role, "content": _semconv_parts(parts)}
        if calls:
            entry["tool_calls"] = calls
        out.append(entry)
    return out


def _indexed_messages(
    attributes: Mapping[str, Any], prefix: str, *, nested: bool
) -> list[dict[str, Any]]:
    """Messages flattened as ``prefix.N.role`` (OpenLLMetry) or ``prefix.N.message.role``.

    Returns:
        The messages in index order; empty when there are none.
    """
    grouped = _group(attributes, prefix)
    out: list[dict[str, Any]] = []
    for _, fields in sorted(grouped.items()):
        base = "message." if nested else ""
        message: dict[str, Any] = {
            "role": str(fields.get(f"{base}role") or ""),
            "content": fields.get(f"{base}content") or "",
        }
        if fields.get(f"{base}tool_call_id"):
            message["tool_call_id"] = str(fields[f"{base}tool_call_id"])
        calls = _group(fields, f"{base}tool_calls")
        if calls:
            path = "tool_call." if nested else ""
            message["tool_calls"] = [
                {
                    "id": str(call.get(f"{path}id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(
                            call.get(f"{path}function.name") or call.get(f"{path}name") or ""
                        ),
                        "arguments": call.get(f"{path}function.arguments")
                        or call.get(f"{path}arguments"),
                    },
                }
                for _, call in sorted(calls.items())
            ]
        out.append(message)
    return out


def _group(attributes: Mapping[str, Any], prefix: str) -> dict[int, dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for key, value in attributes.items():
        if not key.startswith(f"{prefix}."):
            continue
        match = _INDEX.match(key[len(prefix) + 1 :])
        if match:
            grouped.setdefault(int(match.group(1)), {})[match.group(2)] = value
    return grouped


def _event_messages(span: ReadableSpan, *, choices: bool = False) -> list[dict[str, Any]]:
    """Messages from the older GenAI events, such as ``gen_ai.user.message``.

    Returns:
        The messages; empty when the span has no such events.
    """
    roles = {
        "gen_ai.system.message": "system",
        "gen_ai.user.message": "user",
        "gen_ai.assistant.message": "assistant",
        "gen_ai.tool.message": "tool",
    }
    out: list[dict[str, Any]] = []
    for event in span.events or ():
        attributes = dict(event.attributes or {})
        if choices:
            if event.name != "gen_ai.choice":
                continue
            message = loads(attributes.get("message")) or {}
            content = (
                message.get("content")
                if isinstance(message, Mapping)
                else attributes.get("content")
            )
            out.append({"role": "assistant", "content": text_of(content)})
        elif event.name in roles:
            entry: dict[str, Any] = {
                "role": roles[event.name],
                "content": text_of(loads(attributes.get("content"))),
            }
            if attributes.get("id"):
                entry["tool_call_id"] = str(attributes["id"])
            out.append(entry)
    return out


__all__ = ["PluralSpanProcessor", "instrument"]
