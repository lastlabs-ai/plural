"""Load, validate, and order the resources in one project.

A :class:`Workspace` loads a resource by name into the same SDK object a Python
author would build (an ``Environment``, ``Task``, ``Verifier``, ``Harness``,
``Agent``, or ``Benchmark``). Loading is validation: every problem found in a
resource is collected into one :class:`ProjectError`, so a person sees the full
list at once rather than fixing one error per run.

Dependencies are declared by name in manifests. They are resolved only against
this project's directories; a dependency that is not present locally is an
unresolved reference, never a silent lookup elsewhere.
"""

from __future__ import annotations

import importlib.util
import inspect
import mimetypes
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from plural.agents import Agent
from plural.catalog import ModelCatalog
from plural.environments import Environment
from plural.environments.definition import EnvironmentResource, EnvironmentRuntime
from plural.harness.models import Harness
from plural.harness.retrieval import tree_digest
from plural.project.layout import (
    AGENT,
    BENCHMARK,
    ENVIRONMENT,
    HARNESS,
    TASK,
    VERIFIER,
    Project,
    ProjectError,
    ResourceRef,
    resource_kind,
)
from plural.project.manifests import (
    BenchmarkManifest,
    EnvironmentManifest,
    HarnessManifest,
    TaskManifest,
    read_yaml_mapping,
    validation_problems,
)
from plural.tasks import RELEASE_FIELDS, Benchmark, Task
from plural.verifiers import (
    AgentVerifier,
    DeterministicVerifier,
    HumanVerifier,
    Verifier,
    VerifierDefinition,
)

SCAFFOLD_MARKER = "PLURAL-TODO"
_VERIFIER_ADAPTER: TypeAdapter[VerifierDefinition] = TypeAdapter(VerifierDefinition)
_IGNORED_PARTS = frozenset({".git", ".plural", "__pycache__", ".venv", "node_modules"})
_TEXT_SUFFIXES = frozenset({".py", ".md", ".yaml", ".yml", ".txt", ".json", ".toml"})


@dataclass(frozen=True)
class LocalResource:
    """One validated local resource and the SDK object it defines."""

    ref: ResourceRef
    directory: Path
    value: Any
    dependencies: tuple[ResourceRef, ...]

    @property
    def version(self) -> str:
        """Declared semantic version."""
        return str(self.value.version)

    @property
    def content_hash(self) -> str:
        """Canonical digest of the definition, including dependency digests."""
        return str(self.value.content_hash)


