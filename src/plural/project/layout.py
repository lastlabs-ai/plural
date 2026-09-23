"""Where a project lives on disk and where each resource kind is stored.

A project is the nearest directory at or above the working directory that
contains ``project.yaml``. Every resource is a directory named after the
resource, under its kind's collection directory, holding one canonical
manifest::

    project.yaml  plural.lock  pyproject.toml  README.md  .plural/
    environments/<name>/environment.yaml
    tasks/<name>/task.yaml
    verifiers/<name>/verifier.yaml
    harnesses/<name>/harness.yaml
    agents/<name>/agent.yaml
    benchmarks/<name>/benchmark.yaml
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from plural.project.manifests import (
    LockFile,
    ProjectBinding,
    ProjectManifest,
    read_yaml_mapping,
    validation_problems,
)

PROJECT_FILE = "project.yaml"
LOCK_FILE = "plural.lock"
STATE_DIR = ".plural"
BINDING_FILE = "project.json"
NAME_PATTERN = re.compile(r"^(?=.{1,63}$)[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProjectError(Exception):
    """A project, resource, or command precondition that the user must fix.

    ``problems`` lists every independent issue so one run reports all of them.
    """

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.problems = list(problems or [])

    def __str__(self) -> str:
        if not self.problems:
            return self.message
        return self.message + "\n" + "\n".join(f"  - {item}" for item in self.problems)


@dataclass(frozen=True)
class ResourceKind:
    """One resource kind: its CLI noun, directory, manifest, and hosted collection."""

    name: str
    cli: str
    directory: str
    manifest: str
    label: str

    @property
    def collection(self) -> str:
        """Hosted API collection, which matches the local directory name."""
        return self.directory

    @property
    def plural_label(self) -> str:
        """``Harnesses``, ``Tasks``: the label for more than one."""
        return self.label + ("es" if self.label.endswith("s") else "s")


ENVIRONMENT = ResourceKind("environment", "env", "environments", "environment.yaml", "Environment")
VERIFIER = ResourceKind("verifier", "verifier", "verifiers", "verifier.yaml", "Verifier")
HARNESS = ResourceKind("harness", "harness", "harnesses", "harness.yaml", "Harness")
TASK = ResourceKind("task", "task", "tasks", "task.yaml", "Task")
AGENT = ResourceKind("agent", "agent", "agents", "agent.yaml", "Agent")
BENCHMARK = ResourceKind("benchmark", "benchmark", "benchmarks", "benchmark.yaml", "Benchmark")

KINDS: tuple[ResourceKind, ...] = (ENVIRONMENT, VERIFIER, HARNESS, TASK, AGENT, BENCHMARK)
_BY_NAME = {kind.name: kind for kind in KINDS} | {kind.cli: kind for kind in KINDS}


def resource_kind(name: str) -> ResourceKind:
    """Return a kind by its name (``environment``) or CLI noun (``env``).

    Raises:
        ValueError: When the name is not a resource kind.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown resource kind {name!r}") from None


@dataclass(frozen=True, order=True)
class ResourceRef:
    """A resource named within one project, such as ``task/refund``."""

    kind: str
    name: str

    @property
    def info(self) -> ResourceKind:
        """The kind's layout details."""
        return resource_kind(self.kind)

    def __str__(self) -> str:
        return f"{self.kind}/{self.name}"

    @classmethod
    def parse(cls, value: str) -> ResourceRef:
        """Parse ``kind/name``.

        Returns:
            The reference.
        """
        kind, _, name = value.partition("/")
        return cls(resource_kind(kind).name, name)


def check_name(name: str, what: str) -> str:
    """Validate a project or resource name.

    A valid name is already a hosted slug, so a local directory and its hosted
    resource are the same string on every filesystem.

    Returns:
        The name, unchanged.

    Raises:
        ProjectError: When the name cannot be used as a directory and slug.
    """
    if NAME_PATTERN.fullmatch(name):
        return name
    raise ProjectError(
        f"{what} name {name!r} is not valid.\n"
        "Use 1-63 lowercase letters and digits, separated by single hyphens. "
        "Example: support-refunds"
    )


