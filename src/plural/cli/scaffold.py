"""Resource scaffolds around the public project serializer."""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel

from plural import Agent, Benchmark, Environment, Harness, Job, Task
from plural.agents import AgentDefinition
from plural.common import PackageSource
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.errors import NotFoundError
from plural.harness.retrieval import package_from_archive, tree_digest
from plural.jobs import JobSpec
from plural.project import Resolver, prepare_task_payload, public_schema, read_task_package
from plural.studio import resolve_published_revision
from plural.tasks import BenchmarkDefinition, TaskDefinition
from plural.verifiers import (
    AgentVerifier,
    DeterministicVerifier,
    HumanVerifier,
    RubricCriterion,
    Verifier,
    VerifierDefinition,
)

if TYPE_CHECKING:
    from plural.client import Client


def read_yaml(path: Path) -> dict[str, Any]:
    """Read one YAML mapping."""
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return dict(value)


def write_yaml(path: Path, payload: Any) -> None:
    """Write deterministic YAML."""
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", exclude_none=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _target(path: Path, name: str) -> Path:
    return path if path.suffix in {".yaml", ".yml"} else path / name


def _create(path: Path, payload: Any, *, force: bool) -> Path:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to replace it")
    write_yaml(path, payload)
    return path


def scaffold_environment(directory: Path, name: str, *, force: bool = False) -> list[Path]:
    """Create a small public Environment package."""
    directory.mkdir(parents=True, exist_ok=True)
    environment_yaml = _create(
        directory / "environment.yaml",
        {
            "kind": "environment",
            "name": name,
            "overview": "A typed runtime world with declared actions and observable state.",
            "runtime": EnvironmentRuntime().model_dump(mode="json"),
        },
        force=force,
    )
    environment_py = directory / "environment.py"
    if environment_py.exists() and not force:
        raise FileExistsError(f"{environment_py} already exists; pass --force to replace it")
    environment_py.write_text(
        "from plural import Environment, Runtime\n\n\n"
        "class ProjectEnvironment(Environment):\n"
        f'    name = "{name}"\n'
        '    version = "0.1.0"\n\n\n'
        "environment = ProjectEnvironment(runtime=Runtime.docker())\n",
        encoding="utf-8",
    )
    dockerfile = directory / "Dockerfile"
    if dockerfile.exists() and not force:
        raise FileExistsError(f"{dockerfile} already exists; pass --force to replace it")
    dockerfile.write_text(
        "FROM python:3.12-slim\nWORKDIR /workspace/environment\nCOPY . .\n",
        encoding="utf-8",
    )
    return [environment_yaml, environment_py, dockerfile]


def scaffold_verifier(
    path: Path,
    *,
    name: str,
    kind: Literal["deterministic", "agent", "human"] = "deterministic",
    force: bool = False,
) -> Path:
    """Create a standalone Verifier revision."""
    if kind == "deterministic":
        verifier: VerifierDefinition = DeterministicVerifier(
            name=name,
            check=("python", "verify.py"),
        )
    elif kind == "agent":
        verifier = AgentVerifier(
            name=name,
            model="openai/gpt-5.6-luna",
            instructions="Score the submitted result against the rubric.",
            criteria=(
                RubricCriterion(
                    name="correct",
                    description="The answer is correct.",
                ),
            ),
        )
    else:
        verifier = HumanVerifier(
            name=name,
            instructions="Review the result.",
            criteria=(
                RubricCriterion(
                    name="correct",
                    description="The answer is correct.",
                ),
            ),
        )
    return _create(_target(path, "verifier.yaml"), verifier, force=force)


