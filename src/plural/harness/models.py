"""Plain public Harness authoring model."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from plural.common import (
    FileDeclaration,
    FrozenModel,
    HarnessCapability,
    HarnessDefinition,
    HarnessPackage,
    PackageSource,
    semantic_version,
)


class HarnessOutput(FrozenModel):
    """One file produced by a Harness."""

    path: str = Field(min_length=1)
    required: bool = True
    media_type: str = "application/octet-stream"


class Harness(FrozenModel):
    """An executable Agent interaction strategy."""

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    command: tuple[str, ...] = Field(min_length=1)
    source: str = "."
    digest: str | None = None
    requirements: tuple[str, ...] = ()
    capabilities: frozenset[HarnessCapability] = frozenset()
    models: tuple[str, ...] = ("*",)
    auth: tuple[Literal["environment", "api_key", "oauth", "none"], ...] = ("environment",)
    secrets: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()
    healthcheck: tuple[str, ...] | None = None
    outputs: tuple[HarnessOutput, ...] = ()
    artifacts: tuple[HarnessOutput, ...] = ()
    trajectory: str | None = None
    tito: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _ergonomic_values(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        command = payload.get("command")
        if isinstance(command, str):
            payload["command"] = tuple(shlex.split(command))
        for key in ("outputs", "artifacts"):
            items = payload.get(key)
            if isinstance(items, (list, tuple)):
                payload[key] = tuple(
                    {"path": item} if isinstance(item, str) else item for item in items
                )
        return payload

    @field_validator(
        "command",
        "requirements",
        "models",
        "secrets",
        "environment",
        "healthcheck",
    )
    @classmethod
    def _nonempty_items(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("items must be non-empty strings")
        return value

    @model_validator(mode="after")
    def _valid_harness(self) -> Harness:
        semantic_version(self.version)
        if "://" not in self.source:
            from plural.harness.retrieval import tree_digest

            root = Path(self.source).expanduser().resolve()
            if not root.is_dir():
                raise ValueError(f"Harness source directory does not exist: {root}")
            object.__setattr__(
                self,
                "source",
                str(root),
            )
            if self.digest is None:
                object.__setattr__(self, "digest", tree_digest(root))
        artifact_paths = {item.path for item in self.artifacts}
        if self.trajectory is not None and self.trajectory not in artifact_paths:
            raise ValueError("trajectory must name a declared artifact")
        if self.tito is not None and self.tito not in artifact_paths:
            raise ValueError("tito must name a declared artifact")
        for label, values in (("output", self.outputs), ("artifact", self.artifacts)):
            paths = [item.path for item in values]
            if len(paths) != len(set(paths)):
                raise ValueError(f"{label} paths must be unique")
        return self

    @property
    def content_hash(self) -> str:
        """Return the locked executable content hash."""
        return self._package().content_hash

    def _package(self) -> HarnessPackage:
        definition = HarnessDefinition(
            name=self.name,
            revision=self.version,
            description=self.description,
            implementation="runnable",
            command=self.command,
            requirements=self.requirements,
            capabilities=self.capabilities,
            supported_models=self.models,
            auth_modes=self.auth,
            secret_names=self.secrets,
            environment_names=self.environment,
            healthcheck=self.healthcheck,
            outputs=tuple(FileDeclaration(**item.model_dump()) for item in self.outputs),
            artifacts=tuple(FileDeclaration(**item.model_dump()) for item in self.artifacts),
            trajectory_path=self.trajectory,
            supports_tito=self.tito is not None,
            tito_path=self.tito,
        )
        return HarnessPackage(definition=definition, source=self._source())

    def _source(self) -> PackageSource:
        if self.source.startswith("oci://"):
            if self.digest is None:
                raise ValueError("OCI Harness sources require a digest")
            return PackageSource(kind="oci", uri=self.source, digest=self.digest)
        if "://" in self.source:
            if self.digest is None:
                raise ValueError("remote Harness sources require a digest")
            return PackageSource(kind="archive", uri=self.source, digest=self.digest)
        root = Path(self.source).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Harness source directory does not exist: {root}")
        return PackageSource(
            kind="local",
            uri=str(root),
            digest=self.digest,
            trusted=True,
        )


__all__ = ["Harness", "HarnessOutput"]
