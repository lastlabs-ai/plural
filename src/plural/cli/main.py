"""Plural SDK/YAML/CLI entry point."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Literal, NoReturn

import typer
import yaml
from pydantic import BaseModel, ValidationError

from plural.agents import Agent
from plural.catalog import ModelCatalog
from plural.cli.auth import AuthClient
from plural.cli.config import default_credential_store, resolve_context
from plural.cli.hosted_run import sync_and_submit, validate_hosted_graph
from plural.cli.scaffold import (
    generate_schemas,
    load_agent,
    load_benchmark,
    load_environment,
    load_harness,
    load_job,
    load_task,
    load_verifier,
    scaffold_agent,
    scaffold_benchmark,
    scaffold_environment,
    scaffold_harness,
    scaffold_job,
    scaffold_task,
    scaffold_verifier,
)
from plural.client import Client
from plural.config import resolve_gateway_url
from plural.errors import PluralError
from plural.execution import JobRunner, JobStore
from plural.jobs import Job as PublicJob
from plural.jobs import JobMode
from plural.project import CatalogContext, Resolver
from plural.tasks import Benchmark, Task

app = typer.Typer(
    name="plural",
    help="Define environments, evaluate agents, and inspect reproducible results.",
    no_args_is_help=True,
)
env_app = typer.Typer(help="Compatibility Environment commands.")
task_app = typer.Typer(help="Compatibility Task commands.")
verifier_app = typer.Typer(help="Compatibility Verifier commands.")
agent_app = typer.Typer(help="Compatibility Agent commands.")
harness_app = typer.Typer(help="Advanced Harness commands.")
benchmark_app = typer.Typer(help="Compatibility Benchmark commands.")
models_app = typer.Typer(help="List and inspect the effective model catalog.")
benchmarks_app = typer.Typer(help="Inspect, compare, and export Benchmarks.")
auth_app = typer.Typer(help="Authenticate with hosted Plural services.")
job_app = typer.Typer(help="Advanced durable Job and event commands.")
trial_app = typer.Typer(help="Inspect and watch Trials.")
review_app = typer.Typer(help="Inspect and submit human reviews.")
for name, group in (
    ("env", env_app),
    ("task", task_app),
    ("verifier", verifier_app),
    ("agent", agent_app),
    ("harness", harness_app),
    ("benchmark", benchmark_app),
):
    app.add_typer(group, name=name, hidden=True)
for name, group in (
    ("models", models_app),
    ("benchmarks", benchmarks_app),
    ("auth", auth_app),
    ("job", job_app),
    ("trial", trial_app),
    ("review", review_app),
):
    app.add_typer(group, name=name)


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def _emit(value: Any, fmt: str = "json") -> None:
    payload = _dump(value)
    if fmt == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif fmt == "yaml":
        typer.echo(yaml.safe_dump(payload, sort_keys=False).rstrip())
    else:
        typer.echo(str(payload))


def _error(message: str) -> NoReturn:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(2)


def _validated(loader: Any, path: Path) -> Any:
    try:
        return loader(path)
    except (OSError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        _error(str(exc))


def _catalog(path: Path | None) -> ModelCatalog:
    return CatalogContext.from_file(path).catalog if path is not None else ModelCatalog()


def _project_resolver(reference: str, catalog: Path | None = None) -> Resolver:
    path_text = reference.rsplit(":", 1)[0] if ".py:" in reference else reference
    source = Path(path_text).expanduser()
    root = source.resolve().parent if source.parent != Path("") else Path.cwd()
    return Resolver(root=root, catalog=_catalog(catalog))


def _load_public(reference: str, catalog: Path | None = None) -> Any:
    resolver = _project_resolver(reference, catalog)
    path = Path(reference.rsplit(":", 1)[0])
    local = path.name
    if ":" in reference:
        local += ":" + reference.rsplit(":", 1)[1]
    try:
        return resolver.load(local)
    except (OSError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        _error(str(exc))


def _client() -> Client:
    try:
        ctx = resolve_context(credentials=default_credential_store())
        if not ctx.api_key:
            raise PluralError("not authenticated; run `plural auth login` or set PLURAL_API_KEY")
        gateway = os.environ.get("PLURAL_GATEWAY_URL") or ctx.api_url
        return Client(
            api_key=ctx.api_key,
            base_url=resolve_gateway_url(gateway),
            project=ctx.project,
        )
    except (OSError, ValueError, PluralError) as exc:
        _error(str(exc))


def _emit_event(event: Any, *, json_events: bool) -> None:
    payload = _dump(event)
    if json_events:
        typer.echo(json.dumps(payload, separators=(",", ":"), default=str))
        return
    if not isinstance(payload, dict):
        typer.echo(str(payload))
        return
    nested = payload.get("payload")
    event_data = nested if isinstance(nested, dict) else {}
    sequence = payload.get("sequence", 0)
    status = payload.get("status") or payload.get("phase") or payload.get("kind") or ""
    trial_id = payload.get("trial_id") or event_data.get("trial_id")
    target = f" {trial_id}" if trial_id else ""
    message = payload.get("message") or ""
    try:
        sequence_text = f"{int(sequence):>5}"
    except (TypeError, ValueError):
        sequence_text = str(sequence)
    typer.echo(f"{sequence_text} {str(status):<16}{target} {message}".rstrip())


@app.command("init")
def init(
    path: Path = typer.Argument(Path("."), help="Project directory."),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a small Python-first evaluation project."""
    path.mkdir(parents=True, exist_ok=True)
    project_py = path / "project.py"
    project_yaml = path / "project.yaml"
    if not force and (project_py.exists() or project_yaml.exists()):
        _error("project files already exist; pass --force to replace them")
    project_py.write_text(
        "from plural import Agent, Benchmark, Environment, Job, Task\n"
        "from plural.verifiers import DeterministicVerifier\n\n"
        'environment = Environment(name="example")\n'
        'verifier = DeterministicVerifier(name="complete", check="python verify.py")\n'
        'task = Task(name="example", instructions="Complete the task.", '
        "environment=environment, verifiers=[verifier])\n"
        'benchmark = Benchmark(name="example", version="1.0.0", tasks=[task])\n'
        'agent = Agent(model="openai/gpt-5.6-luna")\n'
        "job = Job(benchmark, agents=[agent])\n",
        encoding="utf-8",
    )
    project_yaml.write_text(
        "kind: job\nsource: project.py:benchmark\nagents:\n  - project.py:agent\n",
        encoding="utf-8",
    )
    _emit({"created": [str(project_py), str(project_yaml)]})