def init_task(
    name: str,
    *,
    environment: str | Path | None = None,
    verifiers: str | Path | Sequence[str | Path] | None = (),
    bare: bool = False,
    directory: str | Path | None = None,
    force: bool = False,
    client: Client | None = None,
) -> list[Path]:
    """Create a local task directory without publishing it.

    Args:
        name: Task slug and default directory name.
        environment: Optional hosted environment slug/id or local file reference.
        verifiers: Optional hosted verifier slugs/ids or local file references.
        bare: When true, write empty instructions/resources and only identity fields.
        directory: Optional directory to create instead of ``./<name>``.
        force: Replace existing task files.
        client: Optional configured client used only to warn when ``name`` exists.

    Returns:
        The created instruction file, task file, and resources directory.
    """
    _validate_task_name(name)
    if client is not None and find_remote_task(client, name) is not None:
        warnings.warn(
            f"Task {name!r} already exists in the current project; "
            "writing local files without publishing",
            stacklevel=2,
        )
    target = Path(directory).expanduser() if directory is not None else Path(name)
    target.mkdir(parents=True, exist_ok=True)
    instruction = target / "instruction.md"
    if instruction.exists() and not force:
        raise FileExistsError(f"{instruction} already exists; pass --force to replace it")
    resources = target / "resources"
    resources.mkdir(parents=True, exist_ok=True)
    verifier_refs = _task_verifier_refs(verifiers)

    if bare:
        instruction.write_text("", encoding="utf-8")
        payload: dict[str, Any] = {"kind": "task", "name": name, "version": "0.1.0"}
    else:
        instruction.write_text(
            f"# {name}\n\nReplace this with what the agent should accomplish.\n",
            encoding="utf-8",
        )
        payload = {
            "kind": "task",
            "name": name,
            "version": "0.1.0",
            "instructions": "instruction.md",
            "initial_state": {},
            "info": {},
            "resources": [
                {
                    "kind": "file",
                    "name": "resources",
                    "path": "resources",
                    "delivery": "source",
                }
            ],
        }
        if environment is not None:
            payload["environment"] = _task_binding_text(environment, target)
        if verifier_refs:
            payload["verifiers"] = [
                _task_binding_text(verifier, target) for verifier in verifier_refs
            ]
    config = _create(target / "task.yaml", payload, force=force)
    return [instruction, config, resources]


def find_remote_task(client: Client, name: str) -> dict[str, Any] | None:
    """Return a hosted task parent, or ``None`` when its slug is available.

    Args:
        client: Configured hosted client.
        name: Task slug or id in the client's project scope.

    Returns:
        The hosted parent mapping, or ``None`` when no such task exists.
    """
    try:
        parent = client.tasks.get(name)
    except NotFoundError:
        return None
    return dict(parent) if isinstance(parent, Mapping) else parent


def task_push_needs_remote(
    path: str | Path,
    *,
    environment_revision_id: str | None = None,
    verifier_revision_ids: Sequence[str] | None = None,
) -> bool:
    """Return whether task push must resolve hosted slugs before publishing.

    Args:
        path: Task YAML file or task directory.
        environment_revision_id: Explicit hosted revision id, when supplied.
        verifier_revision_ids: Explicit hosted revision ids, when supplied.

    Returns:
        ``True`` when any environment or verifier binding is a hosted slug
        rather than a local file. Explicit revision ids still use the hosted
        definitions for local validation.
    """
    _source, raw, base = read_task_package(path)
    environment_value = raw.get("environment")
    verifier_values = raw.get("verifiers")
    has_remote_environment = isinstance(environment_value, str) and not _binding_is_local(
        environment_value, base
    )
    has_remote_verifier = isinstance(verifier_values, (list, tuple)) and any(
        isinstance(value, str) and not _binding_is_local(value, base) for value in verifier_values
    )
    return has_remote_environment or has_remote_verifier


