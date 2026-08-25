"""Runtime protocol for executing tools during a rollout.

Examples:
    >>> from plural.environments.runtime import LocalRuntime
    >>> rt = LocalRuntime({"add": lambda a, b: a + b})
    >>> rt.call("add", {"a": 1, "b": 2})
    3
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from plural.environments.fingerprint import (
    callable_implementation_digest,
    public_configuration,
    stable_fingerprint_value,
)


@runtime_checkable
class Runtime(Protocol):
    """Execution surface for environment tools."""

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool by name.

        Args:
            name: Tool name.
            arguments: Keyword arguments for the tool.

        Returns:
            Tool result.
        """
        ...


class LocalRuntime:
    """In-process runtime that calls registered Python callables.

    Args:
        tools: Mapping of tool name to callable.
    """

    def __init__(self, tools: dict[str, Callable[..., Any]] | None = None) -> None:
        self.tools = dict(tools or {})

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """Register a tool.

        Args:
            name: Tool name.
            fn: Python callable.
        """
        self.tools[name] = fn

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a registered tool.

        Args:
            name: Tool name.
            arguments: Keyword arguments.

        Returns:
            Tool result.

        Raises:
            KeyError: If the tool is unknown.
        """
        if name not in self.tools:
            raise KeyError(f"unknown tool: {name}")
        return self.tools[name](**arguments)

    def call_timed(self, name: str, arguments: dict[str, Any]) -> tuple[Any, float]:
        """Call a tool and return ``(result, latency_ms)``.

        Args:
            name: Tool name.
            arguments: Keyword arguments.

        Returns:
            Tuple of result and latency in milliseconds.
        """
        started = time.perf_counter()
        result = self.call(name, arguments)
        return result, (time.perf_counter() - started) * 1000


def runtime_fingerprint(runtime: Runtime) -> str:
    """Return stable pre-execution identity for a tool runtime.

    Custom runtimes may expose ``fingerprint()`` or ``fingerprint_payload()``.
    Otherwise their stable configuration and ``call()`` implementation are hashed.
    """
    fingerprint = getattr(runtime, "fingerprint", None)
    if callable(fingerprint):
        value = fingerprint()
        if not isinstance(value, str) or not value:
            raise TypeError("runtime fingerprint() must return a non-empty string")
        return value
    payload_hook = getattr(runtime, "fingerprint_payload", None)
    payload: Any
    if isinstance(runtime, LocalRuntime):
        payload = {
            "tools": {
                name: callable_implementation_digest(fn)
                for name, fn in sorted(runtime.tools.items())
            }
        }
    elif callable(payload_hook):
        payload = stable_fingerprint_value(payload_hook())
    else:
        payload = public_configuration(runtime)
    runtime_type = type(runtime)
    canonical = json.dumps(
        {
            "type": f"{runtime_type.__module__}.{runtime_type.__qualname__}",
            "configuration": payload,
            "call_implementation": callable_implementation_digest(runtime.call),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
