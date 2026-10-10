"""Apps: the systems an Agent acts in, composed into an Environment.

An App is a named bundle of actions with optional state hooks. Write one in
Python by subclassing :class:`App`, or connect an existing system with
``App.mcp(...)``, ``App.openapi(...)``, or ``App.replay(...)``. Build an
MCP server of your own with FastMCP; see :mod:`plural.mcp`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plural.apps.definition import (
    AppAction,
    AppControl,
    AppDefinition,
    AppKind,
    ExposedAction,
    RewarderDefinition,
    SecretReference,
)

if TYPE_CHECKING:
    from plural.apps.base import App, rewarder
    from plural.apps.host import AppHost
    from plural.apps.mcp import MCPApp
    from plural.apps.openapi import OpenAPIApp
    from plural.apps.replay import ReplayApp

_LAZY = {
    "App": "plural.apps.base",
    "rewarder": "plural.apps.base",
    "AppHost": "plural.apps.host",
    "MCPApp": "plural.apps.mcp",
    "OpenAPIApp": "plural.apps.openapi",
    "ReplayApp": "plural.apps.replay",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'plural.apps' has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module), name)


__all__ = [
    "App",
    "AppAction",
    "AppControl",
    "AppDefinition",
    "AppHost",
    "AppKind",
    "ExposedAction",
    "MCPApp",
    "OpenAPIApp",
    "ReplayApp",
    "RewarderDefinition",
    "SecretReference",
    "rewarder",
]
