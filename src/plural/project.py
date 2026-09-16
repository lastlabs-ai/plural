"""Public Python/YAML project serialization.

Python SDK objects define the semantics. This module is the single boundary
used by YAML and the CLI to resolve those same objects.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeGuard, cast
from uuid import uuid4

import yaml
from pydantic import BaseModel, TypeAdapter

from plural.agents import Agent
from plural.catalog import ModelCatalog, ModelSpec
from plural.environments import Environment
from plural.environments.definition import EnvironmentDefinition
from plural.harness import Harness
from plural.jobs import Job
from plural.tasks import Benchmark, Task
from plural.verifiers import (
    AgentVerifier,
    DeterministicVerifier,
    Verifier,
    VerifierDefinition,
)

ProjectObject = Agent | Harness | Environment[Any, Any] | Verifier | Task | Benchmark | Job
_VERIFIER_ADAPTER: TypeAdapter[VerifierDefinition] = TypeAdapter(VerifierDefinition)
_INTERNAL_SCHEMA_TYPES = frozenset(
    {
        "HarnessBinding",
        "HarnessDefinition",
        "HarnessPackage",
        "PackageSource",
    }
)


class CatalogContext:
    """Explicit factory for objects validated against an effective catalog."""

    def __init__(self, catalog: ModelCatalog | None = None) -> None:
        self.catalog = catalog or ModelCatalog()

    @classmethod
    def from_file(cls, path: str | Path) -> CatalogContext:
        """Load project model entries from JSON or YAML.

        Returns:
            A context containing bundled models plus explicit project entries.
        """
        source = Path(path)
        payload = _read_mapping(source)
        catalog_payload = payload.get("catalog", payload)
        if not isinstance(catalog_payload, Mapping):
            raise ValueError("catalog must be a mapping")
        entries = catalog_payload.get("models", ())
        if not isinstance(entries, list):
            raise ValueError("catalog.models must be a list")
        return cls(ModelCatalog(entries=(ModelSpec.model_validate(item) for item in entries)))

    def agent(self, **fields: Any) -> Agent:
        """Create an Agent against this effective catalog.

        Returns:
            A validated Agent.
        """
        return Agent.from_catalog(self.catalog, **fields)

    def agent_verifier(self, **fields: Any) -> AgentVerifier:
        """Create an AgentVerifier against this effective catalog.

        Returns:
            A validated AgentVerifier.
        """
        return AgentVerifier.from_catalog(self.catalog, **fields)

    def resolver(self, root: str | Path | None = None) -> Resolver:
        """Create a resolver carrying this catalog.

        Returns:
            A public project resolver.
        """
        return Resolver(root=root, catalog=self.catalog)


class Resolver:
    """Resolve Python object references and public YAML object graphs."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        catalog: ModelCatalog | None = None,
    ) -> None:
        self.root = Path(root or ".").expanduser().resolve()
        self.catalog = catalog or ModelCatalog()

    def load(
        self,
        reference: str | Path,
        *,
        expected: type[Any] | tuple[type[Any], ...] | None = None,
    ) -> ProjectObject:
        """Load one YAML file or ``path.py:object`` reference.

        Returns:
            The resolved public SDK object.
        """
        text = str(reference)
        python = _split_python_reference(text, self.root)
        if python is not None:
            source, object_path = python
            value = self._load_python(source, object_path)
        else:
            source = self._resolve_path(Path(text))
            if source.is_dir():
                candidates = [
                    source / name
                    for name in ("project.yaml", "job.yaml", "environment.yaml")
                    if (source / name).is_file()
                ]
                if len(candidates) != 1:
                    raise ValueError(
                        f"{source} must contain exactly one project.yaml, job.yaml, "
                        "or environment.yaml"
                    )
                source = candidates[0]
            value = self._load_payload(_read_mapping(source), source.parent)
        if expected is not None and not isinstance(value, expected):
            names = (
                ", ".join(item.__name__ for item in expected)
                if isinstance(expected, tuple)
                else expected.__name__
            )
            raise TypeError(f"{reference} resolved to {type(value).__name__}, expected {names}")
        return value

    def resolve(self, value: Any, *, base: str | Path | None = None) -> Any:
        """Resolve an inline object, reference, or already-created SDK object.

        Returns:
            The corresponding public SDK object.
        """
        if _is_project_object(value):
            return value
        location = Path(base).resolve() if base is not None else self.root
        if isinstance(value, (str, Path)):
            nested = Resolver(root=location, catalog=self.catalog)
            return nested.load(value)
        if isinstance(value, Mapping):
            return self._load_payload(dict(value), location)
        raise TypeError(f"unsupported project value: {type(value).__name__}")

    def dumps(self, value: ProjectObject, *, base: str | Path | None = None) -> str:
        """Serialize one public SDK graph to deterministic YAML.

        Returns:
            YAML using public field names and defaults.
        """
        location = Path(base).resolve() if base is not None else self.root
        return yaml.safe_dump(
            self._dump_object(value, location),
            sort_keys=False,
            allow_unicode=True,
        )

    def dump(self, value: ProjectObject, path: str | Path) -> Path:
        """Write one public SDK graph as YAML.

        Returns:
            The written path.
        """
        destination = self._resolve_path(Path(path))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.dumps(value, base=destination.parent), encoding="utf-8")
        return destination

    def _resolve_path(self, path: Path) -> Path:
        expanded = path.expanduser()
        return expanded.resolve() if expanded.is_absolute() else (self.root / expanded).resolve()

    def _load_python(self, source: Path, object_path: str) -> ProjectObject:
        module_name = f"_plural_project_{uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, source)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot import Python project reference {source}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        sys.path.insert(0, str(source.parent))
        try:
            spec.loader.exec_module(module)
            value: Any = module
            for part in object_path.split("."):
                value = getattr(value, part)
            if inspect.isclass(value) and issubclass(value, Environment):
                value._python_source = source
                value._python_object = object_path
                return cast(ProjectObject, value)
            if inspect.isclass(value) and issubclass(value, Harness):
                value._bound_python_source = source
                value._bound_python_object = object_path
                value = value()
                value._python_source = source
                value._python_object = object_path
                value._bind_source(source)
            if isinstance(value, Environment):
                type(value)._python_source = source
                type(value)._python_object = type(value).__qualname__
                value._python_source = source
                value._python_object = object_path
        finally:
            sys.path.pop(0)
            sys.modules.pop(module_name, None)
        if not _is_project_object(value):
            raise TypeError(
                f"{source}:{object_path} is {type(value).__name__}, not a public project object"
            )
        return value

    def _load_payload(self, payload: dict[str, Any], base: Path) -> ProjectObject:
        if set(payload) in ({"ref"}, {"$ref"}):
            return Resolver(root=base, catalog=self.catalog).load(
                str(payload.get("ref") or payload["$ref"])
            )
        raw_kind = payload.get("kind")
        if raw_kind in {"deterministic", "agent", "human"} and (
            "check" in payload or "criteria" in payload or raw_kind == "human"
        ):
            kind = "verifier"
        else:
            kind = str(payload.pop("kind", "") or _infer_kind(payload))
        if kind == "agent":
            harness_value = payload.get("harness")
            if isinstance(harness_value, str):
                from plural.harness.builtins import BUILTIN_HARNESSES

                if harness_value not in BUILTIN_HARNESSES:
                    harness = self._resolve_nested(harness_value, base)
                    if not isinstance(harness, Harness):
                        raise TypeError("Agent harness must resolve to a Harness subclass instance")
                    payload["harness"] = harness
            elif harness_value is not None:
                if isinstance(harness_value, Mapping):
                    self._reject_legacy_declared_harness(harness_value)
                harness = self._resolve_nested(harness_value, base)
                if not isinstance(harness, Harness):
                    raise TypeError("Agent harness must resolve to a Harness or built-in name")
                payload["harness"] = harness
            return Agent.model_validate(payload, context={"catalog": self.catalog, "root": base})
        if kind == "harness":
            self._reject_legacy_declared_harness(payload)
            archive = payload.pop("archive", None)
            if archive is not None:
                from plural.harness.models import LockedHarness
                from plural.harness.retrieval import package_from_archive

                digest = payload.pop("digest", None)
                if not isinstance(digest, str) or not digest:
                    raise ValueError("Archived Harness YAML requires an immutable digest")
                if payload:
                    raise ValueError(
                        f"Archived Harness YAML has unsupported fields: {sorted(payload)!r}"
                    )
                return LockedHarness.from_package(package_from_archive(str(archive), digest))
            python_ref = payload.pop("python", None)
            if python_ref is None:
                raise ValueError(
                    "Custom Harness YAML now references a Harness subclass.\n"
                    "Use: kind: harness\n"
                    "     python: harness.py:YourHarness"
                )
            loaded = Resolver(root=base, catalog=self.catalog).load(str(python_ref))
            if not isinstance(loaded, Harness):
                raise TypeError(f"{python_ref!r} did not resolve to a Harness subclass")
            config = payload.pop("config", None)
            allowed = {"name", "version", "description"}
            unsupported = sorted(set(payload) - allowed)
            if unsupported:
                raise ValueError(
                    "Class-based Harness YAML accepts only python and optional config; "
                    f"remove: {unsupported!r}"
                )
            if config is not None:
                if not isinstance(config, Mapping):
                    raise TypeError("Harness config must be a mapping")
                loaded = type(loaded)(config=dict(config))
                loaded._python_source = Path(str(python_ref).split(":", 1)[0])
                if not loaded._python_source.is_absolute():
                    loaded._python_source = (base / loaded._python_source).resolve()
                loaded._python_object = str(python_ref).split(":", 1)[1]
                loaded._bind_source(loaded._python_source)
            return loaded
        if kind == "verifier":
            payload = _resolve_verifier_check(payload, base)
            return _VERIFIER_ADAPTER.validate_python(payload, context={"catalog": self.catalog})
        if kind == "environment":
            return self._load_environment(payload, base)
        if kind == "task":
            environment = self._resolve_nested(payload.pop("environment"), base)
            verifiers = tuple(self._resolve_nested(item, base) for item in payload.pop("verifiers"))
            return Task.model_validate(
                {**payload, "environment": environment, "verifiers": verifiers},
                context={"catalog": self.catalog},
            )
        if kind == "benchmark":
            tasks = tuple(self._resolve_nested(item, base) for item in payload.pop("tasks"))
            return Benchmark.model_validate({**payload, "tasks": tasks})
        if kind == "job":
            source = self._resolve_nested(payload.pop("source"), base)
            if not isinstance(source, (Task, Benchmark)):
                raise TypeError("Job source must resolve to a Task or Benchmark")
            agents: list[Agent] = []
            for item in payload.pop("agents"):
                agent = self._resolve_nested(item, base)
                if not isinstance(agent, Agent):
                    raise TypeError("Job agents must resolve to Agent objects")
                agents.append(agent)
            allowed = {
                "mode",
                "attempts",
                "concurrency",
                "per_runtime_concurrency",
                "priority",
                "retry",
            }
            return Job(
                source,
                agents=agents,
                catalog=self.catalog,
                **{key: payload[key] for key in allowed if key in payload},
            )
        raise ValueError(
            "project YAML requires kind: agent, harness, environment, verifier, task, "
            "benchmark, or job"
        )

    def _resolve_nested(self, value: Any, base: Path) -> ProjectObject:
        if _is_project_object(value):
            return value
        if isinstance(value, str):
            return Resolver(root=base, catalog=self.catalog).load(value)
        if isinstance(value, Mapping):
            return self._load_payload(dict(value), base)
        raise TypeError(f"invalid nested project value: {type(value).__name__}")

    def _load_environment(self, payload: dict[str, Any], base: Path) -> Environment[Any, Any]:
        python_ref = payload.pop("python", None)
        package = payload.pop("package", None)
        if python_ref is None:
            return Environment.from_config(**payload)
        reference = str(python_ref)
        loaded = Resolver(root=base, catalog=self.catalog).load(reference)
        if inspect.isclass(loaded) and issubclass(loaded, Environment):
            ctor = dict(payload)
            python_source = getattr(loaded, "_python_source", None)
            python_object = getattr(loaded, "_python_object", None)
            environment = loaded(**ctor)
            environment._python_source = python_source
            environment._python_object = python_object
        elif isinstance(loaded, Environment):
            environment = loaded
            if payload:
                python_source = environment._python_source
                python_object = environment._python_object
                environment = type(environment)(**payload)
                environment._python_source = python_source
                environment._python_object = python_object
        else:
            raise TypeError(f"{reference} did not resolve to an Environment")
        if package is not None:
            source = package.get("source") if isinstance(package, Mapping) else None
            if source:
                environment._bind_source((base / str(source)).resolve())
            digest = package.get("digest") if isinstance(package, Mapping) else None
            if digest and environment.source is not None:
                environment.source = environment.source.model_copy(update={"digest": str(digest)})
        return environment

    def _dump_object(self, value: ProjectObject, base: Path) -> dict[str, Any]:
        if isinstance(value, Agent):
            payload = _public_data(
                value.model_dump(mode="json", exclude={"harness", "harness_kwargs"})
            )
            if isinstance(value.harness, str):
                payload["harness"] = value.harness
                if value.harness_kwargs:
                    payload["harness_kwargs"] = _public_data(value.harness_kwargs)
            elif value.harness is not None:
                payload["harness"] = self._dump_harness(value.harness, base)
            return {"kind": "agent", **payload}
        if isinstance(value, Harness):
            return self._dump_harness(value, base)
        if isinstance(value, Verifier):
            return self._dump_verifier(value, base)
        if isinstance(value, Environment):
            return self._dump_environment(value, base)
        if isinstance(value, Task):
            return {
                "kind": "task",
                "name": value.name,
                "version": value.version,
                "instructions": value.instructions,
                "goals": list(value.goals),
                "info": _jsonable(value.info),
                "metadata": _jsonable(value.metadata),
                "environment": self._dump_environment_value(value.environment, base),
                "verifiers": [self._dump_object(item, base) for item in value.verifiers],
                "resources": _jsonable(value.resources),
                "initial_state": _jsonable(value.initial_state),
                "reset_options": _jsonable(value.reset_options),
            }
        if isinstance(value, Benchmark):
            return {
                "kind": "benchmark",
                "name": value.name,
                "version": value.version,
                "tasks": [self._dump_object(item, base) for item in value.tasks],
                "primary_metric": value.primary_metric,
                "description": value.description,
                "metadata": _jsonable(value.metadata),
            }
        if isinstance(value, Job):
            spec = value.spec
            return {
                "kind": "job",
                "source": self._dump_object(value.source, base),
                "agents": [self._dump_object(item, base) for item in value.agents],
                "mode": spec.mode.value,
                "attempts": spec.attempts,
                "concurrency": spec.concurrency,
                "per_runtime_concurrency": spec.per_runtime_concurrency,
                "priority": spec.priority,
                "retry": _public_data(spec.retry.model_dump(mode="json")),
            }
        raise TypeError(f"cannot serialize {type(value).__name__}")

    def _dump_verifier(self, value: Verifier, base: Path) -> dict[str, Any]:
        exclude = {"check"} if isinstance(value, DeterministicVerifier) else set()
        payload = _public_data(value.model_dump(mode="json", exclude=exclude or None))
        if isinstance(value, DeterministicVerifier):
            check = value.check
            if callable(check):
                source = inspect.getsourcefile(check)
                qualname = getattr(check, "__qualname__", getattr(check, "__name__", "check"))
                if source:
                    payload["check"] = {
                        "python": f"{_relative(Path(source).resolve(), base)}:{qualname}",
                    }
                else:
                    payload["check"] = {
                        "python": f"{getattr(check, '__module__', 'verify')}:{qualname}",
                    }
            elif isinstance(check, dict):
                payload["check"] = _jsonable(check)
            elif isinstance(check, tuple):
                payload["check"] = list(check)
            else:
                payload["check"] = check
        return cast(dict[str, Any], payload)

    def _reject_legacy_declared_harness(self, payload: Mapping[str, Any]) -> None:
        from plural.harness.builtins import (
            LEGACY_DECLARED_HARNESS_NAMES,
            legacy_declared_harness_error,
        )

        name = str(payload.get("name") or "")
        if name in LEGACY_DECLARED_HARNESS_NAMES and payload.get("implementation") == "declared":
            raise legacy_declared_harness_error(name)

    def _dump_harness(self, harness: Harness, base: Path) -> dict[str, Any]:
        from plural.harness.models import LockedHarness

        if isinstance(harness, LockedHarness):
            package = harness._package()
            if package.source.kind != "archive" or package.source.digest is None:
                raise ValueError("locked Harness must retain its archive URI and digest")
            return {
                "kind": "harness",
                "archive": package.source.uri,
                "digest": package.source.digest,
            }
        source = harness._python_source or harness._class_source_file()
        if source is None:
            raise ValueError("cannot serialize a Harness subclass without a source file")
        object_path = harness._python_object or type(harness).__qualname__
        payload: dict[str, Any] = {
            "kind": "harness",
            "python": f"{_relative(Path(source).resolve(), base)}:{object_path}",
        }
        if harness.config:
            payload["config"] = _jsonable(harness.config)
        return payload

    def _dump_environment_value(self, value: Any, base: Path) -> dict[str, Any]:
        if isinstance(value, Environment):
            return self._dump_environment(value, base)
        if isinstance(value, EnvironmentDefinition):
            return {
                "kind": "environment",
                **_public_data(value.model_dump(mode="json", exclude={"source"})),
            }
        raise TypeError("Task environment is not a public Environment")

    def _dump_environment(self, environment: Environment[Any, Any], base: Path) -> dict[str, Any]:
        if type(environment) is Environment or environment._compiled_definition is not None:
            return {
                "kind": "environment",
                **_public_data(
                    environment.definition().model_dump(mode="json", exclude={"source"})
                ),
            }
        source_file = environment._python_source or inspect.getsourcefile(type(environment))
        if source_file is None:
            raise ValueError("cannot serialize Environment class without a source file")
        source_path = Path(source_file).resolve()
        object_path = environment._python_object or type(environment).__qualname__
        reference = f"{_relative(source_path, base)}:{object_path}"
        payload: dict[str, Any] = {"kind": "environment", "python": reference}
        config = {
            "name": environment.name,
            "version": environment.version,
            "description": environment.description,
            "overview": environment.overview,
            "readme": environment.readme,
            "resources": _jsonable(environment.resources),
            "runtime": _public_data(environment.runtime.model_dump(mode="json")),
            "secrets": _jsonable(environment.secrets),
            "guardrails": _jsonable(environment.guardrails),
            "harness_policy": _public_data(environment.harness_policy.model_dump(mode="json")),
            "limits": _public_data(environment.limits.model_dump(mode="json")),
            "metadata": _jsonable(environment.metadata),
        }
        if environment.reset_command:
            config["reset_command"] = list(environment.reset_command)
        payload.update(config)
        return payload