def load_task_for_push(
    path: str | Path,
    *,
    client: Client | None = None,
    environment_revision_id: str | None = None,
    verifier_revision_ids: Sequence[str] | None = None,
) -> tuple[TaskDefinition, str, list[str]]:
    """Load a task package and resolve its hosted environment and verifiers.

    Args:
        path: Task YAML file or task directory.
        client: Configured hosted client, required for slug references.
        environment_revision_id: Explicit hosted revision id overriding lookup.
        verifier_revision_ids: Explicit hosted revision ids overriding lookup.

    Returns:
        The compiled task definition with resolved revision ids.
    """
    source, raw, base = read_task_package(path)
    environment_value = raw.get("environment")
    verifier_values = raw.get("verifiers")
    if environment_value is None:
        raise ValueError(
            f"{source} does not name an environment; add environment: <slug> to task.yaml"
        )
    if not isinstance(verifier_values, (list, tuple)) or not verifier_values:
        raise ValueError(f"{source} does not name a verifier; add verifiers: [<slug>] to task.yaml")
    explicit_verifiers = list(verifier_revision_ids) if verifier_revision_ids is not None else None
    if explicit_verifiers is not None and len(explicit_verifiers) != len(verifier_values):
        raise ValueError(
            f"{source} names {len(verifier_values)} verifiers "
            f"but received {len(explicit_verifiers)} --verifier-revision-id values"
        )
    resolver = Resolver(root=base)
    environment_revision = _remote_task_revision(client, "environment", environment_value, base)
    verifier_revisions = [
        _remote_task_revision(client, "verifier", value, base) for value in verifier_values
    ]
    payload = prepare_task_payload(raw, base)
    payload["environment"] = _prepare_task_binding(
        environment_value,
        resolver,
        base,
        "environment",
        environment_revision[1] if environment_revision is not None else None,
    )
    payload["verifiers"] = [
        _prepare_task_binding(
            value, resolver, base, "verifier", revision[1] if revision is not None else None
        )
        for value, revision in zip(verifier_values, verifier_revisions, strict=True)
    ]
    task = Task.model_validate(payload, context={"catalog": resolver.catalog})
    if environment_revision_id is not None:
        resolved_environment = environment_revision_id
    elif environment_revision is not None:
        resolved_environment = environment_revision[0]
    else:
        raise ValueError(
            f"Task environment {environment_value!r} is a local file; "
            "pass --environment-revision-id to push it"
        )
    resolved_verifiers = []
    for index, (value, revision) in enumerate(
        zip(verifier_values, verifier_revisions, strict=True)
    ):
        if explicit_verifiers is not None:
            resolved_verifiers.append(explicit_verifiers[index])
        elif revision is not None:
            resolved_verifiers.append(revision[0])
        else:
            raise ValueError(
                f"Task verifier {index + 1} {value!r} is a local file; "
                "pass --verifier-revision-id to push it"
            )
    return task._definition(), resolved_environment, resolved_verifiers


def _validate_task_name(name: str) -> None:
    """Reject empty names and directory traversal before creating files."""
    candidate = Path(name)
    if not name or candidate.is_absolute() or len(candidate.parts) != 1:
        raise ValueError(f"Task name {name!r} must be a single directory name")
    if name in {".", ".."}:
        raise ValueError(f"Task name {name!r} must be a single directory name")


def _task_verifier_refs(verifiers: str | Path | Sequence[str | Path] | None) -> list[str | Path]:
    """Normalize one verifier reference or a sequence of references."""
    if verifiers is None:
        return []
    if isinstance(verifiers, (str, Path)):
        return [verifiers]
    return list(verifiers)


def _task_binding_text(value: str | Path, base: Path) -> str:
    """Store a task binding as a portable relative path or hosted slug."""
    text = str(value)
    candidate = Path(text).expanduser()
    if not candidate.exists():
        return text
    absolute = candidate.resolve()
    try:
        return absolute.relative_to(base.resolve()).as_posix()
    except ValueError:
        return text


def _binding_is_local(value: Any, base: Path) -> bool:
    """Return whether a task binding points at an existing local file."""
    if not isinstance(value, (str, Path)):
        return False
    candidate = Path(str(value)).expanduser()
    if candidate.is_absolute():
        return candidate.exists()
    return (base / candidate).exists()