class Workspace:
    """Resolve resources by name inside one project, caching each load."""

    def __init__(self, project: Project, *, catalog: ModelCatalog | None = None) -> None:
        self.project = project
        self.catalog = catalog or ModelCatalog()
        self._loaded: dict[ResourceRef, LocalResource] = {}
        self._loading: list[ResourceRef] = []

    def load(self, ref: ResourceRef) -> LocalResource:
        """Load and fully validate one resource and its dependencies.

        Returns:
            The validated resource.

        Raises:
            ProjectError: Listing every problem found.
        """
        if ref in self._loaded:
            return self._loaded[ref]
        if ref in self._loading:
            cycle = " -> ".join(str(item) for item in [*self._loading, ref])
            raise ProjectError(f"Dependency cycle: {cycle}")
        directory = self.project.resource_dir(ref)
        manifest = directory / ref.info.manifest
        if not manifest.is_file():
            raise ProjectError(_missing_message(self.project, ref))
        self._loading.append(ref)
        try:
            resource = _LOADERS[ref.kind](self, ref, directory)
        finally:
            self._loading.pop()
        self._loaded[ref] = resource
        return resource

    def get(self, kind: str, name: str) -> Any:
        """Load a resource by kind and name, the way the CLI addresses it.

        ``kind`` is a kind name or its CLI noun, so ``workspace.get("env",
        "support-queue")`` is the object ``plural env show support-queue``
        describes.

        Args:
            kind: ``environment``/``env``, ``task``, ``verifier``, ``harness``,
                ``agent``, or ``benchmark``.
            name: The resource's directory name.

        Returns:
            The validated SDK object, such as a ``Task`` or ``Benchmark``.

        Raises:
            ProjectError: When the resource is missing or invalid.

        Examples:
            >>> from plural.project import Project, Workspace
            >>> workspace = Workspace(Project.find())  # doctest: +SKIP
            >>> benchmark = workspace.get("benchmark", "support-triage")  # doctest: +SKIP
        """
        try:
            info = resource_kind(kind)
        except ValueError as exc:
            raise ProjectError(str(exc)) from None
        return self.load(ResourceRef(info.name, name)).value

    def dependencies(self, ref: ResourceRef) -> tuple[ResourceRef, ...]:
        """Direct dependencies declared in a manifest, without loading code.

        Returns:
            The declared dependencies.

        Raises:
            ProjectError: When the manifest cannot be read.
        """
        path = self.project.manifest_path(ref)
        if not path.is_file():
            raise ProjectError(_missing_message(self.project, ref))
        try:
            payload = read_yaml_mapping(path)
        except ValueError as exc:
            raise ProjectError(str(exc)) from None
        return declared_dependencies(ref.kind, payload)

    def dependency_order(self, roots: Iterable[ResourceRef]) -> list[ResourceRef]:
        """Return ``roots`` and everything they depend on, dependencies first.

        Unresolved references and cycles are reported before any code is
        imported or anything is uploaded.

        Raises:
            ProjectError: Listing unresolved references or the first cycle.
        """
        ordered: list[ResourceRef] = []
        done: set[ResourceRef] = set()
        missing: list[str] = []

        def visit(
            ref: ResourceRef, path: tuple[ResourceRef, ...], parent: ResourceRef | None
        ) -> None:
            if ref in done:
                return
            if ref in path:
                cycle = " -> ".join(str(item) for item in (*path[path.index(ref) :], ref))
                raise ProjectError(f"Dependency cycle: {cycle}")
            if not self.project.manifest_path(ref).is_file():
                where = f"{parent} references " if parent else ""
                missing.append(f"{where}{ref}, which is not in {ref.info.directory}/")
                done.add(ref)
                return
            for dependency in self.dependencies(ref):
                visit(dependency, (*path, ref), ref)
            done.add(ref)
            ordered.append(ref)

        for root in roots:
            visit(root, (), None)
        if missing:
            raise ProjectError(
                "Some dependencies are not in this project. Create them with "
                "`plural <kind> init <name>` or restore them with `plural <kind> pull <name>`.",
                missing,
            )
        return ordered


def declared_dependencies(kind: str, payload: Mapping[str, Any]) -> tuple[ResourceRef, ...]:
    """Resource references named by one raw manifest.

    Returns:
        Direct dependencies in manifest order.
    """
    refs: list[ResourceRef] = []
    if kind == TASK.name:
        if isinstance(payload.get("environment"), str):
            refs.append(ResourceRef(ENVIRONMENT.name, payload["environment"]))
        refs.extend(
            ResourceRef(VERIFIER.name, name)
            for name in payload.get("verifiers") or ()
            if isinstance(name, str)
        )
    elif kind == AGENT.name:
        harness = payload.get("harness")
        if isinstance(harness, str) and not _is_builtin_harness(harness):
            refs.append(ResourceRef(HARNESS.name, harness))
    elif kind == BENCHMARK.name:
        refs.extend(
            ResourceRef(TASK.name, name)
            for name in payload.get("tasks") or ()
            if isinstance(name, str)
        )
    return tuple(dict.fromkeys(refs))


def load_harness_directory(root: Path, *, name: str | None = None) -> Harness:
    """Load a Harness package directory that holds ``harness.yaml``.

    Returns:
        The configured Harness instance, bound to its source directory.

    Raises:
        ProjectError: When the package is invalid.
    """
    problems: list[str] = []
    harness = _build_harness(root, problems, expected_name=name)
    if harness is None or problems:
        raise ProjectError(f"Harness package {root} is not valid", problems)
    return harness