def load(
    reference: str | Path,
    *,
    catalog: ModelCatalog | None = None,
    expected: type[Any] | tuple[type[Any], ...] | None = None,
) -> ProjectObject:
    """Load a public project object from YAML or Python.

    Returns:
        The resolved object.
    """
    path = Path(str(reference).split(":", 1)[0])
    root = path.expanduser().resolve().parent if path.parent != Path("") else Path.cwd()
    return Resolver(root=root, catalog=catalog).load(
        path.name + (f":{str(reference).split(':', 1)[1]}" if ":" in str(reference) else ""),
        expected=expected,
    )


def dump(value: ProjectObject, path: str | Path) -> Path:
    """Serialize a public object graph to YAML.

    Returns:
        The written path.
    """
    destination = Path(path).expanduser().resolve()
    return Resolver(root=destination.parent).dump(value, destination.name)


def dumps(value: ProjectObject) -> str:
    """Serialize a public object graph to YAML text.

    Returns:
        The YAML text.
    """
    return Resolver().dumps(value)


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


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return dict(value)


def _split_python_reference(value: str, root: Path) -> tuple[Path, str] | None:
    if ":" not in value:
        return None
    path_text, object_path = value.rsplit(":", 1)
    if not object_path or Path(path_text).suffix != ".py":
        return None
    path = Path(path_text).expanduser()
    source = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return source, object_path


