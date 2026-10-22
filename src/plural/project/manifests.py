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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from plural.environments.definition import (
    EnvironmentResource,
    ExecutionLimits,
    Guardrail,
    HarnessPolicy,
    Party,
)
from plural.tasks import BenchmarkRelease, without_reset_options

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


class AppManifest(ManifestModel):
    """One entry of ``apps`` in ``environment.yaml``.

    Give exactly one of:

    - ``python``: an App class, ``apps/crm.py:CRM``, built with ``config``.
    - ``mcp``: the settings of :meth:`plural.App.mcp`, such as ``server``,
      ``command``, or ``url``, ``headers``, ``tools``, ``reset``, and ``credentials``.
    - ``openapi`` or ``replay``: the settings of the matching
      :class:`plural.App` factory.
    """

    name: str | None = None
    python: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    mcp: dict[str, Any] | None = None
    openapi: dict[str, Any] | None = None
    replay: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> AppManifest:
        given = [key for key in ("python", "mcp", "openapi", "replay") if getattr(self, key)]
        if len(given) != 1:
            raise ValueError(
                "an App needs exactly one of python, mcp, openapi, or replay"
                + (f"; got {', '.join(given)}" if given else "")
            )
        if not self.python and not self.name:
            raise ValueError(f"a {given[0]} App needs a name")
        if self.config and not self.python:
            raise ValueError("config applies to a python App; put settings under its kind")
        return self

    @property
    def kind(self) -> str:
        """Which source builds this App."""
        return next(key for key in ("python", "mcp", "openapi", "replay") if getattr(self, key))


class EnvironmentManifest(ManifestModel):
    """``environment.yaml``: identity, Apps, resources, runtime, and settings.

    ``python`` names either an App class, for an Environment of one Python App,
    or an Environment subclass whose hooks, such as ``on_step``, span the Apps
    listed in ``apps``. ``runtime`` takes the keyword arguments of the matching
    ``Runtime`` preset (``Runtime.docker()``, ``Runtime.local()``, or
    ``Runtime.daytona()``), selected by its ``provider``, or another catalog
    provider's settings. ``ref`` records the project Runtime the settings were
    copied from by `plural runtime use`.
    """

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    overview: str = ""
    python: str | None = None
    apps: list[AppManifest] = Field(default_factory=list)
    readme: str | None = "README.md"
    resources: list[str | EnvironmentResource] = Field(default_factory=list)
    runtime: dict[str, Any] = Field(default_factory=lambda: {"provider": "docker"})
    harness_policy: HarnessPolicy = Field(default_factory=HarnessPolicy)
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    party: Party | None = Field(
        default=None,
        description=(
            "How many Agents share each episode, such as {min: 2, max: 8} for poker, or one "
            "number for an exact size. Leave it out for an Environment one Agent works alone."
        ),
    )
    guardrails: list[Guardrail] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _moved_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            if "secrets" in value:
                raise ValueError(
                    "secrets moved onto Apps: list each secret under the App that uses it, "
                    "such as apps: [{name: crm, mcp: {url: ..., secrets: [CRM_TOKEN]}}], "
                    "or as App.secrets on a Python App"
                )
            if "reset_command" in value:
                raise ValueError(
                    "reset_command moved onto Apps: give an MCP App a reset command, or "
                    "override App.reset() in Python"
                )
        return value

    @model_validator(mode="after")
    def _has_apps(self) -> EnvironmentManifest:
        if not self.python and not self.apps:
            raise ValueError("an Environment needs Apps: set python to an App class, or list apps")
        return self


class TaskManifest(ManifestModel):
    """``task.yaml``: instructions, one Environment, and its Verifiers."""

    name: str = Field(min_length=1)
    title: str | None = Field(
        default=None,
        min_length=1,
        description="Display name in the hosted project. Defaults to name.",
    )
    version: str = "0.1.0"
    instructions: str = "instruction.md"
    environment: str = Field(min_length=1)
    verifiers: list[str] = Field(min_length=1)
    resources: list[str] = Field(default_factory=lambda: ["resources"])
    goals: list[str] = Field(default_factory=list)
    info: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    initial_state: dict[str, Any] = Field(default_factory=dict)
    seat_instructions: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "For an Environment with a party: what one seat alone is told after the Task's "
            "instructions, keyed seat_1, seat_2, and so on."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _removed_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return without_reset_options(dict(value), value.get("name"))


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
    title: str | None = Field(
        default=None,
        min_length=1,
        description="Display name in the hosted project. Defaults to name.",
    )
    version: str = "0.1.0"
    description: str = ""
    tasks: list[str] = Field(default_factory=list)
    primary_metric: Literal["score"] = "score"
    metadata: dict[str, Any] = Field(default_factory=dict)


class LockEntry(ManifestModel):
    """One resolved resource: its local identity and, once pushed, its revision."""

    version: str | None = None
    number: int | None = None
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
