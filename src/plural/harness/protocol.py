"""Versioned JSON-lines protocol between Plural and one agent harness."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

PROTOCOL_VERSION = "plural-harness-v1"
FORBIDDEN_HARNESS_KEYS = frozenset({"score", "scores", "reward", "verifier", "expected"})


class ProtocolModel(BaseModel):
    """Strict immutable protocol base."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HarnessRunRequest(ProtocolModel):
    """Public-only task request sent as one JSON line."""

    protocol: Literal["plural-harness-v1"] = "plural-harness-v1"
    type: Literal["run"] = "run"
    request_id: str
    task: dict[str, Any]
    agent: dict[str, Any]
    environment: dict[str, Any]
    workspace: str = "/workspace"


class HarnessEvent(ProtocolModel):
    """One parsed harness event."""

    protocol: Literal["plural-harness-v1"] = "plural-harness-v1"
    type: Literal["ready", "log", "trajectory", "artifact", "result", "error"]
    message: str | None = None
    path: str | None = None
    status: Literal["succeeded", "failed"] | None = None
    outputs: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    trace_id: str | None = None

    @field_validator("outputs", "artifacts")
    @classmethod
    def _safe_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        from plural.sandbox.models import safe_relative_path

        return tuple(safe_relative_path(item) for item in values)


class HarnessProtocolError(ValueError):
    """Malformed or policy-violating harness output."""


def encode_request(request: HarnessRunRequest) -> bytes:
    """Encode exactly one JSON-lines request."""
    return request.model_dump_json(exclude_none=True).encode() + b"\n"


def parse_events(payload: bytes, *, max_line_bytes: int = 1_000_000) -> tuple[HarnessEvent, ...]:
    """Parse strict JSON-lines and require one terminal result or error."""
    events: list[HarnessEvent] = []
    terminal = 0
    for index, raw_line in enumerate(payload.splitlines(), start=1):
        if not raw_line.strip():
            continue
        if len(raw_line) > max_line_bytes:
            raise HarnessProtocolError(f"harness line {index} exceeds {max_line_bytes} bytes")
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise HarnessProtocolError(f"invalid JSON on harness line {index}: {exc}") from exc
        if not isinstance(value, dict):
            raise HarnessProtocolError(f"harness line {index} must be an object")
        forbidden = _find_forbidden(value)
        if forbidden is not None:
            raise HarnessProtocolError(f"harness may not emit {forbidden!r}")
        try:
            event = HarnessEvent.model_validate(value)
        except ValueError as exc:
            raise HarnessProtocolError(f"invalid harness event on line {index}: {exc}") from exc
        if event.type in {"result", "error"}:
            terminal += 1
        events.append(event)
    if terminal != 1 or not events or events[-1].type not in {"result", "error"}:
        raise HarnessProtocolError("harness must end with exactly one result or error event")
    return tuple(events)


def _find_forbidden(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_HARNESS_KEYS:
                return str(key)
            nested = _find_forbidden(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_forbidden(item)
            if nested is not None:
                return nested
    return None


__all__ = [
    "FORBIDDEN_HARNESS_KEYS",
    "HarnessEvent",
    "HarnessProtocolError",
    "HarnessRunRequest",
    "PROTOCOL_VERSION",
    "encode_request",
    "parse_events",
]
