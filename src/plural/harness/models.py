"""Public Harness authoring interfaces: the declared schema and the base class."""

from __future__ import annotations

import inspect
import json
import shlex
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from plural.common import (
    FileDeclaration,
    FrozenModel,
    HarnessCapability,
    HarnessPackage,
    HarnessProtocol,
    PackageSource,
    semantic_version,
)
from plural.harness.interface import (
    HarnessAgent,
    HarnessEnvironment,
    HarnessResult,
    HarnessTask,
)

PLURAL_PACKAGE_PREFIX = "plural-package:"


class HarnessDefinition(FrozenModel):
    """A declared executable Agent interaction strategy.

    Point ``source`` at a local directory or a remote archive and name the
    ``command`` that runs the loop. Subclass :class:`Harness` instead to write
    one in Python.
    """

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
    outputs: tuple[FileDeclaration, ...] = ()
    artifacts: tuple[FileDeclaration, ...] = ()
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
    def _valid_harness(self) -> HarnessDefinition:
        semantic_version(self.version)
        if self.source.startswith(PLURAL_PACKAGE_PREFIX):
            if self.digest is None:
                raise ValueError("A Plural package Harness source requires its tree digest")
        elif "://" not in self.source:
            from plural.harness.retrieval import tree_digest

            root = Path(self.source).expanduser().resolve()
            if not root.is_dir():
                raise ValueError(f"Harness source directory does not exist: {root}")
            object.__setattr__(self, "source", str(root))
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
        return HarnessPackage(definition=self._protocol(), source=self._source())

    def _protocol(self) -> HarnessProtocol:
        return HarnessProtocol(
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
            outputs=self.outputs,
            artifacts=self.artifacts,
            trajectory_path=self.trajectory,
            supports_tito=self.tito is not None,
            tito_path=self.tito,
        )

    @classmethod
    def from_package(
        cls, package: HarnessPackage, *, source: str | None = None
    ) -> HarnessDefinition:
        """Flatten an executable package into the public declared schema.

        Args:
            package: The package to describe.
            source: Replacement source location, such as the Plural package a
                pushed Harness is stored in. Defaults to the package's own.

        Returns:
            The equivalent declared Harness.
        """
        protocol = package.definition
        return cls(
            name=protocol.name,
            version=protocol.revision,
            description=protocol.description,
            command=protocol.command,
            source=source or package.source.uri,
            digest=package.source.digest,
            requirements=protocol.requirements,
            capabilities=protocol.capabilities,
            models=protocol.supported_models,
            auth=protocol.auth_modes,
            secrets=protocol.secret_names,
            environment=protocol.environment_names,
            healthcheck=protocol.healthcheck,
            outputs=protocol.outputs,
            artifacts=protocol.artifacts,
            trajectory=protocol.trajectory_path,
            tito=protocol.tito_path,
        )

    def _source(self) -> PackageSource:
        if self.source.startswith(PLURAL_PACKAGE_PREFIX):
            return PackageSource(kind="package", uri=self.source, digest=self.digest)
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
        return PackageSource(kind="local", uri=str(root), digest=self.digest, trusted=True)


