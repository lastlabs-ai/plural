"""Map an App kind to the class that runs it."""

from __future__ import annotations

from typing import Any

from plural.apps.base import App
from plural.apps.definition import AppKind


def app_class(kind: AppKind) -> type[App[Any]]:
    """Return the built-in class for an App kind that has no Python reference.

    Returns:
        The App class.
    """
    if kind == "mcp":
        from plural.apps.mcp import MCPApp

        return MCPApp
    if kind == "openapi":
        from plural.apps.openapi import OpenAPIApp

        return OpenAPIApp
    if kind == "data":
        from plural.apps.data import DataApp

        return DataApp
    if kind == "replay":
        from plural.apps.replay import ReplayApp

        return ReplayApp
    raise ValueError(f"A {kind!r} App needs a file.py:Class reference")


__all__ = ["app_class"]
