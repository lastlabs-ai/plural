"""Schema-v2 package scaffolding, loading, and generated schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from plural.domain import (
    AgentBinding,
    AgentDefinition,
    AgentVerifier,
    BenchmarkDefinition,
    BenchmarkJobSource,
    DeterministicVerifier,
    EnvironmentManifest,
    EnvironmentRuntime,
    HarnessBinding,
    HarnessPackage,
    HumanVerifier,
    JobMode,
    JobSpec,
    PackageSource,
    RubricCriterion,
    TaskDefinition,
    TaskJobSource,
    VerifierDefinition,
    WeightedVerifier,
)
from plural.harness.retrieval import package_from_archive, tree_digest


class StrictFile(BaseModel):
    """Strict immutable path-reference file."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TaskFile(StrictFile):
    """Authoring file for one Task revision."""

    schema_version: Literal["2"] = "2"
    task_id: str
    revision: str = "0.1.0"
    instructions: str
    environment: Path
    verifiers: tuple[Path, ...] = Field(min_length=1)
    verifier_weights: tuple[float, ...] = ()
    info: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkFile(StrictFile):
    """Authoring file for a cross-Environment Benchmark."""

    schema_version: Literal["2"] = "2"
    name: str
    revision: str = "0.1.0"
    tasks: tuple[Path, ...] = Field(min_length=1)
    primary_metric: str = "reward"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobFile(StrictFile):
    """Path-based Job selecting a Benchmark or Task."""

    schema_version: Literal["2"] = "2"
    source_kind: Literal["benchmark", "task"]
    source: Path
    agents: tuple[Path, ...] = Field(min_length=1)
    mode: JobMode = JobMode.EVAL
    attempts: int = Field(default=1, ge=1)
    concurrency: int = Field(default=1, ge=1)
    per_runtime_concurrency: int = Field(default=1, ge=1)
    priority: int = 0


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
    """Create a standalone schema-v2 Environment package."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest = EnvironmentManifest(
        name=name,
        overview="A typed runtime world with declared actions and observable state.",
        runtime=EnvironmentRuntime(),
    )
    environment_yaml = _create(
        directory / "environment.yaml",
        manifest.model_dump(mode="json", exclude={"source"}),
        force=force,
    )
    environment_py = directory / "environment.py"
    if environment_py.exists() and not force:
        raise FileExistsError(f"{environment_py} already exists; pass --force to replace it")
    environment_py.write_text(
        "from plural import Environment\n\n\n"
        "class ProjectEnvironment(Environment):\n"
        f'    name = "{name}"\n'
        '    revision = "0.1.0"\n',
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
            command=("python", "verify.py"),
        )
    elif kind == "agent":
        verifier = AgentVerifier(
            name=name,
            model="openai/gpt-4.1-mini",
            instructions="Score the submitted result against the rubric.",
            rubric=(
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
            rubric=(
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
    task = TaskFile(
        task_id=task_id,
        instructions="Complete the task described in info.",
        environment=environment_path,
        verifiers=verifier_paths,
        info={"prompt": "Replace this example."},
    )
    return _create(_target(path, "task.yaml"), task, force=force)


def scaffold_harness(directory: Path, name: str, *, force: bool = False) -> list[Path]:
    """Create a runnable standalone Harness package."""
    directory.mkdir(parents=True, exist_ok=True)
    package = {
        "manifest": {
            "schema_version": "2",
            "name": name,
            "revision": "0.1.0",
            "implementation": "runnable",
            "command": ["python", "harness.py", "native.chat.v1"],
            "capabilities": ["shell"],
            "secret_names": ["PLURAL_API_KEY", "OPENAI_API_KEY"],
            "environment_names": [
                "PLURAL_GATEWAY_URL",
                "OPENAI_BASE_URL",
                "PLURAL_ALLOW_NO_AUTH",
            ],
            "outputs": [{"path": "result.json"}],
            "artifacts": [{"path": "trajectory.jsonl"}],
            "trajectory_path": "trajectory.jsonl",
        },
        "source": {"kind": "local", "uri": ".", "unsafe_local": True},
    }
    manifest = _create(directory / "harness.yaml", package, force=force)
    runner = directory / "harness.py"
    if runner.exists() and not force:
        raise FileExistsError(f"{runner} already exists; pass --force to replace it")
    runner.write_text(
        (Path(__file__).parents[1] / "harness" / "native_runner.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return [manifest, runner]


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
    agent = AgentDefinition(
        name=name,
        model=model,
        harness=HarnessBinding.from_package(package) if package else None,
        harness_package=package,
        secret_names=secret_names,
    )
    return _create(_target(path, "agent.yaml"), agent, force=force)


def scaffold_benchmark(
    path: Path,
    *,
    name: str,
    task_paths: tuple[Path, ...] = (),
    force: bool = False,
    **_: Any,
) -> Path:
    """Create a cross-Environment Benchmark reference file."""
    if not task_paths:
        raise ValueError("schema-v2 Benchmark requires at least one --task")
    return _create(
        _target(path, "benchmark.yaml"),
        BenchmarkFile(name=name, tasks=task_paths),
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
    """Create a path-based Job."""
    source = source_path or benchmark_path
    if source is None:
        raise ValueError("Job requires a Task or Benchmark source")
    return _create(
        _target(path, "job.yaml"),
        JobFile(source_kind=source_kind, source=source, agents=agent_paths),
        force=force,
    )


def load_environment(path: Path) -> EnvironmentManifest:
    """Load one canonical Environment manifest and lock its local source."""
    source = _target(path, "environment.yaml")
    payload = read_yaml(source)
    environment = EnvironmentManifest.model_validate(payload)
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
    """Load one discriminated Verifier."""
    adapter = Annotated[
        DeterministicVerifier | AgentVerifier | HumanVerifier,
        Field(discriminator="kind"),
    ]
    from pydantic import TypeAdapter

    return TypeAdapter(adapter).validate_python(read_yaml(_target(path, "verifier.yaml")))


def _resolve(base: Path, value: Path) -> Path:
    return value if value.is_absolute() else base / value


def load_task(path: Path) -> TaskDefinition:
    """Resolve one Task and all pinned revision dependencies."""
    source = _target(path, "task.yaml")
    config = TaskFile.model_validate(read_yaml(source))
    weights = config.verifier_weights or tuple(1.0 for _ in config.verifiers)
    if len(weights) != len(config.verifiers):
        raise ValueError("verifier_weights must match verifiers")
    return TaskDefinition(
        task_id=config.task_id,
        revision=config.revision,
        instructions=config.instructions,
        environment=load_environment(_resolve(source.parent, config.environment)),
        verifiers=tuple(
            WeightedVerifier(
                verifier=load_verifier(_resolve(source.parent, verifier)),
                weight=weight,
            )
            for verifier, weight in zip(config.verifiers, weights, strict=True)
        ),
        info=config.info,
        metadata=config.metadata,
    )


def load_benchmark(path: Path) -> BenchmarkDefinition:
    """Resolve a cross-Environment Benchmark."""
    source = _target(path, "benchmark.yaml")
    config = BenchmarkFile.model_validate(read_yaml(source))
    return BenchmarkDefinition(
        name=config.name,
        revision=config.revision,
        tasks=tuple(load_task(_resolve(source.parent, task)) for task in config.tasks),
        primary_metric=config.primary_metric,
        description=config.description,
        metadata=config.metadata,
    )


def load_agent(path: Path) -> AgentDefinition:
    """Load an Agent revision."""
    return AgentDefinition.model_validate(read_yaml(_target(path, "agent.yaml")))


def load_job(path: Path) -> JobSpec:
    """Resolve one path-based schema-v2 Job."""
    source = _target(path, "job.yaml")
    config = JobFile.model_validate(read_yaml(source))
    resolved_source = _resolve(source.parent, config.source)
    job_source = (
        TaskJobSource(task=load_task(resolved_source))
        if config.source_kind == "task"
        else BenchmarkJobSource(benchmark=load_benchmark(resolved_source))
    )
    return JobSpec(
        source=job_source,
        agents=tuple(
            AgentBinding(agent=load_agent(_resolve(source.parent, item))) for item in config.agents
        ),
        mode=config.mode,
        attempts=config.attempts,
        concurrency=config.concurrency,
        per_runtime_concurrency=config.per_runtime_concurrency,
        priority=config.priority,
    )


def load_harness(path: Path) -> HarnessPackage:
    """Load and lock a local Harness package."""
    source = _target(path, "harness.yaml").resolve()
    payload = read_yaml(source)
    package_source = payload.get("source")
    if isinstance(package_source, dict) and package_source.get("kind") == "local":
        root = Path(str(package_source.get("uri", "."))).expanduser()
        if not root.is_absolute():
            root = (source.parent / root).resolve()
        package_source["uri"] = str(root)
        package_source["digest"] = tree_digest(root)
    return HarnessPackage.model_validate(payload)


def load_harness_reference(
    reference: str,
    *,
    digest: str | None = None,
    cache_root: Path | None = None,
) -> HarnessPackage:
    """Load a local Harness or immutable archive."""
    path = Path(reference).expanduser()
    if path.exists() and (path.is_dir() or path.suffix in {".yaml", ".yml"}):
        return load_harness(path)
    if digest is None:
        raise ValueError("archive Harness references require --digest")
    return package_from_archive(reference, digest, cache_root=cache_root)


def generate_schemas(directory: Path) -> list[Path]:
    """Generate canonical schema-v2 JSON schemas."""
    models: tuple[type[BaseModel], ...] = (
        EnvironmentManifest,
        TaskDefinition,
        DeterministicVerifier,
        AgentVerifier,
        HumanVerifier,
        AgentDefinition,
        BenchmarkDefinition,
        JobSpec,
    )
    directory.mkdir(parents=True, exist_ok=True)
    output = []
    for model in models:
        path = directory / f"{model.__name__}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output.append(path)
    return output


__all__ = [
    "BenchmarkFile",
    "JobFile",
    "TaskFile",
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
