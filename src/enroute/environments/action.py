"""Parse a policy action into :class:`~enroute.tracing.schema.ParsedAction` rows.

Examples:
    >>> from enroute.environments.action import parse_tool_arguments
    >>> parse_tool_arguments('{"word": "crane"}')
    {'word': 'crane'}
"""

from __future__ import annotations

import json
from typing import Any

from enroute.tracing.schema import ParsedAction
from enroute.types import ChatResponse, ToolCall


def normalize_action(
    action: Any,
    response: ChatResponse | None,
) -> tuple[list[ParsedAction], list[str | None]]:
    """Turn a step action (or response tool calls) into parsed rows.

    Args:
        action: Parsed actions, tool calls, a response, or ``None``.
        response: Chat response used when ``action`` is ``None``.

    Returns:
        ``(parsed_actions, tool_call_ids)`` aligned lists.
    """
    if action is None and response is not None:
        action = response.message.tool_calls
    if isinstance(action, ChatResponse):
        action = action.message.tool_calls
    if not action:
        return [ParsedAction(name="respond", arguments={})], [None]
    if isinstance(action, ParsedAction):
        return [action], [None]
    if isinstance(action, ToolCall):
        parsed_one = ParsedAction(
            name=action.function.name,
            arguments=parse_tool_arguments(action.function.arguments),
        )
        return [parsed_one], [action.id]
    parsed: list[ParsedAction] = []
    ids: list[str | None] = []
    for item in action:
        if isinstance(item, ParsedAction):
            parsed.append(item)
            ids.append(None)
        elif isinstance(item, ToolCall):
            parsed.append(
                ParsedAction(
                    name=item.function.name,
                    arguments=parse_tool_arguments(item.function.arguments),
                )
            )
            ids.append(item.id)
        elif isinstance(item, dict):
            parsed.append(
                ParsedAction(
                    name=str(item.get("name") or "respond"),
                    arguments=dict(item.get("arguments") or {}),
                )
            )
            ids.append(item.get("id"))
        else:
            parsed.append(ParsedAction(name=str(item), arguments={}))
            ids.append(None)
    return parsed, ids


def parse_tool_arguments(raw: str) -> dict[str, Any]:
    """Parse a tool-call arguments string into a dict.

    Args:
        raw: JSON object string from the model.

    Returns:
        Parsed arguments, or ``{"raw": ...}`` if JSON is invalid.
    """
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(value, dict):
        return value
    return {"value": value}
