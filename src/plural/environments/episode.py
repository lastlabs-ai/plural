"""Open-episode bookkeeping used by :class:`~plural.environments.env.Environment`.

Examples:
    >>> from plural.environments.episode import Episode
    >>> from plural.environments.task import TaskData
    >>> from plural.tracing.schema import Trace
    >>> ep = Episode(task=TaskData(task_id="t", input="go"), trace=Trace(), messages=[])
    >>> ep.turn
    0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from plural.environments.stop import StopReason
from plural.environments.task import TaskData
from plural.tracing.schema import Trace, Turn
from plural.types import ChatResponse, Message


@dataclass
class Episode:
    """In-progress episode: messages, turn count, and the open trace."""

    task: TaskData
    trace: Trace
    messages: list[Message]
    turn: int = 0
    observation: Any = None
    last_response: ChatResponse | None = None
    closed: bool = False
    stop_reason: StopReason | None = None
    terminated: bool = False
    truncated: bool = False
    tool_errors: list[str] = field(default_factory=list)
    failure_persisted: bool = False


def episode_metrics(episode: Episode) -> dict[str, Any]:
    """Aggregate turn, cost, and latency stats for a closing episode.

    Args:
        episode: Episode whose turns are scored.

    Returns:
        Metrics dict stored on ``trace.metrics``.
    """
    turns = [s for s in episode.trace.steps if isinstance(s, Turn)]
    tool_count = sum(len(item.actions) for item in turns)
    cost = 0.0
    latency = 0.0
    for turn in turns:
        output = turn.model_output
        if isinstance(output, ChatResponse):
            if output.usage and output.usage.cost is not None:
                cost += output.usage.cost
            if output.latency_ms is not None:
                latency += output.latency_ms
        elif isinstance(output, dict):
            usage = output.get("usage") or {}
            if usage.get("cost") is not None:
                cost += float(usage["cost"])
            if output.get("latency_ms") is not None:
                latency += float(output["latency_ms"])
    return {
        "turns": episode.turn,
        "turn_steps": len(turns),
        "action_calls": tool_count,
        "cost": cost,
        "latency_ms": latency,
        "stop_reason": episode.stop_reason.value if episode.stop_reason is not None else None,
    }