def scaffold_problems(directory: Path, project_root: Path) -> list[str]:
    """Report every unfinished ``PLURAL-TODO`` marker left by a template.

    Returns:
        One ``path:line: note`` entry per marker.
    """
    problems = []
    for path in sorted(_package_files(directory)):
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, start=1):
            if SCAFFOLD_MARKER in line:
                note = line.split(SCAFFOLD_MARKER, 1)[1].lstrip(":- ").strip(" #->")
                location = f"{_display(path, project_root)}:{number}"
                problems.append(f"{location}: unfinished scaffold: {note or 'replace this'}")
    return problems


def _load_environment(workspace: Workspace, ref: ResourceRef, directory: Path) -> LocalResource:
    problems, payload = _begin(workspace, ref, directory)
    manifest = _parse(EnvironmentManifest, payload, problems)
    environment: Environment[Any, Any] | None = None
    if manifest is not None:
        _check_identity(manifest.name, ref, problems)
        environment = _build_environment(manifest, directory, workspace.project.root, problems)
    return _finish(workspace, ref, directory, environment, (), problems)


def _build_environment(
    manifest: EnvironmentManifest, directory: Path, project_root: Path, problems: list[str]
) -> Environment[Any, Any] | None:
    readme = ""
    if manifest.readme:
        readme_path = _inside(directory, manifest.readme, "readme", problems)
        if readme_path is not None and readme_path.is_file():
            readme = readme_path.read_text(encoding="utf-8")
        elif readme_path is not None:
            problems.append(f"readme: {manifest.readme} does not exist")
    resources: list[EnvironmentResource] = []
    for index, item in enumerate(manifest.resources):
        resource = EnvironmentResource(item) if isinstance(item, str) else item
        if resource.path and resource.delivery == "source":
            target = _inside(directory, resource.path, f"resources.{index}", problems)
            if target is not None and not target.exists():
                problems.append(f"resources.{index}: {resource.path} does not exist")
        resources.append(resource)
    try:
        runtime = runtime_from_manifest(manifest.runtime)
    except (TypeError, ValueError) as exc:
        problems.append(f"runtime: {_first_line(exc)}")
        return None
    cls = _import_reference(directory, manifest.python, "python", problems)
    if cls is None:
        return None
    if not (inspect.isclass(cls) and issubclass(cls, Environment)):
        problems.append(f"python: {manifest.python} is not an Environment subclass")
        return None
    source, object_path = _split_reference(directory, manifest.python)
    cls._python_source = source
    cls._python_object = object_path
    try:
        environment = cls(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            overview=manifest.overview,
            readme=readme,
            resources=resources,
            runtime=runtime,
            secrets=manifest.secrets,
            guardrails=manifest.guardrails,
            harness_policy=manifest.harness_policy,
            limits=manifest.limits,
            metadata=manifest.metadata,
            reset_command=manifest.reset_command or None,
        )
        environment._bind_source(directory)
        if not type(environment)._actions():
            problems.append(
                f"{_display(source, project_root)}: {object_path} declares no actions. "
                "Add at least one method decorated with @action."
            )
        environment.definition()
    except (TypeError, ValueError) as exc:
        problems.append(f"{_display(source, project_root)}: {_first_line(exc)}")
        return None
    return environment


def runtime_from_manifest(spec: Mapping[str, Any]) -> EnvironmentRuntime:
    """Build a Runtime from its preset keyword arguments.

    ``provider`` selects ``Runtime.docker()``, ``Runtime.local()``, or
    ``Runtime.daytona()``, so a manifest states only what differs from the
    preset. Other providers take the full ``EnvironmentRuntime`` fields.

    Returns:
        The validated Runtime.
    """
    payload = dict(spec)
    provider = str(payload.pop("provider", "docker"))
    presets: dict[str, Callable[..., EnvironmentRuntime]] = {
        "docker": EnvironmentRuntime.docker,
        "local": EnvironmentRuntime.local,
        "daytona": EnvironmentRuntime.daytona,
    }
    if provider in presets and "targets" not in payload:
        return presets[provider](**payload)
    return EnvironmentRuntime.model_validate({"provider": provider, **payload})


