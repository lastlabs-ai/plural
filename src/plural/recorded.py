"""Read conversations an agent already had, to draft an Environment from them.

A recorded trace is an OpenAI-style message list: the conversation an agent
had, with its tool calls and their results, and optionally the tools it was
offered. ``plural env add --traces`` turns the tool calls into replay Apps and
each conversation into a draft Task.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from plural.common import FrozenModel


class RecordedTrace(FrozenModel):
    """One conversation an agent already had."""

    trace_id: str = Field(min_length=1)
    messages: tuple[dict[str, Any], ...] = Field(min_length=1)
    model: str = "recorded"
    metadata: dict[str, Any] = Field(default_factory=dict)
    tools: tuple[dict[str, Any], ...] = ()
    """The tools the agent was offered, as ``{"name", "description", "parameters"}``."""

    @property
    def instructions(self) -> str:
        """The first user message, which is what the agent was asked to do."""
        for message in self.messages:
            if message.get("role") == "user":
                text = _text(message.get("content"))
                if text.strip():
                    return text
        return f"Recorded trace {self.trace_id}."

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        """Every tool call with its recorded result, as replay App recordings.

        Returns:
            ``{"action", "arguments", "result"}`` entries, in call order.
        """
        from plural.apps.replay import normalize_recordings

        return normalize_recordings(list(self.messages))


def recordings_by_app(
    traces: Iterable[RecordedTrace], *, default_app: str = "recorded"
) -> dict[str, list[dict[str, Any]]]:
    """Every recorded tool call, grouped by the App it belongs to.

    A call named ``crm__get_record`` belongs to App ``crm`` as action
    ``get_record``, the names an Environment with several Apps exposes. Other
    calls belong to ``default_app``.

    Returns:
        App name to replay App recordings, in call order.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trace in traces:
        for call in trace.tool_calls:
            app, action = app_action(str(call["action"]), default_app)
            grouped.setdefault(app, []).append(
                {**call, "action": action, "trace_id": trace.trace_id}
            )
    return grouped


def tools_by_app(
    traces: Iterable[RecordedTrace], *, default_app: str = "recorded"
) -> dict[str, dict[str, dict[str, Any]]]:
    """The tools the agent was offered, grouped by App like :func:`recordings_by_app`.

    When traces define the same tool differently, the last one wins, so a newer
    trace's description replaces an older one's.

    Returns:
        App name to action name to ``{"name", "description", "parameters"}``.
    """
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for trace in traces:
        for tool in trace.tools:
            app, action = app_action(str(tool["name"]), default_app)
            grouped.setdefault(app, {})[action] = {**tool, "name": action}
    return grouped


def app_action(name: str, default_app: str) -> tuple[str, str]:
    """Split ``crm__get_record`` into App ``crm`` and action ``get_record``.

    Returns:
        The App and the action; ``default_app`` for a name with no prefix.
    """
    app, separator, action = name.partition("__")
    if not separator or not app or not action:
        return default_app, name
    return app, action


def _tools(raw: Any) -> tuple[dict[str, Any], ...]:
    """Tool definitions in OpenAI, Anthropic, or plain form, as one shape.

    Returns:
        ``{"name", "description", "parameters"}`` for each named tool.
    """
    tools: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else ():
        if not isinstance(item, Mapping):
            continue
        nested = item.get("function")
        function: Mapping[str, Any] = nested if isinstance(nested, Mapping) else item
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        parameters = function.get("parameters") or function.get("input_schema")
        tools.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "parameters": dict(parameters)
                if isinstance(parameters, Mapping)
                else {"type": "object", "properties": {}},
            }
        )
    return tuple(tools)


def _fingerprint(messages: Sequence[Any]) -> str:
    text = json.dumps(list(messages), sort_keys=True, separators=(",", ":"), default=str)
    return "trace-" + hashlib.sha256(text.encode()).hexdigest()[:12]


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
        )
    return ""