def _remote_task_revision(
    client: Client | None, kind: str, value: Any, base: Path
) -> tuple[str, dict[str, Any]] | None:
    """Fetch the current hosted revision for a slug reference, if needed."""
    if not isinstance(value, str) or _binding_is_local(value, base):
        return None
    if client is None:
        raise ValueError(
            f"Task {kind} {value!r} is a hosted slug; pass a configured client to resolve it"
        )
    api = client.environments if kind == "environment" else client.verifiers
    revision_id, revision = resolve_published_revision(api, kind, value)
    definition = revision.get("definition") if isinstance(revision, Mapping) else None
    if not isinstance(definition, Mapping):
        raise ValueError(f"Hosted {kind} {value!r} did not include its current definition")
    return revision_id, dict(definition)


def _prepare_task_binding(
    value: Any,
    resolver: Resolver,
    base: Path,
    kind: str,
    remote_definition: dict[str, Any] | None,
) -> Any:
    """Resolve one environment or verifier binding to a public SDK object."""
    if isinstance(value, (Environment, EnvironmentDefinition, Verifier)):
        return value
    if isinstance(value, Mapping):
        return resolver.resolve(value)
    if isinstance(value, (str, Path)):
        if _binding_is_local(value, base):
            return resolver.resolve(str(value))
        if remote_definition is not None:
            return resolver.resolve(remote_definition)
        raise ValueError(
            f"Task {kind} {value!r} is a local file; pass an explicit hosted revision id to push it"
        )
    raise TypeError(f"Task {kind} must be an object, file, or hosted slug")


def scaffold_task(
    path: Path,
    *,
    task_id: str,
    environment_path: Path,
    verifier_paths: tuple[Path, ...],
    force: bool = False,
) -> Path:
    """Create a standalone Task file with revision references."""
    task = {
        "kind": "task",
        "name": task_id,
        "version": "0.1.0",
        "instructions": "Complete the task described in info.",
        "environment": str(environment_path),
        "verifiers": [str(item) for item in verifier_paths],
        "info": {"prompt": "Replace this example."},
    }
    return _create(_target(path, "task.yaml"), task, force=force)


def scaffold_harness(directory: Path, name: str, *, force: bool = False) -> list[Path]:
    """Create a class-based custom Harness."""
    directory.mkdir(parents=True, exist_ok=True)
    class_name = "".join(part.capitalize() for part in name.replace("-", "_").split("_"))
    class_name = f"{class_name or 'Custom'}Harness"
    harness = {"kind": "harness", "python": f"harness.py:{class_name}"}
    config = _create(directory / "harness.yaml", harness, force=force)
    runner = directory / "harness.py"
    if runner.exists() and not force:
        raise FileExistsError(f"{runner} already exists; pass --force to replace it")
    runner.write_text(
        (
            "from plural import (Harness, HarnessAgent, HarnessEnvironment, "
            "HarnessResult, HarnessTask)\n\n\n"
            f"class {class_name}(Harness):\n"
            f"    name = {name!r}\n"
            '    description = "Custom Agent interaction loop."\n\n'
            "    def run(\n"
            "        self,\n"
            "        task: HarnessTask,\n"
            "        agent: HarnessAgent,\n"
            "        environment: HarnessEnvironment,\n"
            "    ) -> HarnessResult:\n"
            "        observation = environment.reset()\n"
            "        completion = agent.complete(\n"
            "            [\n"
            '                {"role": "system", "content": agent.instructions},\n'
            '                {"role": "user", "content": task.instructions},\n'
            "                {\n"
            '                    "role": "user",\n'
            '                    "content": f"Current observation: {observation}",\n'
            "                },\n"
            "            ],\n"
            "            tools=environment.tools(),\n"
            "        )\n"
            "        return HarnessResult(response=completion.text)\n"
        ),
        encoding="utf-8",
    )
    return [config, runner]