class Harness(BaseModel, ABC):
    """Base class for an Agent interaction loop.

    Subclasses implement :meth:`run`. Plural discovers and hashes the Python
    class directory, invokes ``run`` in the Environment Runtime, and emits the
    standard result, trajectory, and log artifacts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: ClassVar[str] = "harness"
    version: ClassVar[str] = "0.1.0"
    description: ClassVar[str] = ""
    requirements: ClassVar[tuple[str, ...]] = ()
    capabilities: ClassVar[frozenset[HarnessCapability]] = frozenset()
    models: ClassVar[tuple[str, ...]] = ("*",)
    auth: ClassVar[tuple[Literal["environment", "api_key", "oauth", "none"], ...]] = (
        "environment",
    )
    secrets: ClassVar[tuple[str, ...]] = ()
    environment: ClassVar[tuple[str, ...]] = ()
    supports_tito: ClassVar[bool] = False
    _bound_python_source: ClassVar[Path | None] = None
    _bound_python_object: ClassVar[str | None] = None

    config: dict[str, Any] = Field(default_factory=dict)

    _package_root: Path | None = PrivateAttr(default=None)
    _python_source: Path | None = PrivateAttr(default=None)
    _python_object: str | None = PrivateAttr(default=None)
    _runner_ref: str | None = PrivateAttr(default=None)

    def model_post_init(self, context: Any, /) -> None:
        """Bind the subclass source immediately after validation."""
        del context
        semantic_version(type(self).version)
        if type(self) is not Harness:
            self._bind_source()

    @abstractmethod
    def run(
        self,
        task: HarnessTask,
        agent: HarnessAgent,
        environment: HarnessEnvironment,
    ) -> HarnessResult | str | dict[str, Any] | Any:
        """Run one Agent against one Task and Environment."""

    def _class_source_file(self) -> Path | None:
        marked = self._python_source or type(self)._bound_python_source
        if marked:
            return Path(marked).expanduser().resolve()
        module = sys.modules.get(type(self).__module__)
        filename = getattr(module, "__file__", None) if module is not None else None
        if filename:
            return Path(filename).resolve()
        try:
            source = inspect.getsourcefile(type(self))
        except TypeError:
            source = None
        return Path(source).resolve() if source else None

    def _bind_source(self, source: str | Path | None = None) -> None:
        """Hash the class directory and derive its sandbox runner reference."""
        class_file = self._class_source_file()
        if source is None:
            if class_file is None:
                raise ValueError(
                    f"Cannot create Harness {type(self).name!r}.\n"
                    "Plural could not find the file that defines this class.\n"
                    "Define the Harness subclass in a .py file."
                )
            root = class_file.parent
        else:
            requested = Path(source).expanduser().resolve()
            root = requested.parent if requested.is_file() else requested
        if class_file is None:
            class_file = root
        self._package_root = root
        self._python_source = class_file if class_file.is_file() else None
        self._python_object = (
            self._python_object or type(self)._bound_python_object or type(self).__qualname__
        )
        if self._python_source is None:
            raise ValueError(f"Harness {type(self).name!r} must be defined in a .py file")
        try:
            relative = self._python_source.relative_to(root).as_posix()
        except ValueError:
            relative = self._python_source.name
        self._runner_ref = f"{relative}:{self._python_object}"

    @property
    def content_hash(self) -> str:
        """Return the class source and configuration hash."""
        return self._package().content_hash

    def _package(self) -> HarnessPackage:
        if self._package_root is None or self._runner_ref is None:
            self._bind_source()
        assert self._package_root is not None
        assert self._runner_ref is not None
        from plural.harness.retrieval import tree_digest

        digest = tree_digest(self._package_root)
        artifacts = [
            FileDeclaration(
                path="trajectory.jsonl",
                required=False,
                media_type="application/jsonl",
            ),
            FileDeclaration(path="logs.txt", required=False, media_type="text/plain"),
            FileDeclaration(
                path="episode.jsonl",
                required=False,
                media_type="application/jsonl; profile=plural.episode/v1",
            ),
        ]
        if type(self).supports_tito:
            artifacts.append(
                FileDeclaration(
                    path="tito.jsonl",
                    required=False,
                    media_type="application/jsonl",
                )
            )
        definition = HarnessProtocol(
            name=type(self).name,
            revision=type(self).version,
            description=type(self).description,
            implementation="runnable",
            command=(
                "python",
                "-m",
                "plural.harness.class_runner",
                self._runner_ref,
                json.dumps(self.config, sort_keys=True, separators=(",", ":")),
            ),
            requirements=tuple(type(self).requirements),
            capabilities=frozenset(type(self).capabilities),
            supported_models=tuple(type(self).models),
            auth_modes=tuple(type(self).auth),
            secret_names=tuple(type(self).secrets),
            environment_names=tuple(type(self).environment),
            outputs=(FileDeclaration(path="result.json", media_type="application/json"),),
            artifacts=tuple(artifacts),
            trajectory_path="trajectory.jsonl",
            supports_tito=type(self).supports_tito,
            tito_path="tito.jsonl" if type(self).supports_tito else None,
        )
        source = PackageSource(
            kind="local", uri=str(self._package_root), digest=digest, trusted=True
        )
        return HarnessPackage(definition=definition, source=source)


class LockedHarness(Harness):
    """Internal adapter for a verified immutable Harness archive."""

    _locked_package: HarnessPackage = PrivateAttr()

    def model_post_init(self, context: Any, /) -> None:
        del context

    def run(
        self,
        task: HarnessTask,
        agent: HarnessAgent,
        environment: HarnessEnvironment,
    ) -> HarnessResult:
        del task, agent, environment
        raise RuntimeError("LockedHarness runs only from its archived package")

    def _package(self) -> HarnessPackage:
        return self._locked_package

    @classmethod
    def from_package(cls, package: HarnessPackage) -> LockedHarness:
        """Wrap a verified package for Agent compilation."""
        value = cls.model_construct(config={})
        value._locked_package = package
        return value


__all__ = [
    "Harness",
    "HarnessAgent",
    "HarnessDefinition",
    "HarnessEnvironment",
    "HarnessResult",
    "HarnessTask",
    "LockedHarness",
]
