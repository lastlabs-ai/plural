"""Answer an App's actions from recorded traces.

A replay App stands in for a system you have traces of but cannot run or
reset, such as a production API an agent called. Each recorded call pairs an
action and its arguments with the result the system returned. When the Agent
makes the same call, it gets the recorded result.

A call with no exact recording is answered by ``fallback``:

- ``"nearest"`` (the default) returns the recorded result of the same action
  whose arguments match best,
- ``"error"`` tells the Agent no recording matches.

Either way the step is marked ``off_recording``, so rewards on it can be
filtered out of training data. A replay App's control level is ``replayed``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from plural.apps.base import App
from plural.apps.definition import AppAction, SecretReference
from plural.environments.types import State

_JSON_TYPES = {bool: "boolean", int: "integer", float: "number", str: "string"}


def _canonical(arguments: Mapping[str, Any]) -> str:
    return json.dumps(dict(arguments), sort_keys=True, separators=(",", ":"), default=str)


def normalize_recordings(raw: Any) -> list[dict[str, Any]]:
    """Read recorded calls from the shapes Plural understands.

    Accepts a list of ``{"action", "arguments", "result"}`` objects, Plural
    ``episode.jsonl`` records (each ``environment.step``), and chat messages in
    which assistant ``tool_calls`` are answered by ``tool`` messages.

    Returns:
        ``{"action", "arguments", "result"}`` records in order.
    """
    rows = raw if isinstance(raw, list) else []
    recordings: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if "action" in row and "result" in row and row.get("kind") is None:
            recordings.append(
                {
                    "action": str(row["action"]),
                    "arguments": dict(row.get("arguments") or {}),
                    "result": row["result"],
                }
            )
        elif row.get("kind") == "environment.step" and not row.get("error"):
            recordings.append(
                {
                    "action": str(row.get("action") or ""),
                    "arguments": dict(row.get("arguments") or {}),
                    "result": row.get("observation"),
                }
            )
        elif row.get("role") == "assistant":
            for call in row.get("tool_calls") or ():
                function = call.get("function") or {}
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                pending[str(call.get("id") or "")] = {
                    "action": str(function.get("name") or ""),
                    "arguments": dict(arguments) if isinstance(arguments, Mapping) else {},
                }
        elif row.get("role") == "tool":
            call = pending.pop(str(row.get("tool_call_id") or ""), None)
            if call is not None:
                content = row.get("content")
                try:
                    result = json.loads(content) if isinstance(content, str) else content
                except json.JSONDecodeError:
                    result = content
                recordings.append({**call, "result": result})
    return [item for item in recordings if item["action"]]


def read_recordings(path: Path) -> list[dict[str, Any]]:
    """Load recorded calls from a ``.json`` or ``.jsonl`` file.

    Returns:
        Normalized recordings.
    """
    text = path.read_text(encoding="utf-8")
    try:
        raw: Any = json.loads(text)
    except json.JSONDecodeError:
        raw = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(raw, Mapping):
        raw = raw.get("recordings") or raw.get("messages") or raw.get("events") or []
    return normalize_recordings(raw)


def _inferred(recordings: Sequence[Mapping[str, Any]], action: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for item in recordings:
        if item["action"] != action:
            continue
        for key, value in item["arguments"].items():
            kind = _JSON_TYPES.get(type(value))
            properties.setdefault(key, {"type": kind} if kind else {})
    return {"type": "object", "properties": properties, "additionalProperties": True}


class ReplayApp(App[State]):
    """An App that answers from recorded calls.

    Settings:
        recordings: A ``.json`` or ``.jsonl`` file of recorded calls in the
            Environment folder.
        fallback: ``"nearest"`` or ``"error"`` for a call with no exact recording.
        actions: Action declarations. Default: one per recorded action, with
            arguments inferred from the recordings.
        read_only: Actions that do not change state, so Verifiers may query them.
    """

    kind = "replay"
    snapshot_on_step = False

    def __init__(
        self,
        *,
        name: str | None = None,
        recordings: str | None = None,
        fallback: Literal["nearest", "error"] = "nearest",
        actions: Sequence[Mapping[str, Any] | AppAction] | None = None,
        read_only: Sequence[str] = (),
        secrets: Iterable[str | SecretReference] | None = None,
        credentials: Iterable[str | SecretReference] | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(
            name=name or type(self).name or None,
            description=description,
            secrets=secrets,
            credentials=credentials,
        )
        if recordings is None:
            raise ValueError(f"Replay App {self.name!r} needs recordings: a .json or .jsonl file")
        if fallback not in {"nearest", "error"}:
            raise ValueError("fallback must be 'nearest' or 'error'")
        self.recordings_file = recordings
        self.fallback = fallback
        self.read_only = tuple(read_only)
        self._declared = (
            tuple(
                item if isinstance(item, AppAction) else AppAction.model_validate(item)
                for item in actions
            )
            if actions is not None
            else None
        )
        self._recordings: list[dict[str, Any]] | None = None
        self._last: dict[str, Any] = {}
        self._calls = 0
        self._off_recording = 0

    def recordings(self) -> list[dict[str, Any]]:
        """The recorded calls, read once.

        Returns:
            Normalized recordings.

        Raises:
            ValueError: When the file is missing or has no calls.
        """
        if self._recordings is None:
            path = Path(self.recordings_file)
            path = path if path.is_absolute() else self.workspace / path
            if not path.is_file():
                raise ValueError(f"Replay App {self.name!r}: {path} does not exist")
            self._recordings = read_recordings(path)
            if not self._recordings:
                raise ValueError(f"Replay App {self.name!r}: {path} has no recorded calls")
        return self._recordings

    def actions(self) -> tuple[AppAction, ...]:
        """One action per recorded action name, unless declared explicitly.

        Returns:
            The App's actions.
        """
        if self._declared is not None:
            return self._declared
        names = list(dict.fromkeys(item["action"] for item in self.recordings()))
        return tuple(
            AppAction(
                name=name,
                description=f"Replayed {name}.",
                parameters=_inferred(self.recordings(), name),
                mutates_state=name not in self.read_only,
            )
            for name in names
        )

    def call(self, action: str, arguments: Mapping[str, Any]) -> Any:
        """Answer from the recordings.

        Returns:
            The recorded result.

        Raises:
            ValueError: For an unknown action, or no match with ``fallback="error"``.
        """
        known = {item.name for item in self.actions()}
        if action not in known:
            raise ValueError(
                f"unknown action {action!r}; available actions: {', '.join(sorted(known))}"
            )
        self._calls += 1
        same = [item for item in self.recordings() if item["action"] == action]
        wanted = _canonical(arguments)
        for item in same:
            if _canonical(item["arguments"]) == wanted:
                self._last = {"replay": "exact"}
                return item["result"]
        self._off_recording += 1
        self._last = {"replay": self.fallback, "off_recording": True}
        if self.fallback == "error" or not same:
            raise ValueError(f"No recorded {action} call matches these arguments.")
        best = max(same, key=lambda item: _overlap(item["arguments"], arguments))
        return best["result"]

    def step_info(self) -> dict[str, Any]:
        """Whether the last call was answered off the recordings.

        Returns:
            ``replay`` and, when it was, ``off_recording``.
        """
        return dict(self._last)

    def reset(self, initial_state: Mapping[str, Any]) -> Any:
        """Start counting calls again; recordings have no state to reset.

        Returns:
            ``None``.
        """
        del initial_state
        self._last = {}
        self._calls = 0
        self._off_recording = 0
        return None

    def snapshot(self) -> dict[str, int]:
        """How many calls this episode made, and how many missed the recordings.

        Returns:
            The counts.
        """
        return {"calls": self._calls, "off_recording": self._off_recording}

    def is_local(self) -> bool:
        """A replay runs inside the Runtime.

        Returns:
            ``True``.
        """
        return True

    def _config(self) -> dict[str, Any]:
        config = super()._config()
        config.pop("actions", None)
        return config

    def _state_schema(self) -> dict[str, Any]:
        return {}


def _overlap(recorded: Mapping[str, Any], given: Mapping[str, Any]) -> int:
    return sum(1 for key, value in given.items() if recorded.get(key) == value)


__all__ = ["ReplayApp", "normalize_recordings", "read_recordings"]