@app.command("validate")
def validate(
    reference: str = typer.Argument(..., metavar="REF"),
    catalog: Path | None = typer.Option(None, "--catalog"),
) -> None:
    """Load and validate any Python or YAML project object."""
    value = _load_public(reference, catalog)
    _emit(
        {
            "valid": True,
            "type": type(value).__name__,
            "content_hash": getattr(value, "content_hash", None),
        }
    )


@app.command("inspect")
def inspect_project(
    reference: str = typer.Argument(..., metavar="REF"),
    catalog: Path | None = typer.Option(None, "--catalog"),
    output_format: Literal["json", "yaml"] = typer.Option("yaml", "--format"),
) -> None:
    """Show the fully resolved public object graph."""
    value = _load_public(reference, catalog)
    resolver = _project_resolver(reference, catalog)
    payload = yaml.safe_load(resolver.dumps(value))
    _emit(payload, output_format)


@app.command("export")
def export_project(
    reference: str = typer.Argument(..., metavar="REF"),
    output: Path = typer.Option(..., "--output", "-o"),
    catalog: Path | None = typer.Option(None, "--catalog"),
) -> None:
    """Export the resolved graph as canonical public YAML."""
    value = _load_public(reference, catalog)
    try:
        Resolver(root=output.resolve().parent, catalog=_catalog(catalog)).dump(value, output.name)
    except (OSError, TypeError, ValueError) as exc:
        _error(str(exc))
    _emit({"output": str(output), "content_hash": getattr(value, "content_hash", None)})