def scaffold_agent(
    path: Path,
    *,
    name: str,
    model: str,
    harness_path: Path | str | None = None,
    harness_digest: str | None = None,
    secret_names: tuple[str, ...] = (),
    force: bool = False,
    **_: Any,
) -> Path:
    """Create an Environment-independent Agent revision."""
    from plural.harness.builtins import BUILTIN_HARNESSES

    agent: dict[str, Any] = {
        "kind": "agent",
        "name": name,
        "version": "0.1.0",
        "model": model,
        "secret_names": list(secret_names),
    }
    target = _target(path, "agent.yaml")
    if harness_path is not None:
        reference = str(harness_path)
        if reference in BUILTIN_HARNESSES:
            agent["harness"] = reference
        else:
            package = load_harness_reference(reference, digest=harness_digest)
            agent["harness"] = yaml.safe_load(Resolver(root=target.parent).dumps(package))
    return _create(target, agent, force=force)


def scaffold_benchmark(
    path: Path,
    *,
    name: str,
    task_paths: tuple[Path, ...] = (),
    force: bool = False,
    **_: Any,
) -> Path:
    """Create a public Benchmark reference file."""
    if not task_paths:
        raise ValueError("Benchmark requires at least one --task")
    return _create(
        _target(path, "benchmark.yaml"),
        {
            "kind": "benchmark",
            "name": name,
            "version": "0.1.0",
            "tasks": [str(item) for item in task_paths],
        },
        force=force,
    )


def scaffold_job(
    path: Path,
    *,
    source_path: Path | None = None,
    source_kind: Literal["benchmark", "task"] = "benchmark",
    agent_paths: tuple[Path, ...],
    force: bool = False,
    benchmark_path: Path | None = None,
    **_: Any,
) -> Path:
    """Create a public path-based Job."""
    source = source_path or benchmark_path
    if source is None:
        raise ValueError("Job requires a Task or Benchmark source")
    return _create(
        _target(path, "job.yaml"),
        {
            "kind": "job",
            "source": str(source),
            "agents": [str(item) for item in agent_paths],
        },
        force=force,
    )


def load_environment(path: Path) -> EnvironmentDefinition:
    """Adapter from the public loader to the engine definition."""
    source = _target(path, "environment.yaml")
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Environment):
        raise TypeError(f"{source} is not an Environment")
    environment = value.definition()
    root = source.parent.resolve()
    return environment.model_copy(
        update={
            "source": PackageSource(
                kind="local",
                uri=str(root),
                digest=tree_digest(root),
                trusted=True,
            )
        }
    )


def load_verifier(path: Path) -> VerifierDefinition:
    """Load one discriminated Verifier.

    A deterministic ``python script.py`` command next to the YAML is inlined so
    the Job sandbox can run the same file you edit.
    """
    source = _target(path, "verifier.yaml")
    verifier = Resolver(root=source.parent).load(source.name)
    if not isinstance(verifier, (DeterministicVerifier, AgentVerifier, HumanVerifier)):
        raise TypeError(f"{source} is not a Verifier")
    if (
        isinstance(verifier, DeterministicVerifier)
        and len(verifier.command) >= 2
        and Path(verifier.command[0]).name in {"python", "python3"}
        and str(verifier.command[-1]).endswith(".py")
    ):
        script = _resolve(source.parent, Path(verifier.command[-1]))
        if script.is_file():
            return verifier.model_copy(
                update={"command": ("python", "-c", script.read_text(encoding="utf-8"))}
            )
    return verifier


def _resolve(base: Path, value: Path) -> Path:
    return value if value.is_absolute() else base / value


def load_task(path: str | Path) -> TaskDefinition:
    """Adapter from the public loader to the engine definition."""
    source, _, _ = read_task_package(path)
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Task):
        raise TypeError(f"{source} is not a Task")
    return value._definition()


def load_benchmark(path: Path) -> BenchmarkDefinition:
    """Adapter from the public loader to the engine definition."""
    source = _target(path, "benchmark.yaml")
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Benchmark):
        raise TypeError(f"{source} is not a Benchmark")
    return value._definition()


