"""Helpers for reading Environment snapshots. EvidenceContract is gone."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def first_json_mapping(files: Sequence[Any], names: Sequence[str]) -> dict[str, Any]:
    """Parse the first matching JSON object from downloaded files.

    Args:
        files: Downloaded Trial artifacts.
        names: Preferred file names, in order.

    Returns:
        The first matching JSON object, or an empty mapping.
    """
    wanted = set(names)
    for item in files:
        path = getattr(item, "path", "")
        if path not in wanted and not any(str(path).endswith(name) for name in names):
            continue
        data = getattr(item, "data", b"")
        try:
            payload = data.decode() if isinstance(data, bytes) else str(data)
            value = json.loads(payload)
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def as_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a plain dict copy of a mapping."""
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = ["as_mapping", "first_json_mapping"]