def _load_verifier(workspace: Workspace, ref: ResourceRef, directory: Path) -> LocalResource:
    problems, payload = _begin(workspace, ref, directory)
    verifier = None
    if payload:
        _check_identity(str(payload.get("name") or ""), ref, problems)
        verifier = _build_verifier(payload, directory, workspace.catalog, problems)
    return _finish(workspace, ref, directory, verifier, (), problems)


def _build_verifier(
    payload: dict[str, Any], directory: Path, catalog: ModelCatalog, problems: list[str]
) -> Verifier | None:
    prepared = dict(payload)
    prepared.setdefault("kind", "deterministic")
    check = prepared.get("check")
    bound_check = False
    if isinstance(check, str) and _looks_like_reference(check):
        function = _import_reference(directory, check, "check", problems)
        if function is None:
            return None
        if not callable(function):
            problems.append(f"check: {check} is not a function")
            return None
        prepared["check"] = function
        bound_check = True
    try:
        verifier = _VERIFIER_ADAPTER.validate_python(prepared, context={"catalog": catalog})
    except ValidationError as exc:
        problems.extend(validation_problems(exc))
        return None
    if bound_check and isinstance(verifier, DeterministicVerifier):
        verifier.bind_source_digest(tree_digest(directory))
    return verifier


def _load_harness(workspace: Workspace, ref: ResourceRef, directory: Path) -> LocalResource:
    problems, payload = _begin(workspace, ref, directory)
    harness = None
    if _is_builtin_harness(ref.name):
        problems.append(
            f"{ref.name!r} is a built-in Harness. Use `harness: {ref.name}` in an agent.yaml "
            "directly, or give this Harness another name."
        )
    elif payload:
        harness = _build_harness(directory, problems, expected_name=ref.name, payload=payload)
    return _finish(workspace, ref, directory, harness, (), problems)


def _build_harness(
    directory: Path,
    problems: list[str],
    *,
    expected_name: str | None,
    payload: dict[str, Any] | None = None,
) -> Harness | None:
    if payload is None:
        try:
            payload = read_yaml_mapping(directory / HARNESS.manifest)
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
            return None
    manifest = _parse(HarnessManifest, payload, problems)
    if manifest is None:
        return None
    if expected_name is not None and manifest.name != expected_name:
        problems.append(f"name: {manifest.name!r} must match its directory name {expected_name!r}")
    cls = _import_reference(directory, manifest.python, "python", problems)
    if cls is None:
        return None
    if not (inspect.isclass(cls) and issubclass(cls, Harness)) or cls is Harness:
        problems.append(f"python: {manifest.python} is not a Harness subclass")
        return None
    source, object_path = _split_reference(directory, manifest.python)
    # Each load imports a fresh module, so identity set here belongs to this load only.
    cls.name = manifest.name
    cls.version = manifest.version
    cls.description = manifest.description
    cls._bound_python_source = source
    cls._bound_python_object = object_path
    try:
        harness = cls(config=manifest.config)
        harness._bind_source(directory)
        harness._package()
    except (TypeError, ValueError) as exc:
        problems.append(f"python: {_first_line(exc)}")
        return None
    return harness