def find_project_root(start: Path | None = None) -> Path | None:
    """Return the nearest directory at or above ``start`` holding ``project.yaml``."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_FILE).is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Project:
    """A project directory and its identity."""

    root: Path
    manifest: ProjectManifest

    @classmethod
    def find(cls, start: Path | None = None) -> Project:
        """Load the project containing ``start`` (default: the working directory).

        Returns:
            The project.

        Raises:
            ProjectError: When no enclosing directory holds ``project.yaml``.
        """
        root = find_project_root(start)
        if root is None:
            where = (start or Path.cwd()).resolve()
            raise ProjectError(
                f"{where} is not inside a Plural project.\n"
                "Run this command inside a project directory, or create one with "
                "`plural project init <project-name>`."
            )
        return cls.at(root)

    @classmethod
    def at(cls, root: Path) -> Project:
        """Load the project whose ``project.yaml`` is directly in ``root``.

        Returns:
            The project.

        Raises:
            ProjectError: When ``project.yaml`` is missing or invalid.
        """
        path = root / PROJECT_FILE
        try:
            payload = read_yaml_mapping(path)
        except FileNotFoundError:
            raise ProjectError(f"{root} has no {PROJECT_FILE}") from None
        except ValueError as exc:
            raise ProjectError(str(exc)) from None
        try:
            manifest = ProjectManifest.model_validate(payload)
        except ValidationError as exc:
            raise ProjectError(f"{path} is invalid", validation_problems(exc)) from None
        return cls(root=root.resolve(), manifest=manifest)

    @property
    def name(self) -> str:
        """Project name from ``project.yaml``."""
        return self.manifest.name

    def resource_dir(self, ref: ResourceRef) -> Path:
        """Directory that holds one resource.

        Returns:
            The resource directory, whether or not it exists.
        """
        return self.root / ref.info.directory / ref.name

    def manifest_path(self, ref: ResourceRef) -> Path:
        """Canonical manifest path for one resource.

        Returns:
            The manifest path, whether or not it exists.
        """
        return self.resource_dir(ref) / ref.info.manifest

    def has(self, ref: ResourceRef) -> bool:
        """Whether the resource directory exists locally.

        Returns:
            ``True`` when the directory exists.
        """
        return self.resource_dir(ref).is_dir()

    def names(self, kind: ResourceKind) -> list[str]:
        """Local resource names of one kind, sorted.

        Returns:
            The names.
        """
        directory = self.root / kind.directory
        if not directory.is_dir():
            return []
        return sorted(
            path.name
            for path in directory.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )

    def resource_at(self, path: Path) -> ResourceRef | None:
        """The resource whose directory contains ``path``, if any.

        Returns:
            The resource, or ``None`` outside any resource directory.
        """
        try:
            parts = path.resolve().relative_to(self.root).parts
        except ValueError:
            return None
        if len(parts) < 2:
            return None
        for kind in KINDS:
            if parts[0] == kind.directory:
                return ResourceRef(kind.name, parts[1])
        return None

    @property
    def state_dir(self) -> Path:
        """Ignored per-checkout state: binding, caches, and run records."""
        return self.root / STATE_DIR

    @property
    def jobs_dir(self) -> Path:
        """Local Job records."""
        return self.state_dir / "jobs"

    @property
    def lock_path(self) -> Path:
        """``plural.lock`` path."""
        return self.root / LOCK_FILE

    def read_lock(self) -> LockFile:
        """Return ``plural.lock``, or an empty lock when none exists yet.

        Raises:
            ProjectError: When the lock exists but is invalid.
        """
        if not self.lock_path.is_file():
            return LockFile()
        try:
            return LockFile.model_validate(read_yaml_mapping(self.lock_path))
        except (ValueError, ValidationError) as exc:
            raise ProjectError(
                f"{self.lock_path} is invalid. Restore it from version control or delete it "
                f"and push again.\n{exc}"
            ) from None

    def write_lock(self, lock: LockFile) -> None:
        """Write ``plural.lock`` with resources in a stable order."""
        from plural.project.manifests import write_yaml

        ordered = lock.model_copy(update={"resources": dict(sorted(lock.resources.items()))})
        write_yaml(
            self.lock_path,
            ordered.model_dump(mode="json", exclude_none=True),
            header="# Generated by Plural. Commit this file; do not edit it by hand.\n",
        )

    @property
    def binding_path(self) -> Path:
        """``.plural/project.json`` path."""
        return self.state_dir / BINDING_FILE

    def read_binding(self) -> ProjectBinding | None:
        """Return the hosted project this checkout is bound to, if any.

        Raises:
            ProjectError: When the binding file is unreadable.
        """
        if not self.binding_path.is_file():
            return None
        try:
            return ProjectBinding.model_validate_json(self.binding_path.read_text("utf-8"))
        except (OSError, ValidationError) as exc:
            raise ProjectError(
                f"{self.binding_path} is invalid. Run `plural project init {self.name} --push` "
                f"to bind this directory again.\n{exc}"
            ) from None

    def write_binding(self, binding: ProjectBinding) -> None:
        """Bind this checkout to a hosted project."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        ignore = self.state_dir / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
        self.binding_path.write_text(
            json.dumps(binding.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


__all__ = [
    "AGENT",
    "BENCHMARK",
    "ENVIRONMENT",
    "HARNESS",
    "KINDS",
    "LOCK_FILE",
    "PROJECT_FILE",
    "STATE_DIR",
    "TASK",
    "VERIFIER",
    "Project",
    "ProjectError",
    "ResourceKind",
    "ResourceRef",
    "check_name",
    "find_project_root",
    "resource_kind",
]
