"""Public, provider-neutral trajectory contract and tolerant adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from plural.common import FrozenModel

TrajectoryKind = Literal[
    "message",
    "reasoning",
    "action",
    "tool_result",
    "observation",
    "reward",
    "cost",
    "timing",
]


class TrajectoryEvent(FrozenModel):
    """One normalized trajectory event with its source payload retained."""

    sequence: int = Field(ge=0)
    kind: TrajectoryKind
    payload: dict[str, Any] = Field(default_factory=dict)
    original: Any = None


class Trajectory(FrozenModel):
    """Normalized interaction trajectory."""

    schema_version: Literal["1"] = "1"
    events: tuple[TrajectoryEvent, ...] = ()
    original: Any = None


_KINDS: dict[str, TrajectoryKind] = {
    "message": "message",
    "messages": "message",
    "model_turn": "message",
    "reasoning": "reasoning",
    "thinking": "reasoning",
    "action": "action",
    "actions": "action",
    "tool_call": "action",
    "tool_calls": "action",
    "tool_result": "tool_result",
    "tool_results": "tool_result",
    "tool_response": "tool_result",
    "observation": "observation",
    "observations": "observation",
    "reward": "reward",
    "rewards": "reward",
    "cost": "cost",
    "costs": "cost",
    "usage": "cost",
    "timing": "timing",
    "timings": "timing",
    "latency": "timing",
}


def _kind(item: Mapping[str, Any], hint: str | None = None) -> TrajectoryKind | None:
    raw = str(item.get("type") or item.get("kind") or item.get("event") or hint or "").lower()
    if raw in _KINDS:
        return _KINDS[raw]
    if "role" in item:
        return "message"
    if any(key in item for key in ("tool_call", "tool_calls", "action")):
        return "action"
    if any(key in item for key in ("tool_result", "tool_response")):
        return "tool_result"
    if "observation" in item:
        return "observation"
    if "reward" in item:
        return "reward"
    return None


def _rows(value: Any) -> list[tuple[Mapping[str, Any], str | None]]:
    if isinstance(value, Mapping):
        rows: list[tuple[Mapping[str, Any], str | None]] = []
        for key in (
            "messages",
            "reasoning",
            "actions",
            "tool_results",
            "observations",
            "rewards",
            "costs",
            "timings",
            "events",
            "trajectory",
            "transitions",
        ):
            nested = value.get(key)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)):
                rows.extend((item, key) for item in nested if isinstance(item, Mapping))
        return rows or [(value, None)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [(item, None) for item in value if isinstance(item, Mapping)]
    return []


def _decode(source: Any) -> Any:
    if isinstance(source, Path):
        return _decode(source.read_bytes())
    if isinstance(source, bytes):
        source = source.decode("utf-8")
    if isinstance(source, str):
        stripped = source.strip()
        if not stripped:
            return []
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return [json.loads(line) for line in stripped.splitlines() if line.strip()]
    return source


def _atif_events(value: Mapping[str, Any]) -> list[TrajectoryEvent] | None:
    """Read Harbor's ATIF document when ``schema_version`` says so.

    ATIF steps are the interchange record. Plural still keeps reward and verifier
    scores beside the trajectory; they are not ATIF fields.

    Returns:
        Normalized events, or ``None`` when the document is not ATIF.
    """
    schema = value.get("schema_version")
    steps = value.get("steps")
    if not isinstance(schema, str) or not schema.startswith("ATIF-"):
        return None
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes, bytearray)):
        return None
    events: list[TrajectoryEvent] = []

    def add(kind: TrajectoryKind, payload: Mapping[str, Any], original: Mapping[str, Any]) -> None:
        events.append(
            TrajectoryEvent(
                sequence=len(events),
                kind=kind,
                payload={str(key): item for key, item in payload.items()},
                original=dict(original),
            )
        )

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        message = step.get("message")
        if isinstance(message, str):
            add("message", {"source": step.get("source"), "message": message}, step)
        reasoning = step.get("reasoning")
        if isinstance(reasoning, str):
            add("reasoning", {"reasoning": reasoning}, step)
        calls = step.get("tool_calls")
        if isinstance(calls, Sequence) and not isinstance(calls, (str, bytes, bytearray)):
            for call in calls:
                if isinstance(call, Mapping):
                    add("action", call, call)
        observation = step.get("observation")
        if isinstance(observation, Mapping):
            add("observation", observation, observation)
        metrics = step.get("metrics")
        if isinstance(metrics, Mapping):
            add("cost", metrics, metrics)
    return events


def normalize_trajectory(source: Any) -> Trajectory:
    """Normalize current native formats and ATIF while retaining original data.

    A document whose ``schema_version`` starts with ``ATIF-`` is read as Harbor's
    Agent Trajectory Interchange Format. Other JSON and JSONL shapes use the
    existing event adapter.

    Returns:
        A provider-neutral trajectory with source payloads attached.
    """
    original = _decode(source)
    if isinstance(original, Mapping):
        atif = _atif_events(original)
        if atif is not None:
            return Trajectory(events=tuple(atif), original=original)
    events: list[TrajectoryEvent] = []
    for item, hint in _rows(original):
        kind = _kind(item, hint)
        if kind is None:
            continue
        events.append(
            TrajectoryEvent(
                sequence=len(events),
                kind=kind,
                payload={str(key): value for key, value in item.items()},
                original=dict(item),
            )
        )
    return Trajectory(events=tuple(events), original=original)


__all__ = ["Trajectory", "TrajectoryEvent", "normalize_trajectory"]