@models_app.command("list")
def models_list(catalog: Path | None = typer.Option(None, "--catalog")) -> None:
    """List models in the effective bundled plus project catalog."""
    _emit(
        [
            {
                "id": model.id,
                "name": model.name,
                "providers": model.host_providers(),
            }
            for model in sorted(_catalog(catalog).models(), key=lambda item: item.id)
        ]
    )


@models_app.command("show")
def models_show(
    model_id: str,
    catalog: Path | None = typer.Option(None, "--catalog"),
) -> None:
    """Show one effective catalog model."""
    try:
        _emit(_catalog(catalog).require(model_id))
    except PluralError as exc:
        _error(str(exc))


@benchmarks_app.command("show")
def benchmarks_show(
    reference: str = typer.Argument(..., metavar="REF"),
    catalog: Path | None = typer.Option(None, "--catalog"),
) -> None:
    """Show one resolved Benchmark."""
    value = _load_public(reference, catalog)
    if not isinstance(value, Benchmark):
        _error(f"{reference} is not a Benchmark")
    _emit(value.export())


@benchmarks_app.command("diff")
def benchmarks_diff(
    before: str,
    after: str,
    catalog: Path | None = typer.Option(None, "--catalog"),
) -> None:
    """Compare two resolved Benchmark versions."""
    first = _load_public(before, catalog)
    second = _load_public(after, catalog)
    if not isinstance(first, Benchmark) or not isinstance(second, Benchmark):
        _error("benchmarks diff requires two Benchmark references")
    _emit(first.diff(second))


