"""Framework-recorded episode log for class-based Harnesses.

The class runner records every Environment reset and step and every model call
a Harness makes through ``HarnessAgent.complete`` into ``episode.jsonl``, one
record per line. A Harness author does not write this file and cannot omit
entries from it; it is the authoritative account of what happened, with timing
taken from the runner's own clock.

Each record carries ``schema: "plural.episode/v1"``. The fields that matter
for the Agent boundary are explicit:

- ``observation`` is the value the Environment returned to the Harness. It is
  the only part of a step a Harness may place in the Agent's context.
- ``reward``, ``terminated``, ``truncated``, ``info``, and ``view`` are episode
  bookkeeping. They are recorded for credit assignment, evaluation, and
  display, and are never Agent input.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from plural.usage import TokenUsage

EPISODE_SCHEMA = "plural.episode/v1"
EPISODE_FILE = "episode.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)
    return value


class EpisodeRecorder:
    """Append episode records to ``episode.jsonl`` as they happen.

    Records are flushed line by line so a crashed Harness still leaves the
    steps it completed. ``turn`` groups records: a model call opens a new turn
    and the Environment steps after it belong to that turn. A Harness that
    never calls a model takes one turn per step.
    """

    def __init__(self, path: str | Path = EPISODE_FILE) -> None:
        self.path = Path(path)
        self.path.write_text("", encoding="utf-8")
        self._sequence = 0
        self._turn = 0
        self._model_turn_open = False
        self._messages: list[Any] = []

    def _write(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=_jsonable) + "\n")

    def _record(
        self,
        kind: str,
        *,
        started_at: str,
        started_clock: float,
        turn: int | None,
        **fields: Any,
    ) -> None:
        self._sequence += 1
        self._write(
            {
                "schema": EPISODE_SCHEMA,
                "sequence": self._sequence,
                "kind": kind,
                "turn": turn,
                "started_at": started_at,
                "ended_at": _now(),
                "duration_ms": round((time.monotonic() - started_clock) * 1000, 3),
                **fields,
            }
        )

    def start(self) -> tuple[str, float]:
        """Mark the start of one recorded operation."""
        return _now(), time.monotonic()

    def reset(
        self,
        started: tuple[str, float],
        *,
        observation: Any = None,
        info: dict[str, Any] | None = None,
        view: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Record one Environment reset."""
        self._record(
            "environment.reset",
            started_at=started[0],
            started_clock=started[1],
            turn=None,
            observation=observation,
            info=info or {},
            view=view or None,
            error=error,
        )

    def step(
        self,
        started: tuple[str, float],
        *,
        action: str,
        arguments: dict[str, Any],
        observation: Any = None,
        reward: float | None = None,
        terminated: bool | None = None,
        truncated: bool | None = None,
        info: dict[str, Any] | None = None,
        view: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Record one Environment step."""
        if not self._model_turn_open:
            self._turn += 1
        self._record(
            "environment.step",
            started_at=started[0],
            started_clock=started[1],
            turn=self._turn,
            action=action,
            arguments=arguments,
            observation=observation,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            info=info or {},
            view=view or None,
            error=error,
        )

    def model_call(
        self,
        started: tuple[str, float],
        *,
        model: str,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        text: str = "",
        tool_calls: tuple[dict[str, Any], ...] = (),
        finish_reason: str | None = None,
        usage: TokenUsage | None = None,
        error: str | None = None,
    ) -> None:
        """Record one model call made through ``HarnessAgent.complete``.

        Messages already recorded by an earlier call are not repeated: when the
        new request extends the previous one, only the appended messages are
        stored, with ``messages_offset`` giving their position.
        """
        offset = 0
        if len(messages) >= len(self._messages) and messages[: len(self._messages)] == (
            self._messages
        ):
            offset = len(self._messages)
        self._messages = list(messages)
        self._turn += 1
        self._model_turn_open = True
        self._record(
            "model.call",
            started_at=started[0],
            started_clock=started[1],
            turn=self._turn,
            model=model,
            messages_offset=offset,
            messages=messages[offset:],
            message_count=len(messages),
            tools=[str((item.get("function") or {}).get("name") or "") for item in tools or ()],
            text=text,
            tool_calls=list(tool_calls),
            finish_reason=finish_reason,
            usage=(usage or TokenUsage()).model_dump(mode="json"),
            error=error,
        )


__all__ = ["EPISODE_FILE", "EPISODE_SCHEMA", "EpisodeRecorder"]