def _load_task(workspace: Workspace, ref: ResourceRef, directory: Path) -> LocalResource:
    problems, payload = _begin(workspace, ref, directory)
    manifest = _parse(TaskManifest, payload, problems, hints=_TASK_HINTS)
    dependencies = declared_dependencies(TASK.name, payload)
    task = None
    if manifest is not None:
        _check_identity(manifest.name, ref, problems)
        instructions = _read_instructions(directory, manifest.instructions, problems)
        resources = _task_resources(directory, manifest.resources, problems)
        environment = _dependency(workspace, ResourceRef(ENVIRONMENT.name, manifest.environment))
        verifiers = [
            _dependency(workspace, ResourceRef(VERIFIER.name, name)) for name in manifest.verifiers
        ]
        for item in (environment, *verifiers):
            if isinstance(item, str):
                problems.append(item)
        if len(set(manifest.verifiers)) != len(manifest.verifiers):
            problems.append("verifiers: each Verifier may be listed once")
        if instructions and not problems:
            assert isinstance(environment, LocalResource)
            try:
                task = Task.model_validate(
                    {
                        "name": manifest.name,
                        "version": manifest.version,
                        "instructions": instructions,
                        "goals": manifest.goals,
                        "info": manifest.info,
                        "metadata": manifest.metadata,
                        "environment": environment.value,
                        "verifiers": tuple(
                            item.value for item in verifiers if isinstance(item, LocalResource)
                        ),
                        "resources": resources,
                        "initial_state": manifest.initial_state,
                        "reset_options": manifest.reset_options,
                    },
                    context={"catalog": workspace.catalog},
                )
                task.definition()
            except ValidationError as exc:
                problems.extend(validation_problems(exc))
            except (TypeError, ValueError) as exc:
                problems.append(_first_line(exc))
    return _finish(workspace, ref, directory, task, dependencies, problems)


_TASK_HINTS = {
    "environment": (
        "environment: is required. Name the one Environment this Task runs in, "
        "for example `environment: support-desk` (create one with `plural env init <name>`)"
    ),
    "verifiers": (
        "verifiers: needs at least one Verifier name, for example `verifiers: [resolved]`"
    ),
}


def _read_instructions(directory: Path, reference: str, problems: list[str]) -> str:
    path = _inside(directory, reference, "instructions", problems)
    if path is None:
        return ""
    if not path.is_file():
        problems.append(f"instructions: {reference} does not exist")
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        problems.append(f"instructions: {reference} must be UTF-8 text")
        return ""
    if not text.strip():
        problems.append(f"instructions: {reference} is empty. Write what the Agent must do.")
    return text


def _task_resources(
    directory: Path, entries: list[str], problems: list[str]
) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        target = _inside(directory, entry, f"resources.{index}", problems)
        if target is None:
            continue
        if not target.exists():
            if entry != "resources":
                problems.append(f"resources.{index}: {entry} does not exist")
            continue
        files = sorted(_package_files(target)) if target.is_dir() else [target]
        for source in files:
            relative = source.relative_to(directory).as_posix()
            try:
                content = source.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                problems.append(f"resources: {relative} must be UTF-8 text")
                continue
            content_type, _ = mimetypes.guess_type(source.name)
            resources.append(
                {
                    "kind": "file",
                    "name": relative,
                    "path": relative,
                    "content_type": content_type or "text/plain",
                    "delivery": "inline",
                    "content": content,
                }
            )
    return resources


def _load_agent(workspace: Workspace, ref: ResourceRef, directory: Path) -> LocalResource:
    problems, payload = _begin(workspace, ref, directory)
    dependencies = declared_dependencies(AGENT.name, payload)
    agent = None
    if payload:
        _check_identity(str(payload.get("name") or ""), ref, problems)
        prepared = dict(payload)
        harness = prepared.get("harness")
        if dependencies:
            loaded = _dependency(workspace, dependencies[0])
            if isinstance(loaded, str):
                problems.append(loaded)
            else:
                prepared["harness"] = loaded.value
        elif harness is not None and not isinstance(harness, str):
            problems.append("harness: must be a Harness name")
        if not problems:
            try:
                agent = Agent.model_validate(
                    prepared, context={"catalog": workspace.catalog, "root": directory}
                )
            except ValidationError as exc:
                problems.extend(validation_problems(exc))
    return _finish(workspace, ref, directory, agent, dependencies, problems)


