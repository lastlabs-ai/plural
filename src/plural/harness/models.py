"""Class-based public Harness authoring interface."""

from __future__ import annotations

import inspect
import json
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from plural.common import (
    FileDeclaration,
    HarnessCapability,
    HarnessDefinition,
    HarnessPackage,
    PackageSource,
    semantic_version,
)
from plural.harness.interface import (
    HarnessAgent,
    HarnessEnvironment,
    HarnessResult,
    HarnessTask,
)


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
        ]
        if type(self).supports_tito:
            artifacts.append(
                FileDeclaration(
                    path="tito.jsonl",
                    required=False,
                    media_type="application/jsonl",
                )
            )
        definition = HarnessDefinition(
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
    "HarnessEnvironment",
    "HarnessResult",
    "HarnessTask",
    "LockedHarness",
]
