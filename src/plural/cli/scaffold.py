"""Scaffolding, YAML loading, strict validation, and schema generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from plural.domain import (
    AgentSpec,
    BenchmarkDefinition,
    EnvironmentManifest,
    HarnessBinding,
    HarnessPackage,
    JobSpec,
    PackageSource,
    RetryPolicy,
    RuntimeSpec,
    TaskDefinition,
)
from plural.harness.retrieval import package_from_archive, tree_digest


class JobFile(BaseModel):
    """Path-based local job config resolved into an immutable JobSpec."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1"
    environment: Path = Path("environment.yaml")
    benchmark: Path = Path("benchmark.yaml")
    agents: tuple[Path, ...] = Field(min_length=1)
    n_attempts: int = Field(default=1, ge=1)
    concurrency: int = Field(default=1, ge=1)
    per_agent_concurrency: int = Field(default=1, ge=1)
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)


def read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return dict(payload)


def write_yaml(path: Path, payload: Any) -> None:
    """Write deterministic, human-readable YAML."""
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", exclude_none=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _target(path: Path, default_name: str) -> Path:
    return path if path.suffix in {".yaml", ".yml"} else path / default_name


def _create(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scaffold_environment(directory: Path, name: str, *, force: bool = False) -> list[Path]:
    """Create a minimal environment package."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": "1",
        "name": name,
        "revision": "0.1.0",
        "description": "",
        "instructions": "Complete the task using only the declared commands and context.",
        "context": None,
        "commands": [],
        "limits": {"max_turns": 8, "max_seconds": 120},
        "policy": {},
        "tasks": [],
        "allowed_harnesses": [],
        "runtime_capabilities": [],
    }
    environment_yaml = directory / "environment.yaml"
    _create(
        environment_yaml,
        yaml.safe_dump(manifest, sort_keys=False),
        force=force,
    )
    _create(
        directory / "environment.py",
        (
            "from plural import Environment\n\n\n"
            "class ProjectEnvironment(Environment):\n"
            f'    name = "{name}"\n'
            '    version = "0.1.0"\n'
        ),
        force=force,
    )
    task = {"task_id": "example", "input": "Replace this example task."}
    _create(
        directory / "tasks.jsonl",
        json.dumps(task, sort_keys=True) + "\n",
        force=force,
    )
    _create(
        directory / "Dockerfile",
        (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY . /app\n"
            'CMD ["python", "-c", "print(\'environment package ready\')"]\n'
        ),
        force=force,
    )
    return [
        environment_yaml,
        directory / "environment.py",
        directory / "tasks.jsonl",
        directory / "Dockerfile",
    ]


def scaffold_harness(directory: Path, name: str, *, force: bool = False) -> list[Path]:
    """Create a trusted local harness package manifest."""
    directory.mkdir(parents=True, exist_ok=True)
    package = {
        "manifest": {
            "schema_version": "1",
            "name": name,
            "version": "0.1.0",
            "description": "",
            "protocol": "plural-harness-v1",
            "command": ["python", "harness.py", "chat.v1"],
            "requirements": [
                "OpenAI-compatible POST /chat/completions endpoint",
                "PLURAL_API_KEY or OPENAI_API_KEY unless explicitly unauthenticated",
            ],
            "capabilities": ["chat"],
            "secret_names": ["PLURAL_API_KEY", "OPENAI_API_KEY"],
            "environment_names": [
                "PLURAL_GATEWAY_URL",
                "OPENAI_BASE_URL",
                "PLURAL_ALLOW_NO_AUTH",
            ],
            "outputs": [{"path": "result.json", "required": True}],
            "artifacts": [{"path": "trajectory.jsonl", "required": True}],
            "trajectory_path": "trajectory.jsonl",
        },
        "source": {
            "kind": "local",
            "uri": ".",
            "trusted": False,
            "unsafe_local": True,
        },
    }
    manifest = directory / "harness.yaml"
    _create(manifest, yaml.safe_dump(package, sort_keys=False), force=force)
    _create(
        directory / "harness.py",
        (Path(__file__).parents[1] / "harness" / "builtin_runner.py").read_text(encoding="utf-8"),
        force=force,
    )
    return [manifest, directory / "harness.py"]


def scaffold_benchmark(
    path: Path,
    *,
    name: str,
    environment_path: Path,
    force: bool = False,
) -> Path:
    """Create a benchmark selecting environment tasks in file order."""
    environment = load_environment(environment_path)
    benchmark = BenchmarkDefinition(
        name=name,
        environment=environment.identity,
        task_ids=tuple(task.task_id for task in environment.tasks),
    )
    destination = _target(path, "benchmark.yaml")
    if destination.exists() and not force:
        raise FileExistsError(f"{destination} already exists; pass --force to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(destination, benchmark)
    return destination


def scaffold_agent(
    path: Path,
    *,
    name: str,
    model: str,
    environment_path: Path,
    harness_path: Path | str,
    harness_digest: str | None = None,
    secret_names: tuple[str, ...] = (),
    force: bool = False,
) -> Path:
    """Create an agent bound to one exact environment and harness."""
    environment = load_environment(environment_path)
    harness = load_harness_reference(str(harness_path), digest=harness_digest)
    agent = AgentSpec(
        name=name,
        model=model,
        environment=environment.identity,
        harness=harness_binding(harness),
        harness_package=harness,
        secret_names=secret_names,
    )
    destination = _target(path, "agent.yaml")
    if destination.exists() and not force:
        raise FileExistsError(f"{destination} already exists; pass --force to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(destination, agent)
    return destination


def scaffold_job(
    path: Path,
    *,
    environment_path: Path,
    benchmark_path: Path,
    agent_paths: tuple[Path, ...],
    force: bool = False,
) -> Path:
    """Create a path-based local job config."""
    job_file = JobFile(
        environment=environment_path,
        benchmark=benchmark_path,
        agents=agent_paths,
    )
    destination = _target(path, "job.yaml")
    if destination.exists() and not force:
        raise FileExistsError(f"{destination} already exists; pass --force to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(destination, job_file)
    return destination


def load_environment(path: Path) -> EnvironmentManifest:
    """Load an environment YAML and its conventional tasks.jsonl."""
    source = _target(path, "environment.yaml")
    payload = read_yaml(source)
    tasks = payload.get("tasks")
    task_path = source.parent / "tasks.jsonl"
    if (tasks is None or tasks == []) and task_path.exists():
        tasks = [
            json.loads(line)
            for line in task_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        payload["tasks"] = tasks
    environment = EnvironmentManifest.model_validate(payload)
    package_root = source.parent.resolve()
    return environment.model_copy(
        update={
            "source": PackageSource(
                kind="local",
                uri=str(package_root),
                digest=tree_digest(package_root),
                trusted=True,
            )
        }
    )


def load_harness(path: Path) -> HarnessPackage:
    """Load and strictly validate a harness package manifest."""
    source = _target(path, "harness.yaml").resolve()
    payload = read_yaml(source)
    package_source = payload.get("source")
    if isinstance(package_source, dict) and package_source.get("kind") == "local":
        package_path = Path(str(package_source.get("uri", "."))).expanduser()
        if not package_path.is_absolute():
            package_path = (source.parent / package_path).resolve()
        package_source["uri"] = str(package_path)
        package_source["digest"] = tree_digest(package_path)
    return HarnessPackage.model_validate(payload)


def load_harness_reference(
    reference: str,
    *,
    digest: str | None = None,
    cache_root: Path | None = None,
) -> HarnessPackage:
    """Load a local manifest or immutable archive reference."""
    parsed_path = Path(reference).expanduser()
    if parsed_path.exists() and (parsed_path.is_dir() or parsed_path.suffix in {".yaml", ".yml"}):
        return load_harness(parsed_path)
    if digest is None:
        raise ValueError("archive/HTTPS harness references require --digest sha256:<hex>")
    return package_from_archive(reference, digest, cache_root=cache_root)


def harness_binding(package: HarnessPackage) -> HarnessBinding:
    """Return the exact binding represented by a package."""
    return HarnessBinding.from_package(package)


def load_benchmark(path: Path) -> BenchmarkDefinition:
    """Load and strictly validate a benchmark definition."""
    return BenchmarkDefinition.model_validate(read_yaml(_target(path, "benchmark.yaml")))


def load_agent(path: Path) -> AgentSpec:
    """Load and strictly validate an agent config."""
    return AgentSpec.model_validate(read_yaml(_target(path, "agent.yaml")))


def load_job(path: Path) -> JobSpec:
    """Resolve a path-based job file into a validated immutable JobSpec."""
    source = _target(path, "job.yaml")
    config = JobFile.model_validate(read_yaml(source))

    def resolve(value: Path) -> Path:
        return value if value.is_absolute() else source.parent / value

    environment_path = resolve(config.environment)
    runtime = config.runtime
    if runtime.provider == "docker" and runtime.image is None and runtime.build_context is None:
        environment_source = _target(environment_path, "environment.yaml")
        runtime = runtime.model_copy(
            update={"build_context": str(environment_source.parent.resolve())}
        )
    return JobSpec(
        environment=load_environment(environment_path),
        benchmark=load_benchmark(resolve(config.benchmark)),
        agents=tuple(load_agent(resolve(agent)) for agent in config.agents),
        n_attempts=config.n_attempts,
        concurrency=config.concurrency,
        per_agent_concurrency=config.per_agent_concurrency,
        runtime=runtime,
        retry=config.retry,
    )


def add_task(environment_path: Path, task: TaskDefinition) -> Path:
    """Append an environment-owned task to conventional tasks.jsonl."""
    source = _target(environment_path, "environment.yaml")
    environment = load_environment(source)
    if task.task_id in {item.task_id for item in environment.tasks}:
        raise ValueError(f"task {task.task_id!r} already exists")
    task_path = source.parent / "tasks.jsonl"
    with task_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(task.model_dump(mode="json"), sort_keys=True) + "\n")
    return task_path


def allow_harness(environment_path: Path, harness_path: Path) -> Path:
    """Add an exact harness binding to an environment manifest."""
    return allow_harness_package(environment_path, load_harness(harness_path))


def allow_harness_package(
    environment_path: Path,
    package: HarnessPackage,
) -> Path:
    """Add an already-resolved harness package to an environment allowlist."""
    source = _target(environment_path, "environment.yaml")
    payload = read_yaml(source)
    binding = harness_binding(package)
    values = list(payload.get("allowed_harnesses") or [])
    dumped = binding.model_dump(mode="json")
    if dumped not in values:
        values.append(dumped)
    payload["allowed_harnesses"] = values
    write_yaml(source, payload)
    load_environment(source)
    return source


def generate_schemas(directory: Path) -> list[Path]:
    """Generate JSON schemas for core public package configs."""
    models: tuple[type[BaseModel], ...] = (
        HarnessPackage,
        EnvironmentManifest,
        BenchmarkDefinition,
        AgentSpec,
        JobSpec,
    )
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for model in models:
        path = directory / f"{model.__name__}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


__all__ = [
    "JobFile",
    "add_task",
    "allow_harness",
    "allow_harness_package",
    "generate_schemas",
    "load_agent",
    "load_benchmark",
    "load_environment",
    "load_harness",
    "load_harness_reference",
    "load_job",
    "read_yaml",
    "scaffold_agent",
    "scaffold_benchmark",
    "scaffold_environment",
    "scaffold_harness",
    "scaffold_job",
    "write_yaml",
]
