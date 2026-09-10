"""Access packaged tracing resources."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, cast


def trace_json_schema() -> dict[str, Any]:
    """Load the canonical trace JSON Schema from the installed package.

    Returns:
        The JSON Schema as a mutable dictionary.

    Raises:
        ValueError: If the packaged resource is not a JSON object.
    """
    resource = files("plural.schemas").joinpath("trace.v3.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise ValueError("packaged trace schema is not a JSON object")
    return cast(dict[str, Any], schema)