def _infer_kind(payload: Mapping[str, Any]) -> str:
    if "schema_version" in payload and ("verifier" in payload or "actions" in payload):
        return "environment"
    if "source" in payload and "agents" in payload:
        return "job"
    if "tasks" in payload and "version" in payload:
        return "benchmark"
    if "environment" in payload and "verifiers" in payload:
        return "task"
    if "model" in payload and "check" not in payload and "criteria" not in payload:
        return "agent"
    if "command" in payload and ("source" in payload or "capabilities" in payload):
        return "harness"
    if "check" in payload or payload.get("kind") in {"deterministic", "agent", "human"}:
        return "verifier"
    if "runtime" in payload or "actions" in payload or "python" in payload:
        return "environment"
    return ""


def _import_callable(source: Path, object_path: str) -> Any:
    module_name = f"_plural_check_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import Verifier check {source}:{object_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(source.parent))
    try:
        spec.loader.exec_module(module)
        value: Any = module
        for part in object_path.split("."):
            value = getattr(value, part)
    finally:
        sys.path.pop(0)
        sys.modules.pop(module_name, None)
    if not callable(value):
        raise TypeError(f"{source}:{object_path} is not a callable Verifier check")
    return value


def _resolve_verifier_check(payload: dict[str, Any], base: Path) -> dict[str, Any]:
    check = payload.get("check")
    if not (isinstance(check, dict) and check.get("python")):
        return payload
    reference = str(check["python"])
    if ":" not in reference:
        return payload
    source_text, object_path = reference.rsplit(":", 1)
    source = Path(source_text).expanduser()
    path = source if source.is_absolute() else (base / source)
    if not path.exists():
        return payload
    resolved = dict(payload)
    resolved["check"] = _import_callable(path.resolve(), object_path)
    return resolved


def _is_project_object(value: object) -> TypeGuard[ProjectObject]:
    return isinstance(value, (Agent, Harness, Environment, Verifier, Task, Benchmark, Job))


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _public_data(value.model_dump(mode="json"))
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _public_data(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {
                "schema_version",
                "protocol",
                "protocol_adapter",
                "definition",
                "manifest",
                "binding",
                "package",
            }:
                continue
            public_key = "version" if key == "revision" else str(key)
            if public_key in result:
                continue
            result[public_key] = _public_data(item)
        return result
    if isinstance(value, list):
        return [_public_data(item) for item in value]
    return value


def _relative(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        import os

        return Path(os.path.relpath(path, base)).as_posix()


__all__ = [
    "CatalogContext",
    "ProjectObject",
    "Resolver",
    "dump",
    "dumps",
    "load",
    "public_schema",
]
