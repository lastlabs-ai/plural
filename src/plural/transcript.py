"""Export an episode as a plain chat transcript.

Every execution that records ``episode.jsonl`` also gets ``trajectory.json``:
the conversation in the OpenAI chat shape most tooling already reads, beside
``status``, ``time_elapsed``, and ``finalized``. Each message has a ``role`` and
``content``; assistant messages add ``reasoning_content`` and ``tool_calls``,
and tool messages add ``tool_call_id`` and ``name``.

``atif-trajectory.json`` is the interchange record, with per-call usage and
timing. This file is the same turn-taking with nothing else, so it can be read
at a glance or replayed as model input. Like ATIF, it holds only what reached
the Agent.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

TRAJECTORY_FILE = "trajectory.json"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [
            str(item.get("text"))
            for item in value
            if isinstance(item, Mapping) and item.get("type") == "text" and item.get("text")
        ]
        if parts:
            return "\n".join(parts)
    return json.dumps(value, sort_keys=True, default=str)


def _status(records: Sequence[Mapping[str, Any]]) -> str:
    """Return how the episode ended, in the words of Mercor's ``status``.

    Returns:
        ``completed`` when the Agent finished, gave a final reply, or the
        Environment terminated; ``truncated`` when a limit ended it first;
        otherwise ``incomplete``.
    """
    status = "incomplete"
    for record in records:
        if record.get("kind") == "agent.finish" or record.get("terminated"):
            return "completed"
        if record.get("truncated"):
            status = "truncated"
    calls = [record for record in records if record.get("kind") == "model.call"]
    final_reply = bool(calls) and not calls[-1].get("tool_calls") and not calls[-1].get("error")
    return "completed" if status == "incomplete" and final_reply else status


def _tool_calls(raw: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, call in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(call, Mapping):
            continue
        function = call.get("function")
        function = function if isinstance(function, Mapping) else call
        arguments = function.get("arguments")
        calls.append(
            {
                "id": str(call.get("id") or f"call_{index}"),
                "type": "function",
                "function": {
                    "name": str(function.get("name") or ""),
                    "arguments": (
                        arguments
                        if isinstance(arguments, str)
                        else json.dumps(arguments or {}, sort_keys=True)
                    ),
                },
            }
        )
    return calls


def _assistant(content: Any, reasoning: Any, calls: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": _text(content)}
    if isinstance(reasoning, str) and reasoning:
        message["reasoning_content"] = reasoning
    tool_calls = _tool_calls(calls)
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _clean(message: Mapping[str, Any], names: Mapping[str, str]) -> dict[str, Any] | None:
    """One requested message in the transcript shape, without provider extras.

    Returns:
        The message, or ``None`` for a role the transcript does not carry.
    """
    role = message.get("role")
    if role == "assistant":
        return _assistant(
            message.get("content"),
            message.get("reasoning_content") or message.get("reasoning"),
            message.get("tool_calls"),
        )
    if role == "tool":
        call_id = str(message.get("tool_call_id") or "")
        cleaned = {"role": "tool", "tool_call_id": call_id}
        name = message.get("name") or names.get(call_id)
        if name:
            cleaned["name"] = str(name)
        cleaned["content"] = _text(message.get("content"))
        return cleaned
    if role in {"system", "developer", "user"}:
        return {"role": str(role), "content": _text(message.get("content"))}
    return None


def _step_content(record: Mapping[str, Any]) -> str:
    """What a step returned to the Agent.

    Returns:
        The recorded tool content, else the observation's text.
    """
    content = record.get("content")
    if content is None:
        observation = record.get("observation")
        if isinstance(observation, Mapping):
            text = observation.get("text")
            content = text if isinstance(text, str) and text else observation
        else:
            content = observation if observation is not None else record.get("summary")
    if content is None and record.get("error"):
        content = f"Error: {record['error']}"
    return _text(content)


def _seconds(start: Any, end: Any) -> float | None:
    try:
        delta = datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))
    except ValueError:
        return None
    return delta.total_seconds()


def episode_to_messages(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Convert ``plural.episode/v1`` records into one chat transcript.

    The transcript is the last request the model received, which already holds
    every earlier turn, followed by the model's final reply and the tool results
    that came after it.

    Returns:
        ``{"messages", "status", "time_elapsed", "finalized"}``, the shape of
        Mercor's ``trajectory.json``.
    """
    ordered = sorted(
        (dict(item) for item in records if isinstance(item, Mapping)),
        key=lambda item: int(item.get("sequence") or 0),
    )
    requested: list[Mapping[str, Any]] = []
    tail: list[dict[str, Any]] = []
    last_call: dict[str, Any] | None = None
    for record in ordered:
        kind = record.get("kind")
        if kind == "model.call":
            delta = [item for item in record.get("messages") or [] if isinstance(item, Mapping)]
            offset = int(record.get("messages_offset") or 0)
            requested = [*requested[:offset], *delta]
            last_call = record
            tail = []
        elif kind in {"environment.step", "agent.finish"} and last_call is not None:
            tail.append(record)
    names: dict[str, str] = {}
    messages: list[dict[str, Any]] = []

    def add(message: dict[str, Any] | None) -> None:
        if message is None:
            return
        for call in message.get("tool_calls") or []:
            names[call["id"]] = call["function"]["name"]
        messages.append(message)

    for item in requested:
        add(_clean(item, names))
    if last_call is not None:
        add(
            _assistant(
                last_call.get("text"), last_call.get("reasoning"), last_call.get("tool_calls")
            )
        )
        for record in tail:
            call_id = str(record.get("tool_call_id") or "")
            finish = "finish" if record.get("kind") == "agent.finish" else ""
            name = str(record.get("action") or finish) or names.get(call_id, "")
            message: dict[str, Any] = {"role": "tool", "tool_call_id": call_id}
            if name:
                message["name"] = name
            message["content"] = _step_content(record)
            add(message)
    elapsed = (
        _seconds(ordered[0].get("started_at"), ordered[-1].get("ended_at")) if ordered else None
    )
    status = _status(ordered)
    return {
        "messages": messages,
        "status": status,
        **({"time_elapsed": round(elapsed, 3)} if elapsed is not None else {}),
        "finalized": status == "completed",
    }


__all__ = ["TRAJECTORY_FILE", "episode_to_messages"]
