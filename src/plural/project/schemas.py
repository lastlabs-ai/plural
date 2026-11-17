"""JSON Schemas for public authoring models and project manifests."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_INTERNAL_SCHEMA_TYPES = frozenset(
    {
        "HarnessBinding",
        "HarnessPackage",
        "HarnessProtocol",
        "PackageSource",
    }
)


def public_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a JSON Schema containing only public authoring fields.

    Returns:
        A detached schema safe for generated public references.
    """
    schema = model.model_json_schema()

    def clean(value: Any) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                for key in tuple(properties):
                    item = properties[key]
                    if isinstance(item, dict) and item.pop("x-internal", False):
                        properties.pop(key)
                required = value.get("required")
                if isinstance(required, list):
                    value["required"] = [key for key in required if key in properties]
            definitions = value.get("$defs")
            if isinstance(definitions, dict):
                for name in _INTERNAL_SCHEMA_TYPES:
                    definitions.pop(name, None)
            for item in value.values():
                clean(item)
        elif isinstance(value, list):
            for item in value:
                clean(item)

    clean(schema)
    return schema


def manifest_schemas() -> dict[str, dict[str, Any]]:
    """Schemas for every file a project author writes by hand.

    Returns:
        Schemas keyed by file name, such as ``task.yaml``.
    """
    from pydantic import TypeAdapter

    from plural.agents import Agent
    from plural.project.manifests import (
        BenchmarkManifest,
        EnvironmentManifest,
        HarnessManifest,
        ProjectManifest,
        TaskManifest,
    )
    from plural.verifiers import VerifierDefinition

    return {
        "project.yaml": public_schema(ProjectManifest),
        "environment.yaml": public_schema(EnvironmentManifest),
        "task.yaml": public_schema(TaskManifest),
        "verifier.yaml": TypeAdapter(VerifierDefinition).json_schema(),
        "harness.yaml": public_schema(HarnessManifest),
        "agent.yaml": public_schema(Agent),
        "benchmark.yaml": public_schema(BenchmarkManifest),
    }


__all__ = ["manifest_schemas", "public_schema"]