def _load_benchmark(workspace: Workspace, ref: ResourceRef, directory: Path) -> LocalResource:
    problems, payload = _begin(workspace, ref, directory)
    manifest = _parse(BenchmarkManifest, payload, problems)
    dependencies = declared_dependencies(BENCHMARK.name, payload)
    benchmark = None
    if manifest is not None:
        _check_identity(manifest.name, ref, problems)
        if not (directory / "README.md").is_file():
            problems.append("README.md is missing. Explain what this Benchmark measures.")
        if not manifest.purpose.strip():
            problems.append("purpose: state the motivation: what this Benchmark measures and why")
        if not manifest.scoring.description.strip():
            problems.append(
                "scoring.description: describe what a score means, for example "
                "'Share of tickets resolved according to policy'"
            )
        if not manifest.tasks:
            problems.append(
                f"tasks: this Benchmark has no Tasks yet. Add one with "
                f"`plural benchmark add <task-name> --benchmark {ref.name}`"
            )
        if len(set(manifest.tasks)) != len(manifest.tasks):
            problems.append("tasks: each Task may be listed once")
        tasks = [_dependency(workspace, ResourceRef(TASK.name, name)) for name in manifest.tasks]
        problems.extend(item for item in tasks if isinstance(item, str))
        loaded = [item for item in tasks if isinstance(item, LocalResource)]
        problems.extend(_score_compatibility(manifest, loaded))
        if not problems:
            try:
                benchmark = Benchmark.model_validate(
                    {
                        "name": manifest.name,
                        "version": manifest.version,
                        "description": manifest.description,
                        "metadata": manifest.metadata,
                        "primary_metric": manifest.primary_metric,
                        "tasks": tuple(item.value for item in loaded),
                        **{field: getattr(manifest, field) for field in RELEASE_FIELDS},
                    }
                )
            except ValidationError as exc:
                problems.extend(validation_problems(exc))
    return _finish(workspace, ref, directory, benchmark, dependencies, problems)


def _score_compatibility(manifest: BenchmarkManifest, tasks: list[LocalResource]) -> list[str]:
    """Check that every Task's Verifiers can score inside the Benchmark range.

    A Benchmark ranks on the Verifier score. A rubric whose criteria can score
    outside ``scoring.score_range`` would produce scores the ranking cannot
    place, so it is rejected here rather than at result time.

    Returns:
        One problem per incompatible Verifier.
    """
    low, high = manifest.scoring.score_range
    problems = []
    for task in tasks:
        for verifier in task.value.verifiers:
            if not isinstance(verifier, (AgentVerifier, HumanVerifier)):
                continue
            for criterion in verifier.criteria:
                if criterion.min_score < low or criterion.max_score > high:
                    problems.append(
                        f"task {task.ref.name!r}: Verifier {verifier.name!r} criterion "
                        f"{criterion.name!r} scores {criterion.min_score}..{criterion.max_score}, "
                        f"outside scoring.score_range {low}..{high}"
                    )
    return problems


def _begin(
    workspace: Workspace, ref: ResourceRef, directory: Path
) -> tuple[list[str], dict[str, Any]]:
    problems = scaffold_problems(directory, workspace.project.root)
    try:
        payload = read_yaml_mapping(directory / ref.info.manifest)
    except ValueError as exc:
        problems.insert(0, str(exc))
        payload = {}
    return problems, payload


def _finish(
    workspace: Workspace,
    ref: ResourceRef,
    directory: Path,
    value: Any,
    dependencies: tuple[ResourceRef, ...],
    problems: list[str],
) -> LocalResource:
    if problems or value is None:
        manifest = _display(directory / ref.info.manifest, workspace.project.root)
        raise ProjectError(
            f"{ref.info.label} {ref.name!r} is not valid ({manifest}).",
            problems or ["the manifest is empty"],
        )
    return LocalResource(ref=ref, directory=directory, value=value, dependencies=dependencies)


def _dependency(workspace: Workspace, ref: ResourceRef) -> LocalResource | str:
    try:
        return workspace.load(ref)
    except ProjectError as exc:
        if not workspace.project.manifest_path(ref).is_file():
            return (
                f"{ref.kind} {ref.name!r} is not in {ref.info.directory}/. Create it with "
                f"`plural {ref.info.cli} init {ref.name}` or restore it with "
                f"`plural {ref.info.cli} pull {ref.name}`."
            )
        details = "; ".join(exc.problems) or exc.message
        return f"depends on {ref.kind} {ref.name!r}, which is not valid: {details}"