@benchmarks_app.command("export")
def benchmarks_export(
    reference: str = typer.Argument(..., metavar="REF"),
    output: Path = typer.Option(..., "--output", "-o"),
    catalog: Path | None = typer.Option(None, "--catalog"),
) -> None:
    """Write a Benchmark and its pinned dependency graph."""
    value = _load_public(reference, catalog)
    if not isinstance(value, Benchmark):
        _error(f"{reference} is not a Benchmark")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(value.export(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    _emit({"output": str(output), "content_hash": value.content_hash})


@auth_app.command("login")
def auth_login(no_browser: bool = typer.Option(False, "--no-browser")) -> None:
    """Authenticate using the hosted device flow."""
    context = resolve_context(credentials=default_credential_store())
    store = default_credential_store()
    try:
        with AuthClient(context.api_url) as client:
            _device, tokens = client.login(
                no_browser=no_browser,
                on_device=lambda device: typer.echo(
                    f"Open {device.verification_uri} and enter {device.user_code}"
                ),
            )
        store.set(context.profile, tokens.credential())
    except (OSError, ValueError, PluralError) as exc:
        _error(str(exc))
    _emit({"authenticated": True, "profile": context.profile})


@auth_app.command("logout")
def auth_logout() -> None:
    """Remove stored credentials for the active profile."""
    context = resolve_context(credentials=default_credential_store())
    default_credential_store().delete(context.profile)
    _emit({"authenticated": False, "profile": context.profile})


@auth_app.command("status")
def auth_status() -> None:
    """Show local authentication context without exposing secrets."""
    _emit(resolve_context(credentials=default_credential_store()).redacted())


@env_app.command("init")
def env_init(
    path: Path = typer.Argument(Path(".")),
    name: str = typer.Option("environment", "--name"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a standalone Environment package."""
    try:
        files = scaffold_environment(path, name, force=force)
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": [str(item) for item in files]})


@env_app.command("validate")
def env_validate(path: Path = typer.Argument(Path("."))) -> None:
    """Validate a canonical Environment."""
    environment = _validated(load_environment, path)
    _emit({"valid": True, "digest": environment.content_hash})


@env_app.command("show")
def env_show(path: Path = typer.Argument(Path("."))) -> None:
    """Show a canonical Environment."""
    _emit(_validated(load_environment, path))


@env_app.command("push")
def env_push(path: Path = typer.Argument(Path("."))) -> None:
    """Publish an Environment parent and immutable revision."""
    with _client() as client:
        _emit(client.environments.push(_validated(load_environment, path)))


@env_app.command("publish")
def env_publish(resource_id: str, revision_id: str) -> None:
    """Publish an existing hosted Environment revision."""
    with _client() as client:
        _emit(client.environments.publish_revision(resource_id, revision_id))


@task_app.command("init")
def task_init(
    path: Path = typer.Argument(Path("task.yaml")),
    task_id: str = typer.Option("task", "--id"),
    environment: Path = typer.Option(..., "--environment", "-e"),
    verifier: list[Path] = typer.Option(..., "--verifier", "-v"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a Task pinned to an Environment and Verifiers."""
    try:
        created = scaffold_task(
            path,
            task_id=task_id,
            environment_path=environment,
            verifier_paths=tuple(verifier),
            force=force,
        )
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": str(created)})


@task_app.command("validate")
def task_validate(path: Path = typer.Argument(Path("task.yaml"))) -> None:
    """Validate a complete Task revision graph."""
    task = _validated(load_task, path)
    _emit({"valid": True, "digest": task.content_hash})


@task_app.command("show")
def task_show(path: Path = typer.Argument(Path("task.yaml"))) -> None:
    """Show a resolved Task."""
    _emit(_validated(load_task, path))


@task_app.command("push")
def task_push(
    path: Path = typer.Argument(Path("task.yaml")),
    environment_revision_id: str = typer.Option(..., "--environment-revision-id"),
    verifier_revision_id: list[str] = typer.Option(..., "--verifier-revision-id"),
) -> None:
    """Publish a Task revision with exact hosted dependencies."""
    with _client() as client:
        _emit(
            client.tasks.push(
                _validated(load_task, path),
                environment_revision_id=environment_revision_id,
                verifier_revision_ids=verifier_revision_id,
            )
        )


@task_app.command("publish")
def task_publish(resource_id: str, revision_id: str) -> None:
    """Publish an existing hosted Task revision."""
    with _client() as client:
        _emit(client.tasks.publish_revision(resource_id, revision_id))


@verifier_app.command("init")
def verifier_init(
    path: Path = typer.Argument(Path("verifier.yaml")),
    name: str = typer.Option("verifier", "--name"),
    kind: Literal["deterministic", "agent", "human"] = typer.Option("deterministic", "--kind"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a deterministic, agent, or human Verifier."""
    try:
        created = scaffold_verifier(path, name=name, kind=kind, force=force)
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": str(created)})


@verifier_app.command("validate")
def verifier_validate(path: Path = typer.Argument(Path("verifier.yaml"))) -> None:
    """Validate a Verifier."""
    verifier = _validated(load_verifier, path)
    _emit({"valid": True, "kind": verifier.kind, "digest": verifier.content_hash})


@verifier_app.command("show")
def verifier_show(path: Path = typer.Argument(Path("verifier.yaml"))) -> None:
    """Show a Verifier."""
    _emit(_validated(load_verifier, path))


@verifier_app.command("push")
def verifier_push(path: Path = typer.Argument(Path("verifier.yaml"))) -> None:
    """Publish a Verifier parent and immutable revision."""
    with _client() as client:
        _emit(client.verifiers.push(_validated(load_verifier, path)))


@verifier_app.command("publish")
def verifier_publish(resource_id: str, revision_id: str) -> None:
    """Publish an existing hosted Verifier revision."""
    with _client() as client:
        _emit(client.verifiers.publish_revision(resource_id, revision_id))


@agent_app.command("init")
def agent_init(
    path: Path = typer.Argument(Path("agent.yaml")),
    name: str = typer.Option("agent", "--name"),
    model: str = typer.Option(..., "--model"),
    harness: Path | None = typer.Option(None, "--harness"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create an Agent independent of Environment identity."""
    try:
        created = scaffold_agent(
            path,
            name=name,
            model=model,
            harness_path=harness,
            force=force,
        )
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": str(created)})


@agent_app.command("validate")
def agent_validate(path: Path = typer.Argument(Path("agent.yaml"))) -> None:
    """Validate an Agent."""
    agent = _validated(load_agent, path)
    _emit({"valid": True, "digest": agent.content_hash})


@agent_app.command("show")
def agent_show(path: Path = typer.Argument(Path("agent.yaml"))) -> None:
    """Show an Agent."""
    _emit(_validated(load_agent, path))


@agent_app.command("push")
def agent_push(
    path: Path = typer.Argument(Path("agent.yaml")),
    harness_revision_id: str | None = typer.Option(None, "--harness-revision-id"),
) -> None:
    """Publish an AgentDefinition parent and immutable revision."""
    with _client() as client:
        _emit(
            client.agents.push(
                _validated(load_agent, path),
                harness_revision_id=harness_revision_id,
            )
        )


@agent_app.command("publish")
def agent_publish(resource_id: str, revision_id: str) -> None:
    """Publish an existing hosted Agent revision."""
    with _client() as client:
        _emit(client.agents.publish_revision(resource_id, revision_id))


@harness_app.command("init")
def harness_init(
    path: Path = typer.Argument(Path(".")),
    name: str = typer.Option("harness", "--name"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a Harness package."""
    try:
        created = scaffold_harness(path, name, force=force)
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": [str(item) for item in created]})


@harness_app.command("validate")
def harness_validate(path: Path = typer.Argument(Path("."))) -> None:
    """Validate and lock a Harness."""
    package = _validated(load_harness, path)
    _emit({"valid": True, "digest": package.content_hash})


@harness_app.command("show")
def harness_show(path: Path = typer.Argument(Path("."))) -> None:
    """Show a Harness."""
    _emit(_validated(load_harness, path))


@harness_app.command("push")
def harness_push(path: Path = typer.Argument(Path("."))) -> None:
    """Publish a Harness parent and immutable revision."""
    with _client() as client:
        _emit(client.harnesses.push(_validated(load_harness, path)))


@harness_app.command("publish")
def harness_publish(resource_id: str, revision_id: str) -> None:
    """Publish an existing hosted Harness revision."""
    with _client() as client:
        _emit(client.harnesses.publish_revision(resource_id, revision_id))


@benchmark_app.command("init")
def benchmark_init(
    path: Path = typer.Argument(Path("benchmark.yaml")),
    name: str = typer.Option("benchmark", "--name"),
    task: list[Path] = typer.Option(..., "--task", "-t"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a Benchmark selecting Task revisions across Environments."""
    try:
        created = scaffold_benchmark(path, name=name, task_paths=tuple(task), force=force)
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": str(created)})


@benchmark_app.command("validate")
def benchmark_validate(path: Path = typer.Argument(Path("benchmark.yaml"))) -> None:
    """Validate a complete Benchmark revision graph."""
    benchmark = _validated(load_benchmark, path)
    _emit({"valid": True, "digest": benchmark.content_hash})


@benchmark_app.command("show")
def benchmark_show(path: Path = typer.Argument(Path("benchmark.yaml"))) -> None:
    """Show a resolved Benchmark."""
    _emit(_validated(load_benchmark, path))


@benchmark_app.command("push")
def benchmark_push(
    path: Path = typer.Argument(Path("benchmark.yaml")),
    task_revision_id: list[str] = typer.Option(..., "--task-revision-id"),
) -> None:
    """Publish a cross-Environment Benchmark revision."""
    with _client() as client:
        _emit(
            client.benchmarks.push(
                _validated(load_benchmark, path),
                task_revision_ids=task_revision_id,
            )
        )


@benchmark_app.command("publish")
def benchmark_publish(resource_id: str, revision_id: str) -> None:
    """Publish an existing hosted Benchmark revision."""
    with _client() as client:
        _emit(client.benchmarks.publish_revision(resource_id, revision_id))


@job_app.command("init")
def job_init(
    path: Path = typer.Argument(Path("job.yaml")),
    source: Path = typer.Option(..., "--source"),
    source_kind: Literal["benchmark", "task"] = typer.Option("benchmark", "--source-kind"),
    agent: list[Path] = typer.Option(..., "--agent", "-a"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a path-based Job."""
    try:
        created = scaffold_job(
            path,
            source_path=source,
            source_kind=source_kind,
            agent_paths=tuple(agent),
            force=force,
        )
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": str(created)})


@job_app.command("list")
def job_list(store: Path = typer.Option(Path(".plural/jobs"), "--store")) -> None:
    """List durable local Jobs."""
    _emit(JobStore(store).list_jobs())


@job_app.command("show")
def job_show(
    job_id: str,
    store: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Show a Job, lock, result, and latest event."""
    storage = JobStore(store)
    try:
        spec = storage.load_spec(job_id)
        events = tuple(storage.events(job_id))
    except (OSError, ValueError) as exc:
        _error(str(exc))
    _emit(
        {
            "spec": spec.model_dump(mode="json"),
            "lock": storage.load_lock(job_id).model_dump(mode="json"),
            "result": _dump(storage.read_job_result(job_id)),
            "latest_event": _dump(events[-1]) if events else None,
        }
    )


@job_app.command("submit")
def job_submit(
    path: Path = typer.Argument(Path("job.yaml")),
    source_revision_id: str = typer.Option(..., "--source-revision-id"),
    agent_revision_id: list[str] = typer.Option(..., "--agent-revision-id"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    name: str = typer.Option("Job", "--name"),
) -> None:
    """Submit a hosted Job from exact revision IDs."""
    spec = _validated(load_job, path)
    with _client() as client:
        _emit(
            client.jobs.submit(
                spec,
                source_revision_id=source_revision_id,
                agent_revision_ids=agent_revision_id,
                idempotency_key=idempotency_key,
                name=name,
            )
        )


@job_app.command("watch")
def job_watch(
    job_id: str,
    store: Path = typer.Option(Path(".plural/jobs"), "--store"),
    after: int = typer.Option(0, "--after", min=0),
    follow: bool = typer.Option(False, "--follow"),
    json_events: bool = typer.Option(False, "--json"),
    hosted: bool = typer.Option(False, "--hosted"),
) -> None:
    """Replay or follow local or hosted append-only Job events."""
    try:
        if hosted:
            with _client() as client:
                for hosted_event in client.jobs.watch(job_id, cursor=after):
                    _emit_event(hosted_event, json_events=json_events)
            return
        for local_event in JobStore(store).events(job_id, after=after, follow=follow):
            _emit_event(local_event, json_events=json_events)
    except (OSError, ValueError, PluralError) as exc:
        _error(str(exc))


@app.command("run")
def run(
    source: str = typer.Argument(..., metavar="REF", help="Task, Benchmark, or Job reference."),
    agent: list[str] = typer.Option(None, "--agent", "-a", help="Agent reference; repeatable."),
    mode: JobMode | None = typer.Option(None, "--mode"),
    attempts: int | None = typer.Option(None, "--attempts", min=1),
    concurrency: int | None = typer.Option(None, "--concurrency", min=1),
    per_runtime_concurrency: int | None = typer.Option(None, "--per-runtime-concurrency", min=1),
    dry_run: bool = typer.Option(False, "--dry-run"),
    hosted: bool = typer.Option(
        False,
        "--hosted",
        help="Explicitly synchronize and submit to hosted Plural.",
    ),
    offline: bool = typer.Option(False, "--offline", "--private", hidden=True),
    watch: bool = typer.Option(
        True,
        "--watch/--no-watch",
        help="Follow hosted Job events after explicit submission.",
    ),
    json_events: bool = typer.Option(
        False,
        "--json",
        help="Render watched hosted events as JSON Lines.",
    ),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
    name: str = typer.Option("Job", "--name"),
    output_format: Literal["json", "yaml"] = typer.Option("json", "--format"),
    catalog: Path | None = typer.Option(None, "--catalog"),
) -> None:
    """Run locally by default; use --hosted for explicit remote submission."""
    del offline
    try:
        value = _load_public(source, catalog)
        effective_catalog = _catalog(catalog)
        loaded_agents = tuple(
            candidate
            for item in agent or ()
            if isinstance((candidate := _load_public(item, catalog)), Agent)
        )
        if len(loaded_agents) != len(agent or ()):
            raise TypeError("--agent references must resolve to Agent objects")
        if isinstance(value, PublicJob):
            selected_agents = loaded_agents or value.agents
            spec = value.spec
            job = PublicJob(
                value.source,
                agents=selected_agents,
                mode=mode or spec.mode,
                attempts=attempts or spec.attempts,
                concurrency=concurrency or spec.concurrency,
                per_runtime_concurrency=(per_runtime_concurrency or spec.per_runtime_concurrency),
                priority=spec.priority,
                retry=spec.retry,
                catalog=effective_catalog,
            )
        elif isinstance(value, (Task, Benchmark)):
            if not loaded_agents:
                raise ValueError("Task and Benchmark runs require at least one --agent")
            job = PublicJob(
                value,
                agents=loaded_agents,
                mode=mode or JobMode.EVAL,
                attempts=attempts or 1,
                concurrency=concurrency or 1,
                per_runtime_concurrency=per_runtime_concurrency or 1,
                catalog=effective_catalog,
            )
        else:
            raise TypeError("run requires a Task, Benchmark, or Job")
        spec = job.spec
        plan = job.plan
        if hosted:
            validate_hosted_graph(spec)
    except (OSError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        _error(str(exc))
    if dry_run:
        _emit(
            {
                "dry_run": True,
                "job_id": plan.job_id,
                "mode": spec.mode.value,
                "trial_count": plan.trial_count,
                "runtimes": sorted({item.runtime_provider for item in plan.trials}),
                "trials": [
                    {**item.model_dump(mode="json"), "trial_id": item.trial_id}
                    for item in plan.trials
                ],
            },
            output_format,
        )
        return
    if hosted:
        try:
            with _client() as client:
                submission = sync_and_submit(
                    client,
                    spec,
                    idempotency_key=idempotency_key,
                    name=name,
                )
                _emit(submission.job, output_format)
                if not watch:
                    return
                job_id = submission.job.get("id")
                if not isinstance(job_id, str) or not job_id:
                    raise ValueError("created hosted Job response omitted id")
                for event in client.jobs.watch(job_id):
                    _emit_event(event, json_events=json_events)
            return
        except (OSError, ValueError, PluralError) as exc:
            _error(str(exc))
    source_path = Path(source.rsplit(":", 1)[0]).expanduser().resolve()
    storage = JobStore(source_path.parent / ".plural" / "jobs")
    try:
        result = asyncio.run(JobRunner(spec, store=storage, catalog=job.catalog).run())
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        _error(str(exc))
    _emit(result, output_format)
    if result.status in {"failed", "cancelled"}:
        raise typer.Exit(1)


@trial_app.command("list")
def trial_list(
    job_id: str,
    store: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """List planned Trials and current states."""
    storage = JobStore(store)
    try:
        plan = storage.load_spec(job_id).plan()
        results = {item.receipt.trial_id: item for item in storage.trial_results(job_id)}
    except (OSError, ValueError) as exc:
        _error(str(exc))
    _emit(
        [
            {
                "trial_id": item.trial_id,
                "agent": item.agent_name,
                "task_id": item.task_id,
                "environment": item.environment.name,
                "runtime": item.runtime_provider,
                "attempt": item.attempt,
                "status": results[item.trial_id].status if item.trial_id in results else "queued",
            }
            for item in plan.trials
        ]
    )


@trial_app.command("watch")
def trial_watch(
    trial_id: str,
    job_id: str = typer.Option(..., "--job"),
    store: Path = typer.Option(Path(".plural/jobs"), "--store"),
    after: int = typer.Option(0, "--after", min=0),
    follow: bool = typer.Option(False, "--follow"),
    json_events: bool = typer.Option(False, "--json"),
    hosted: bool = typer.Option(False, "--hosted"),
) -> None:
    """Replay or follow events for one Trial."""
    if hosted:
        with _client() as client:
            for hosted_event in client.trials.watch(trial_id, cursor=after):
                _emit(hosted_event)
        return
    for local_event in JobStore(store).events(job_id, after=after, follow=follow):
        if local_event.trial_id != trial_id:
            continue
        typer.echo(
            local_event.model_dump_json(exclude_none=True)
            if json_events
            else f"{local_event.sequence:>5} {local_event.status:<16} "
            f"{local_event.message}".rstrip()
        )


@review_app.command("list")
def review_list(
    job_id: str,
    store: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """List local Trials awaiting human review."""
    result = JobStore(store).read_job_result(job_id)
    if result is None:
        _error("Job has no result")
    _emit(
        [
            {
                "trial_id": trial.receipt.trial_id,
                "verifiers": [
                    item.verifier_name
                    for item in trial.verifier_results
                    if item.status == "awaiting_review"
                ],
            }
            for trial in result.trials
            if trial.status == "awaiting_review"
        ]
    )


@review_app.command("submit")
def review_submit(
    job_id: str,
    trial_id: str,
    verifier: str = typer.Option(..., "--verifier"),
    score: float = typer.Option(..., "--score"),
    feedback: str = typer.Option("", "--feedback"),
    store: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Durably append a local human-review submission."""
    storage = JobStore(store)
    try:
        spec = storage.load_spec(job_id)
        task = next(
            task
            for task in spec.tasks
            if any(
                item.verifier.name == verifier and item.verifier.kind == "human"
                for item in task.verifiers
            )
        )
        human = next(
            item.verifier
            for item in task.verifiers
            if item.verifier.name == verifier and item.verifier.kind == "human"
        )
        if len(human.rubric) != 1:
            raise ValueError(
                "CLI --score supports one-criterion rubrics; use the Python API "
                "Job.submit_review() for multiple criteria"
            )
        JobRunner(spec, store=storage).submit_review(
            trial_id,
            verifier,
            {human.rubric[0].name: score},
            feedback=feedback,
        )
    except (OSError, ValueError, StopIteration) as exc:
        _error(str(exc))
    path = storage.job_path(job_id) / "trials" / trial_id / "reviews" / verifier
    _emit({"submitted": str(path)})


@review_app.command("hosted-list")
def review_hosted_list(
    status: str | None = typer.Option("awaiting_review", "--status"),
) -> None:
    """List hosted human review assignments."""
    with _client() as client:
        _emit(client.reviews.list(status=status))


@review_app.command("hosted-submit")
def review_hosted_submit(
    assignment_id: str,
    score: list[str] = typer.Option(..., "--score", help="criterion=value"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    feedback: str = typer.Option("", "--feedback"),
) -> None:
    """Submit hosted human-review criterion scores."""
    try:
        scores = {name: float(raw) for item in score for name, raw in (item.split("=", 1),)}
    except (ValueError, TypeError) as exc:
        _error(f"invalid --score; expected criterion=value: {exc}")
    with _client() as client:
        _emit(
            client.reviews.submit(
                assignment_id,
                scores=scores,
                idempotency_key=idempotency_key,
                feedback=feedback,
            )
        )


@app.command("schemas")
def schemas(path: Path = typer.Argument(Path("schemas"))) -> None:
    """Generate schemas from the public SDK models."""
    _emit({"generated": [str(item) for item in generate_schemas(path)]})


def main() -> None:
    """Run the CLI."""
    app()


__all__ = ["app", "main"]
