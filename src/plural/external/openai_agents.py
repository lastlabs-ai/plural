"""Trace an OpenAI Agents SDK agent to Plural.

Install the processor once, and every model call, tool call, and final answer
of each agent run is recorded into the current Plural run, or into a run of its
own when there is none::

    from plural.external.openai_agents import install

    install()  # adds Plural next to the SDK's own trace export

Use ``agents.set_trace_processors([PluralTracingProcessor()])`` instead to send
traces to Plural only.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from typing import Any

from plural.external._adapters import Roots, from_iso, loads, text_of, usage
from plural.external.tracing import Run, ToolCall, Tracer

try:
    import agents
    from agents.tracing import Span, Trace, TracingProcessor
    from agents.tracing.span_data import FunctionSpanData, GenerationSpanData, ResponseSpanData
except ImportError as exc:  # pragma: no cover - exercised only without the SDK
    raise ImportError("The OpenAI Agents adapter needs the SDK: pip install openai-agents") from exc


class PluralTracingProcessor(TracingProcessor):
    """Records OpenAI Agents SDK traces into Plural runs.

    Args:
        tracer: The Plural tracer; defaults to the process's
            (:func:`plural.external.tracer`).
    """

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._roots = Roots(tracer)
        self._lock = threading.Lock()
        self._answers: dict[str, str] = {}

    def on_trace_start(self, trace: Trace) -> None:
        """Open a Plural run for an agent run."""
        self._roots.open(trace.trace_id)

    def on_trace_end(self, trace: Trace) -> None:
        """Finish an agent run with its last answer."""
        with self._lock:
            answer = self._answers.pop(trace.trace_id, None)
        self._roots.close(trace.trace_id, answer=answer)

    def on_span_start(self, span: Span[Any]) -> None:
        """Nothing is recorded until a span ends."""
        return None

    def on_span_end(self, span: Span[Any]) -> None:
        """Record a model or tool span."""
        run = self._roots.get(span.trace_id)
        if run is None:
            return
        data = span.span_data
        error = _error(span)
        if isinstance(data, ResponseSpanData):
            self._response(run, span, data, error)
        elif isinstance(data, GenerationSpanData):
            self._generation(run, span, data, error)
        elif isinstance(data, FunctionSpanData):
            run.tool(
                data.name,
                _arguments(data.input),
                loads(data.output),
                error=error,
                latency_ms=_elapsed(span),
                started_at=from_iso(span.started_at),
            )

    def _response(
        self, run: Run, span: Span[Any], data: ResponseSpanData, error: str | None
    ) -> None:
        response = data.response
        output = list(getattr(response, "output", None) or [])
        text = "\n".join(
            part_text
            for item in output
            if getattr(item, "type", None) == "message"
            for part in getattr(item, "content", None) or []
            if (part_text := getattr(part, "text", None))
        )
        calls = [
            ToolCall(
                id=str(getattr(item, "call_id", "") or getattr(item, "id", "")),
                name=str(getattr(item, "name", "")),
                arguments=_arguments(getattr(item, "arguments", None)),
            )
            for item in output
            if getattr(item, "type", None) == "function_call"
        ]
        reasoning = "\n".join(
            str(getattr(summary, "text", ""))
            for item in output
            if getattr(item, "type", None) == "reasoning"
            for summary in getattr(item, "summary", None) or []
        )
        messages = _input_messages(data.input)
        instructions = getattr(response, "instructions", None)
        if isinstance(instructions, str) and instructions:
            messages = [{"role": "system", "content": instructions}, *messages]
        counts = getattr(response, "usage", None)
        details = getattr(counts, "input_tokens_details", None)
        run.llm(
            model=getattr(response, "model", None),
            messages=messages,
            output=text,
            tool_calls=calls,
            reasoning=reasoning or None,
            usage=usage(
                getattr(counts, "input_tokens", None),
                getattr(counts, "output_tokens", None),
                getattr(details, "cached_tokens", None),
            ),
            latency_ms=_elapsed(span),
            error=error,
            started_at=from_iso(span.started_at),
        )
        if text:
            with self._lock:
                self._answers[span.trace_id] = text

    def _generation(
        self, run: Run, span: Span[Any], data: GenerationSpanData, error: str | None
    ) -> None:
        outputs = [dict(item) for item in data.output or [] if isinstance(item, Mapping)]
        reply = next((item for item in reversed(outputs) if item.get("role") == "assistant"), {})
        text = text_of(reply.get("content"))
        counts = data.usage or {}
        run.llm(
            model=data.model,
            messages=[dict(item) for item in data.input or [] if isinstance(item, Mapping)],
            output=text,
            tool_calls=[
                ToolCall(
                    id=str(call.get("id") or ""),
                    name=str((call.get("function") or {}).get("name") or ""),
                    arguments=_arguments((call.get("function") or {}).get("arguments")),
                )
                for call in reply.get("tool_calls") or []
                if isinstance(call, Mapping)
            ],
            usage=usage(
                counts.get("input_tokens", counts.get("prompt_tokens")),
                counts.get("output_tokens", counts.get("completion_tokens")),
            ),
            latency_ms=_elapsed(span),
            error=error,
            started_at=from_iso(span.started_at),
        )
        if text:
            with self._lock:
                self._answers[span.trace_id] = text

    def shutdown(self) -> None:
        """Write pending traces."""
        self._roots.tracer().flush()

    def force_flush(self) -> None:
        """Write pending traces."""
        self._roots.tracer().flush()


def install(tracer: Tracer | None = None) -> PluralTracingProcessor:
    """Add a :class:`PluralTracingProcessor` to the SDK's trace processors.

    Returns:
        The processor.
    """
    processor = PluralTracingProcessor(tracer)
    agents.add_trace_processor(processor)
    return processor


def _input_messages(raw: Any) -> list[dict[str, Any]]:
    """Responses API input items, as OpenAI chat messages.

    Returns:
        The messages; one user message when the input is a string.
    """
    if isinstance(raw, str):
        return [{"role": "user", "content": raw}]
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, Sequence) else ():
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if kind == "function_call":
            out.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": str(item.get("call_id") or ""),
                            "type": "function",
                            "function": {
                                "name": str(item.get("name") or ""),
                                "arguments": item.get("arguments") or "{}",
                            },
                        }
                    ],
                }
            )
        elif kind == "function_call_output":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": str(item.get("call_id") or ""),
                    "content": text_of(item.get("output")),
                }
            )
        elif item.get("role"):
            out.append({"role": str(item["role"]), "content": text_of(item.get("content"))})
    return out


def _arguments(value: Any) -> dict[str, Any]:
    parsed = loads(value)
    if isinstance(parsed, Mapping):
        return dict(parsed)
    return {} if parsed in (None, "") else {"input": parsed}


def _error(span: Span[Any]) -> str | None:
    error = span.error
    if not error:
        return None
    message = error.get("message") if isinstance(error, Mapping) else None
    return str(message or error)


def _elapsed(span: Span[Any]) -> float | None:
    started, ended = from_iso(span.started_at), from_iso(span.ended_at)
    if started is None or ended is None:
        return None
    return (ended - started).total_seconds() * 1000


__all__ = ["PluralTracingProcessor", "install"]