def _from_plural_trace(payload: Mapping[str, Any]) -> RecordedTrace | None:
    """The fullest conversation in a Plural ``Trace``: its longest model call.

    Returns:
        The recorded conversation, or ``None`` when the Trace made no model call.
    """
    best: list[dict[str, Any]] = []
    tools: tuple[dict[str, Any], ...] = ()
    model = payload.get("model")
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "llm":
            continue
        raw_request, raw_response = step.get("request"), step.get("response")
        request = raw_request if isinstance(raw_request, dict) else {}
        response = raw_response if isinstance(raw_response, dict) else {}
        messages = [item for item in request.get("messages") or [] if isinstance(item, dict)]
        choices = response.get("choices") or []
        reply = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
        if isinstance(reply, dict):
            messages.append(reply)
        if len(messages) >= len(best):
            best = messages
            tools = _tools(request.get("tools")) or tools
            model = step.get("model") or model
    if not best:
        return None
    return RecordedTrace(
        trace_id=str(payload["trace_id"]),
        messages=tuple(best),
        model=str(model or "recorded"),
        metadata=dict(payload.get("metadata") or {}),
        tools=tools,
    )


def recorded_trace(
    payload: Mapping[str, Any] | BaseModel | RecordedTrace, index: int = 0
) -> RecordedTrace:
    """Read one recorded conversation.

    Accepts ``{"messages": [...]}`` (OpenAI chat logs and fine-tuning files,
    optionally with ``id`` or ``trace_id``, ``model``, ``metadata``, and the
    ``tools`` the agent was offered) and a Plural ``Trace`` with model-call
    steps. A trace without an id is named after its content, so reading the
    same conversation twice gives it the same id.

    Returns:
        The conversation.

    Raises:
        ValueError: The payload holds no conversation.
    """
    if isinstance(payload, RecordedTrace):
        return payload
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    if isinstance(payload.get("messages"), list):
        messages = tuple(item for item in payload["messages"] if isinstance(item, dict))
        return RecordedTrace(
            trace_id=str(payload.get("trace_id") or payload.get("id") or _fingerprint(messages)),
            messages=messages,
            model=str(payload.get("model") or "recorded"),
            metadata=dict(payload.get("metadata") or {}),
            tools=_tools(payload.get("tools")),
        )
    if payload.get("trace_id") and isinstance(payload.get("steps"), list):
        found = _from_plural_trace(payload)
        if found is not None:
            return found
    raise ValueError(
        f"Trace {index + 1} has no conversation. Give each trace a 'messages' list "
        "(OpenAI chat format) or a Plural Trace with model-call steps."
    )


def read_traces(
    source: str | Path | Iterable[Mapping[str, Any] | BaseModel | RecordedTrace],
) -> list[RecordedTrace]:
    """Read recorded conversations from a JSONL or JSON file, or from objects.

    A file may hold one trace per line, a JSON array, or traces pretty-printed
    one after another.

    A ``TraceDataset`` works too: its Traces are read in order.

    Returns:
        The conversations, in order.

    Raises:
        ValueError: The source is empty or a trace holds no conversation.
    """
    if isinstance(source, (str, Path)):
        items: list[Any] = _json_values(Path(source).read_text(encoding="utf-8"))
        if len(items) == 1 and isinstance(items[0], list):
            items = items[0]
    else:
        items = list(getattr(source, "traces", source))
    traces = [recorded_trace(item, index) for index, item in enumerate(items)]
    if not traces:
        raise ValueError("No recorded traces to read.")
    return traces


def _json_values(text: str) -> list[Any]:
    """Every JSON value in ``text``, one after another, however each is laid out.

    Returns:
        The values, in order.

    Raises:
        ValueError: Something in ``text`` is not JSON.
    """
    decoder = json.JSONDecoder()
    values: list[Any] = []
    position = 0
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            return values
        try:
            value, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError as exc:
            line = text.count("\n", 0, position) + 1
            raise ValueError(
                f"The trace starting on line {line} is not valid JSON: {exc.msg} "
                f"(line {exc.lineno})."
            ) from None
        values.append(value)


__all__ = [
    "RecordedTrace",
    "app_action",
    "read_traces",
    "recordings_by_app",
    "recorded_trace",
    "tools_by_app",
]