def load_agent(path: Path) -> AgentDefinition:
    """Adapter from the public loader to the engine definition."""
    source = _target(path, "agent.yaml")
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Agent):
        raise TypeError(f"{source} is not an Agent")
    return value._definition()


def load_job(path: Path) -> JobSpec:
    """Adapter from the public loader to the engine spec."""
    source = _target(path, "job.yaml")
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Job):
        raise TypeError(f"{source} is not a Job")
    return value.spec


def load_harness(path: Path) -> Harness:
    """Load and lock a local Harness."""
    source = _target(path, "harness.yaml").resolve()
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Harness):
        raise TypeError(f"{source} is not a Harness")
    return value


def load_harness_reference(
    reference: str,
    *,
    digest: str | None = None,
    cache_root: Path | None = None,
) -> Harness:
    """Load a local Harness or immutable archive."""
    path = Path(reference).expanduser()
    if path.exists() and (path.is_dir() or path.suffix in {".yaml", ".yml", ".py"}):
        if path.suffix == ".py":
            raise ValueError(
                "A Python Harness reference must include its class, "
                "for example harness.py:SupportHarness"
            )
        return load_harness(path)
    if ":" in reference and Path(reference.rsplit(":", 1)[0]).expanduser().is_file():
        source = Path(reference.rsplit(":", 1)[0]).expanduser().resolve()
        value = Resolver(root=source.parent).load(f"{source.name}:{reference.rsplit(':', 1)[1]}")
        if not isinstance(value, Harness):
            raise TypeError(f"{reference} is not a Harness subclass")
        return value
    if digest is not None:
        from plural.harness.models import LockedHarness

        return LockedHarness.from_package(
            package_from_archive(reference, digest, cache_root=cache_root)
        )
    raise ValueError(
        "Custom Harnesses must be Python subclasses. Use harness.yaml, a "
        "file.py:HarnessClass reference, or an immutable archive with --digest."
    )


def generate_schemas(directory: Path) -> list[Path]:
    """Generate schemas from public SDK models with plain names."""
    models: tuple[tuple[str, type[BaseModel]], ...] = (
        ("Environment", EnvironmentDefinition),
        ("Harness", Harness),
        ("Task", Task),
        ("DeterministicVerifier", DeterministicVerifier),
        ("AgentVerifier", AgentVerifier),
        ("HumanVerifier", HumanVerifier),
        ("Agent", Agent),
        ("Benchmark", Benchmark),
    )
    directory.mkdir(parents=True, exist_ok=True)
    output = []
    for name, model in models:
        schema = public_schema(model)
        schema["title"] = name
        path = directory / f"{name}.schema.json"
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output.append(path)
    job_path = directory / "Job.schema.json"
    job_path.write_text(
        json.dumps(
            {
                "title": "Job",
                "type": "object",
                "required": ["source", "agents"],
                "properties": {
                    "source": {},
                    "agents": {"type": "array", "minItems": 1},
                    "mode": {"enum": ["eval", "train"], "default": "eval"},
                    "attempts": {"type": "integer", "minimum": 1, "default": 1},
                    "concurrency": {"type": "integer", "minimum": 1, "default": 1},
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    output.append(job_path)
    return output


__all__ = [
    "find_remote_task",
    "generate_schemas",
    "init_task",
    "load_agent",
    "load_benchmark",
    "load_environment",
    "load_harness",
    "load_harness_reference",
    "load_job",
    "load_task",
    "load_task_for_push",
    "load_verifier",
    "read_yaml",
    "resolve_published_revision",
    "scaffold_agent",
    "scaffold_benchmark",
    "scaffold_environment",
    "scaffold_harness",
    "scaffold_job",
    "scaffold_task",
    "scaffold_verifier",
    "task_push_needs_remote",
    "write_yaml",
]
