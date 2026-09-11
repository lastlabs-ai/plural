"""Verifier evidence contracts and Environment fit checks."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import AliasChoices, Field

from plural.common import FrozenModel
from plural.environments.types import HIDDEN_SCHEMA_KEY, is_hidden_schema_field


class EvidenceContract(FrozenModel):
    """What a Verifier needs from the Environment and Trial artifacts."""

    artifacts: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices("artifacts", "required_artifacts"),
    )
    state_paths: tuple[str, ...] = ()
    observation_paths: tuple[str, ...] = ()
    include_hidden_state: bool = False


def normalize_pointer(path: str) -> str:
    """Accept ``board`` or ``/board`` as a JSON Pointer.

    Args:
        path: Author-facing pointer.

    Returns:
        A pointer that always starts with ``/``.
    """
    value = path.strip()
    if not value:
        raise ValueError("evidence path must be non-empty")
    return value if value.startswith("/") else f"/{value}"


def pointer_parts(path: str) -> tuple[str, ...]:
    """Split a JSON Pointer into unescaped segments.

    Args:
        path: Author-facing or RFC 6901 pointer.

    Returns:
        One segment per path component.
    """
    return tuple(
        part.replace("~1", "/").replace("~0", "~")
        for part in normalize_pointer(path).split("/")
        if part
    )


def schema_property(schema: Mapping[str, Any], path: str) -> dict[str, Any] | None:
    """Return the JSON Schema node for a pointer, if present.

    Args:
        schema: An Environment observation or state JSON Schema.
        path: Pointer into ``properties``.

    Returns:
        The nested schema object, or ``None`` when the path is absent.
    """
    node: Any = schema
    for part in pointer_parts(path):
        if not isinstance(node, Mapping):
            return None
        properties = node.get("properties")
        if not isinstance(properties, Mapping) or part not in properties:
            return None
        node = properties[part]
    return node if isinstance(node, dict) else None


def extract_pointer(data: Any, path: str) -> Any:
    """Read one JSON Pointer from a mapping; missing paths are omitted.

    Args:
        data: Observation or state mapping.
        path: Pointer into that mapping.

    Returns:
        The value at the path, or ``None`` if any segment is missing.
    """
    node = data
    for part in pointer_parts(path):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def validate_evidence_contract(
    environment_name: str,
    observation_schema: Mapping[str, Any],
    state_schema: Mapping[str, Any],
    contract: EvidenceContract,
) -> list[str]:
    """Fail closed when a Verifier path is absent from the Environment schemas.

    Args:
        environment_name: Environment revision name for error text.
        observation_schema: Environment observation JSON Schema.
        state_schema: Environment state JSON Schema.
        contract: Declared Verifier evidence.

    Returns:
        Human-readable pin errors. Empty means the pin is valid.
    """
    errors: list[str] = []
    for path in contract.observation_paths:
        if schema_property(observation_schema, path) is None:
            errors.append(
                f"observation path {path!r} is absent from Environment {environment_name!r}"
            )
    for path in contract.state_paths:
        spec = schema_property(state_schema, path)
        if spec is None:
            errors.append(f"state path {path!r} is absent from Environment {environment_name!r}")
            continue
        if is_hidden_schema_field(spec) and not contract.include_hidden_state:
            errors.append(
                f"state path {path!r} is hidden; set include_hidden_state on the Verifier"
            )
    return errors


def environment_view(
    contract: EvidenceContract,
    *,
    observation: Mapping[str, Any] | None,
    state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Filter Environment observation/state to the contracted paths.

    Args:
        contract: Declared Verifier evidence.
        observation: Episode observation mapping, if available.
        state: Episode state mapping, if available.

    Returns:
        ``{observation, state}`` containing only contracted fields.
    """
    visible_observation: dict[str, Any] = {}
    for path in contract.observation_paths:
        value = extract_pointer(observation or {}, path)
        if value is not None:
            visible_observation[pointer_parts(path)[-1]] = value
    visible_state: dict[str, Any] = {}
    for path in contract.state_paths:
        value = extract_pointer(state or {}, path)
        if value is not None:
            visible_state[pointer_parts(path)[-1]] = value
    return {"observation": visible_observation, "state": visible_state}


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


__all__ = [
    "HIDDEN_SCHEMA_KEY",
    "EvidenceContract",
    "environment_view",
    "extract_pointer",
    "first_json_mapping",
    "normalize_pointer",
    "schema_property",
    "validate_evidence_contract",
]
