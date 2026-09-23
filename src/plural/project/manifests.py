"""Schemas for the files a Plural project keeps on disk.

Each resource kind has exactly one manifest format. A manifest field that means
the same thing as an SDK field uses the SDK type, so defaults and validation are
defined once. The only manifest-specific fields are references: other resources
by name, Python behavior as ``file.py:Object``, and files by a path relative to
the manifest.

Verifiers and Agents have no manifest model of their own: their manifests are
the public :mod:`plural.verifiers` and :class:`plural.Agent` fields, with a
Verifier ``check`` written as ``verify.py:function`` and an Agent ``harness``
written as a Harness name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from plural.environments.definition import (
    EnvironmentResource,
    ExecutionLimits,
    Guardrail,
    HarnessPolicy,
    SecretReference,
)
from plural.tasks import BenchmarkRelease

PROJECT_SCHEMA_VERSION: Literal[1] = 1
LOCK_VERSION: Literal[1] = 1


class ManifestModel(BaseModel):
    """Strict base: unknown keys are errors, never silently ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ProjectManifest(ManifestModel):
    """``project.yaml``: project identity and the layout version it follows."""

    schema_version: Literal[1] = PROJECT_SCHEMA_VERSION
    name: str = Field(min_length=1)
    description: str = ""


class EnvironmentManifest(ManifestModel):
    """``environment.yaml``: identity, resources, runtime, and settings.

    Actions, State, Observations, and rewards are Python behavior in the class
    named by ``python``. ``runtime`` takes the keyword arguments of the matching
    ``Runtime`` preset (``Runtime.docker()``, ``Runtime.local()``, or
    ``Runtime.daytona()``), selected by its ``provider``.
    """

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    overview: str = ""
    python: str = Field(min_length=1)
    readme: str | None = "README.md"
    resources: list[str | EnvironmentResource] = Field(default_factory=list)
    runtime: dict[str, Any] = Field(default_factory=lambda: {"provider": "docker"})
    harness_policy: HarnessPolicy = Field(default_factory=HarnessPolicy)
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    secrets: list[SecretReference] = Field(default_factory=list)
    guardrails: list[Guardrail] = Field(default_factory=list)
    reset_command: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskManifest(ManifestModel):
    """``task.yaml``: instructions, one Environment, and its Verifiers."""

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    instructions: str = "instruction.md"
    environment: str = Field(min_length=1)
    verifiers: list[str] = Field(min_length=1)
    resources: list[str] = Field(default_factory=lambda: ["resources"])
    goals: list[str] = Field(default_factory=list)
    info: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    initial_state: dict[str, Any] = Field(default_factory=dict)
    reset_options: dict[str, Any] = Field(default_factory=dict)


class HarnessManifest(ManifestModel):
    """``harness.yaml``: identity and configuration for one Harness subclass.

    The class holds the interaction loop. Its identity comes from this file, so
    the class does not repeat ``name`` or ``version``.
    """

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    python: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class BenchmarkManifest(BenchmarkRelease):
    """``benchmark.yaml``: Task references plus release and scoring rules.

    ``purpose`` is the Benchmark's motivation. It ranks on the Verifier-derived
    ``score`` only; step rewards never contribute.
    """

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    tasks: list[str] = Field(default_factory=list)
    primary_metric: Literal["score"] = "score"
    metadata: dict[str, Any] = Field(default_factory=dict)


class LockEntry(ManifestModel):
    """One resolved resource: its local identity and, once pushed, its revision."""

    version: str
    content_hash: str
    package_digest: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    resource_id: str | None = None
    revision_id: str | None = None


class LockFile(ManifestModel):
    """``plural.lock``: resolved dependency revisions and content hashes.

    Hosted identifiers belong to ``project_id``. Entries recorded for another
    hosted project are never used as dependency pins.
    """

    lock_version: Literal[1] = LOCK_VERSION
    project_id: str | None = None
    resources: dict[str, LockEntry] = Field(default_factory=dict)


class ProjectBinding(ManifestModel):
    """``.plural/project.json``: the hosted project this checkout pushes to."""

    api_url: str
    account_id: str | None = None
    project_id: str
    project_slug: str
    project_name: str = ""


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read one YAML file that must contain a mapping.

    Returns:
        The parsed mapping.

    Raises:
        ValueError: When the file is not valid YAML or not a mapping.
    """
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} is not valid YAML: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return dict(value)


def write_yaml(path: Path, payload: Any, *, header: str = "") -> None:
    """Write deterministic, human-editable YAML."""
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", exclude_defaults=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.write_text(header + text, encoding="utf-8")


def validation_problems(exc: ValidationError) -> list[str]:
    """Turn a Pydantic error into ``field: message`` lines a person can act on.

    Returns:
        One line per failed field.
    """
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "__root__")
        message = str(error.get("msg", "invalid value")).removeprefix("Value error, ")
        if error.get("type") == "missing":
            message = "is required"
        elif error.get("type") == "extra_forbidden":
            message = "is not a recognized field"
        problems.append(f"{location}: {message}" if location else message)
    return problems


__all__ = [
    "LOCK_VERSION",
    "PROJECT_SCHEMA_VERSION",
    "BenchmarkManifest",
    "EnvironmentManifest",
    "HarnessManifest",
    "LockEntry",
    "LockFile",
    "ManifestModel",
    "ProjectBinding",
    "ProjectManifest",
    "TaskManifest",
    "read_yaml_mapping",
    "validation_problems",
    "write_yaml",
]
