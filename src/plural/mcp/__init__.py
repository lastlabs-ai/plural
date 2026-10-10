"""Build the MCP server behind an App with FastMCP.

An App's server is an ordinary FastMCP server. Name it in ``environment.yaml``
and Plural starts a fresh copy for every Trial, inside the Runtime::

    apps:
      - name: crm
        mcp:
          server: server.py:mcp

Every tool becomes an action the Agent can take. This module gives the server
what it needs from the Trial:

- :func:`environment_resources` and :func:`task_resources`, the two read-only
  folders of files the Environment and the Task supply. The Trial references
  them; it does not own them, so nothing written during a Trial changes them.
- :func:`scratch`, a writable folder for this Trial only, deleted when it ends.
- :func:`reset` and :func:`snapshot`, which register the hooks Plural calls to
  start an episode from a Task's state and to report state to Verifiers. The
  Agent never sees either as a tool.

Install FastMCP with ``pip install 'plural[mcp]'``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

RESET_TOOL = "plural_reset"
SNAPSHOT_TOOL = "plural_snapshot"
HOOK_TOOLS = frozenset({RESET_TOOL, SNAPSHOT_TOOL})
ENVIRONMENT_RESOURCES = "environment-resources"
TASK_RESOURCES = "task-resources"
# 3825 spells EVAL on a phone keypad.
PORT = 3825


def _sandbox_path(value: str) -> Path:
    root = os.environ.get("PLURAL_SANDBOX_ROOT")
    if root and value.startswith("/"):
        return Path(root) / value.removeprefix("/")
    return Path(value)


def resources_root() -> Path | None:
    """The folder holding this Trial's resources, or ``None`` outside a Trial.

    Returns:
        The folder with ``environment-resources/`` and ``task-resources/``.
    """
    value = os.environ.get("PLURAL_RESOURCES_DIR")
    return _sandbox_path(value) if value else None


def environment_resources() -> Path:
    """The Environment's files, read-only, shared by every Task.

    Paths inside are the ones listed under ``resources`` in
    ``environment.yaml``, such as ``resources/policy.md``. Outside a Trial,
    such as while you develop the server, this is the Environment folder
    itself, so the same relative paths work.

    Returns:
        The folder.
    """
    root = resources_root()
    return root / ENVIRONMENT_RESOURCES if root is not None else Path.cwd()


def task_resources() -> Path | None:
    """The running Task's own files, read-only, or ``None`` when it has none.

    Returns:
        The folder, beside :func:`environment_resources`, never merged into it.
    """
    root = resources_root()
    folder = root / TASK_RESOURCES if root is not None else None
    return folder if folder is not None and folder.is_dir() else None


def scratch() -> Path:
    """A writable folder for this Trial only, empty at the start and deleted at the end.

    Returns:
        The folder.
    """
    value = os.environ.get("PLURAL_APP_DIR")
    folder = Path(value) if value else Path.cwd() / ".plural" / "scratch"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _register(server: Any, name: str, fn: Callable[..., Any], description: str) -> None:
    try:
        add = server.tool
    except AttributeError:
        raise TypeError("Pass the FastMCP server, such as @plural.mcp.snapshot(mcp)") from None
    add(name=name, description=description, meta={"plural": "hook"})(fn)


def reset(server: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register the function that starts each episode from the Task's state.

    The function receives ``initial_state``, the Task's starting state for this
    App, as a dict. Whatever it returns, if anything, is the Agent's first
    observation, so return ``None`` unless the Agent should see it::

        @plural.mcp.reset(mcp)
        def start(initial_state: dict) -> None:
            TICKETS[:] = initial_state.get("tickets", [])

    Returns:
        A decorator that leaves the function unchanged.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        def hook(initial_state: dict[str, Any] | None = None) -> Any:
            return fn(dict(initial_state or {}))

        _register(server, RESET_TOOL, hook, "Plural: start an episode. Never offered to the Agent.")
        return fn

    return decorate


def snapshot(server: Any) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
    """Register the function that reports the server's state as JSON, for Verifiers.

    ::

        @plural.mcp.snapshot(mcp)
        def state() -> dict:
            return {"tickets": TICKETS}

    Returns:
        A decorator that leaves the function unchanged.
    """

    def decorate(fn: Callable[[], Any]) -> Callable[[], Any]:
        def hook() -> str:
            return json.dumps(fn(), sort_keys=True, default=str)

        _register(server, SNAPSHOT_TOOL, hook, "Plural: report state for Verifiers. Never offered.")
        return fn

    return decorate


def is_hook(tool: Mapping[str, Any]) -> bool:
    """Whether an MCP tool is one of Plural's hooks rather than an action.

    Returns:
        True for the reset and snapshot hooks.
    """
    return str(tool.get("name") or "") in HOOK_TOOLS


__all__ = [
    "ENVIRONMENT_RESOURCES",
    "PORT",
    "HOOK_TOOLS",
    "RESET_TOOL",
    "SNAPSHOT_TOOL",
    "TASK_RESOURCES",
    "environment_resources",
    "is_hook",
    "reset",
    "resources_root",
    "scratch",
    "snapshot",
    "task_resources",
]
