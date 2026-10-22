"""What the framework adapters share: framework runs mapped to Plural runs."""

from __future__ import annotations

import json
import threading
from collections.abc import Hashable, Mapping
from datetime import datetime, timezone
from typing import Any

from plural.external.tracing import Run, Tracer, current_run, tracer


class Roots:
    """Each top-level framework run, and the Plural run it records into.

    A framework run that starts inside a traced run, such as an episode,
    records into it and leaves finishing it to its owner. One that starts
    outside any gets a run of its own, finished when the framework run ends.
    """

    def __init__(self, tracer_: Tracer | None) -> None:
        self._tracer = tracer_
        self._lock = threading.Lock()
        self._runs: dict[Hashable, tuple[Run, bool]] = {}

    def tracer(self) -> Tracer:
        return self._tracer or tracer()

    def open(self, key: Hashable, *, input: str | None = None) -> Run:  # noqa: A002
        with self._lock:
            known = self._runs.get(key)
        if known is not None:
            return known[0]
        active = current_run()
        if active is not None and not active.finished:
            run, owned = active, False
        else:
            run, owned = self.tracer().run(input=input), True
        with self._lock:
            self._runs.setdefault(key, (run, owned))
            return self._runs[key][0]

    def get(self, key: Hashable) -> Run | None:
        with self._lock:
            known = self._runs.get(key)
        return known[0] if known else None

    def close(self, key: Hashable, *, answer: Any = None, error: str | None = None) -> None:
        with self._lock:
            run, owned = self._runs.pop(key, (None, False))
        if run is None or not owned:
            return
        if error is not None:
            run.fail(error)
        else:
            run.finish(answer)


def from_nanoseconds(value: int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1e9, tz=timezone.utc)


def from_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def loads(value: Any) -> Any:
    """Parse a JSON string a framework stored as text.

    Returns:
        The parsed value, or ``value`` as is when it is not JSON text.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(value, Mapping):
        for key in ("text", "content", "output"):
            if isinstance(value.get(key), str):
                return str(value[key])
    return json.dumps(value, default=str)


def usage(prompt: Any, completion: Any, cached: Any = None) -> dict[str, Any] | None:
    out = {
        key: int(value)
        for key, value in (
            ("prompt_tokens", prompt),
            ("completion_tokens", completion),
            ("cached_tokens", cached),
        )
        if isinstance(value, (int, float))
    }
    return out or None
