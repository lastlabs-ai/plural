"""Compatibility scaffolds around the public project serializer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from plural import Agent, Benchmark, Environment, Harness, HarnessOutput, Job, Task
from plural.domain import (
    AgentDefinition,
    AgentVerifier,
    BenchmarkDefinition,
    DeterministicVerifier,
    EnvironmentDefinition,
    EnvironmentRuntime,
    HumanVerifier,
    JobSpec,
    PackageSource,
    RubricCriterion,
    TaskDefinition,
    VerifierDefinition,
)
from plural.harness.retrieval import package_from_archive, tree_digest
from plural.project import Resolver, public_schema


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
        "from plural import Environment\n\n\n"
        "class ProjectEnvironment(Environment):\n"
        f'    name = "{name}"\n'
        '    version = "0.1.0"\n',
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
    """Create a runnable standalone Harness."""
    directory.mkdir(parents=True, exist_ok=True)
    harness = {
        "kind": "harness",
        "name": name,
        "version": "0.1.0",
        "description": "Custom Agent interaction loop.",
        "command": ["python", "harness.py", "chat"],
        "source": ".",
        "capabilities": ["shell"],
        "secrets": ["PLURAL_API_KEY", "OPENAI_API_KEY"],
        "environment": [
            "PLURAL_GATEWAY_URL",
            "OPENAI_BASE_URL",
            "PLURAL_ALLOW_NO_AUTH",
        ],
        "outputs": [{"path": "result.json"}],
        "artifacts": [{"path": "trajectory.jsonl"}],
        "trajectory": "trajectory.jsonl",
    }
    config = _create(directory / "harness.yaml", harness, force=force)
    runner = directory / "harness.py"
    if runner.exists() and not force:
        raise FileExistsError(f"{runner} already exists; pass --force to replace it")
    runner.write_text(
        (Path(__file__).parents[1] / "harness" / "native_runner.py").read_text(encoding="utf-8"),
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
    package = (
        load_harness_reference(str(harness_path), digest=harness_digest)
        if harness_path is not None
        else None
    )
    agent: dict[str, Any] = {
        "kind": "agent",
        "name": name,
        "version": "0.1.0",
        "model": model,
        "secret_names": list(secret_names),
    }
    target = _target(path, "agent.yaml")
    if package is not None:
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
    """Compatibility adapter from the public loader to the engine definition."""
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


def load_task(path: Path) -> TaskDefinition:
    """Compatibility adapter from the public loader to the engine definition."""
    source = _target(path, "task.yaml")
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Task):
        raise TypeError(f"{source} is not a Task")
    return value._definition()


def load_benchmark(path: Path) -> BenchmarkDefinition:
    """Compatibility adapter from the public loader to the engine definition."""
    source = _target(path, "benchmark.yaml")
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Benchmark):
        raise TypeError(f"{source} is not a Benchmark")
    return value._definition()


def load_agent(path: Path) -> AgentDefinition:
    """Compatibility adapter from the public loader to the engine definition."""
    source = _target(path, "agent.yaml")
    value = Resolver(root=source.parent).load(source.name)
    if not isinstance(value, Agent):
        raise TypeError(f"{source} is not an Agent")
    return value._definition()


def load_job(path: Path) -> JobSpec:
    """Compatibility adapter from the public loader to the engine spec."""
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
    if path.exists() and (path.is_dir() or path.suffix in {".yaml", ".yml"}):
        return load_harness(path)
    if digest is None:
        raise ValueError("archive Harness references require --digest")
    package = package_from_archive(reference, digest, cache_root=cache_root)
    definition = package.definition
    return Harness(
        name=definition.name,
        version=definition.revision,
        description=definition.description,
        command=definition.command,
        source=reference,
        digest=digest,
        requirements=definition.requirements,
        capabilities=definition.capabilities,
        models=definition.supported_models,
        auth=definition.auth_modes,
        secrets=definition.secret_names,
        environment=definition.environment_names,
        healthcheck=definition.healthcheck,
        outputs=tuple(HarnessOutput(**item.model_dump()) for item in definition.outputs),
        artifacts=tuple(HarnessOutput(**item.model_dump()) for item in definition.artifacts),
        trajectory=definition.trajectory_path,
        tito=definition.tito_path,
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
    "generate_schemas",
    "load_agent",
    "load_benchmark",
    "load_environment",
    "load_harness",
    "load_harness_reference",
    "load_job",
    "load_task",
    "load_verifier",
    "read_yaml",
    "scaffold_agent",
    "scaffold_benchmark",
    "scaffold_environment",
    "scaffold_harness",
    "scaffold_job",
    "scaffold_task",
    "scaffold_verifier",
    "write_yaml",
]
