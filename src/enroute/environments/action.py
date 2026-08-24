"""Parse a policy action into :class:`~enroute.tracing.schema.ParsedAction` rows.

Examples:
    >>> from enroute.environments.action import parse_tool_arguments
    >>> parse_tool_arguments('{"word": "crane"}')
    {'word': 'crane'}
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from enroute.environments.stop import StopReason
from enroute.tracing.schema import ParsedAction, RewardEvent, ToolCallStep
from enroute.types import ChatResponse, ToolCall, text_content

TEXT_ACTION = "respond"


class ActionResult(BaseModel):
    """Result returned by :meth:`Environment.apply_action` for one policy turn.

    Environment authors use this model to describe the action that was applied
    and any tool calls, rewards, stop request, or diagnostics it produced.
    Framework-owned :meth:`Environment.step` records these fields and advances
    the episode lifecycle.

    Attributes:
        parsed_actions: Trace-safe representations of the applied actions.
        tool_calls: Tool executions produced while applying the action.
        reward_events: Dense rewards attached to this policy turn.
        stop_reason: Explicit reason to stop, or ``None`` to continue.
        info: Author-defined diagnostics merged into the step result.
    """

    parsed_actions: list[ParsedAction] = Field(default_factory=list)
    tool_calls: list[ToolCallStep] = Field(default_factory=list)
    reward_events: list[RewardEvent] = Field(default_factory=list)
    stop_reason: StopReason | None = None
    info: dict[str, Any] = Field(default_factory=dict)


def is_text_action(action: ParsedAction) -> bool:
    """Return whether an action is a policy text response."""
    return action.name == TEXT_ACTION


def is_tool_action(action: ParsedAction) -> bool:
    """Return whether an action requests a tool."""
    return bool(action.name) and not is_text_action(action)


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
        action = response
    if isinstance(action, ChatResponse):
        tool_calls = action.message.tool_calls
        if tool_calls:
            action = tool_calls
        else:
            return [
                ParsedAction(
                    name=TEXT_ACTION,
                    arguments={"text": text_content(action.message)},
                )
            ], [None]
    if not action:
        return [ParsedAction(name=TEXT_ACTION, arguments={})], [None]
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
                    name=str(item.get("name") or TEXT_ACTION),
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