def _parse(
    model: type[Any],
    payload: dict[str, Any],
    problems: list[str],
    *,
    hints: Mapping[str, str] | None = None,
) -> Any:
    if not payload:
        return None
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        for error, line in zip(exc.errors(), validation_problems(exc), strict=True):
            field = str(error["loc"][0]) if error.get("loc") else ""
            problems.append((hints or {}).get(field, line))
        return None


def _check_identity(name: str, ref: ResourceRef, problems: list[str]) -> None:
    if name != ref.name:
        problems.append(f"name: {name!r} must match its directory name {ref.name!r}")


def _looks_like_reference(value: str) -> bool:
    path, separator, obj = value.rpartition(":")
    return bool(separator and obj and path.endswith(".py") and " " not in path)


def _split_reference(directory: Path, reference: str) -> tuple[Path, str]:
    path, _, obj = reference.rpartition(":")
    return (directory / path).resolve(), obj


def _import_reference(directory: Path, reference: str, field: str, problems: list[str]) -> Any:
    if not _looks_like_reference(reference):
        problems.append(f"{field}: {reference!r} must look like file.py:Name")
        return None
    path, _, obj = reference.rpartition(":")
    source = _inside(directory, path, field, problems)
    if source is None:
        return None
    if not source.is_file():
        problems.append(f"{field}: {path} does not exist")
        return None
    module_name = f"_plural_resource_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        problems.append(f"{field}: cannot import {path}")
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(source.parent))
    try:
        spec.loader.exec_module(module)
        value: Any = module
        for part in obj.split("."):
            value = getattr(value, part)
    except AttributeError:
        problems.append(f"{field}: {path} does not define {obj}")
        return None
    except Exception as exc:  # noqa: BLE001 - user code may raise anything on import
        problems.append(f"{field}: importing {path} failed: {type(exc).__name__}: {exc}")
        return None
    finally:
        sys.path.remove(str(source.parent))
        sys.modules.pop(module_name, None)
    return value


def _inside(directory: Path, relative: str, field: str, problems: list[str]) -> Path | None:
    """Resolve a manifest path, which must stay inside its resource directory.

    A resource is pushed and pulled as its directory alone, so a path that
    escapes it would work locally and break everywhere else.

    Returns:
        The resolved path, or ``None`` after recording a problem.
    """
    target = (directory / relative).resolve()
    try:
        target.relative_to(directory.resolve())
    except ValueError:
        problems.append(f"{field}: {relative} must be inside {directory.name}/")
        return None
    return target


def _package_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        relative = path.relative_to(root).parts
        if (
            path.is_file()
            and not path.name.startswith(".")
            and not _IGNORED_PARTS.intersection(relative)
        ):
            yield path


def _display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return type(exc).__name__
    if lines[0].startswith("Cannot create") and len(lines) > 1:
        return " ".join(lines[1:])
    return " ".join(lines)


def _is_builtin_harness(name: str) -> bool:
    from plural.harness.builtins import BUILTIN_HARNESSES

    return name in BUILTIN_HARNESSES


def _missing_message(project: Project, ref: ResourceRef) -> str:
    local = project.names(ref.info)
    listing = f" Local {ref.info.directory}: {', '.join(local)}." if local else ""
    return (
        f"{ref.info.label} {ref.name!r} is not in {ref.info.directory}/ of project "
        f"{project.name!r}.{listing}\nCreate it with `plural {ref.info.cli} init {ref.name}`, "
        f"or restore it with `plural {ref.info.cli} pull {ref.name}`."
    )


_LOADERS: dict[str, Callable[[Workspace, ResourceRef, Path], LocalResource]] = {
    ENVIRONMENT.name: _load_environment,
    VERIFIER.name: _load_verifier,
    HARNESS.name: _load_harness,
    TASK.name: _load_task,
    AGENT.name: _load_agent,
    BENCHMARK.name: _load_benchmark,
}


__all__ = [
    "SCAFFOLD_MARKER",
    "LocalResource",
    "Workspace",
    "declared_dependencies",
    "load_harness_directory",
    "runtime_from_manifest",
    "scaffold_problems",
]
