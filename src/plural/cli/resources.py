"""Plural resource lifecycle commands: init, validate, show, push, publish."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import typer

from plural.cli.config import default_credential_store, resolve_context
from plural.cli.output import _client, _emit, _error, _validated
from plural.cli.scaffold import (
    find_remote_task,
    init_task,
    load_agent,
    load_benchmark,
    load_environment,
    load_harness,
    load_task,
    load_task_for_push,
    load_verifier,
    scaffold_agent,
    scaffold_benchmark,
    scaffold_environment,
    scaffold_harness,
    scaffold_verifier,
    task_push_needs_remote,
)
from plural.client import Client
from plural.config import resolve_gateway_url
from plural.errors import PluralError
from plural.tasks import TaskDefinition

env_app = typer.Typer(help="Author, inspect, and publish Environments.")
task_app = typer.Typer(help="Author, inspect, and publish Tasks.")
verifier_app = typer.Typer(help="Author, inspect, and publish Verifiers.")
agent_app = typer.Typer(help="Author, inspect, and publish Agents.")
harness_app = typer.Typer(help="List built-in Harnesses or author a custom one.")
benchmark_app = typer.Typer(help="Author, inspect, and publish Benchmarks.")


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
    name: str = typer.Argument(..., help="Task slug and local directory name."),
    environment: str | None = typer.Option(
        None, "--environment", "-e", help="Hosted environment slug/id or local file."
    ),
    verifier: list[str] | None = typer.Option(
        None, "--verifier", "-v", help="Hosted verifier slug/id or local file."
    ),
    bare: bool = typer.Option(False, "--bare", help="Create an empty task package."),
    push: bool = typer.Option(False, "--push", help="Publish the new task immediately."),
    force: bool = typer.Option(False, "--force", help="Replace existing task files."),
) -> None:
    """Create a local Task directory without publishing it."""
    client = _task_init_client()
    if client is None:
        typer.echo(
            "Remote task name was not checked because PLURAL_API_KEY is not set.",
            err=True,
        )
    else:
        _confirm_task_slug(client, name)
    try:
        created = init_task(
            name,
            environment=environment,
            verifiers=tuple(verifier or ()),
            bare=bare,
            force=force,
        )
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    if not push:
        _emit({"created": [str(item) for item in created]})
        return
    directory = Path(name).expanduser()
    with _client() as push_client:
        definition, environment_revision_id, verifier_revision_ids = _validated(
            lambda target: load_task_for_push(target, client=push_client),
            directory,
        )
        record = push_client.tasks.push(
            definition,
            environment_revision_id=environment_revision_id,
            verifier_revision_ids=verifier_revision_ids,
        )
    _emit({"created": [str(item) for item in created], "pushed": record})


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
    path: Path = typer.Argument(Path("task.yaml"), help="Task file or task directory."),
    environment_revision_id: str | None = typer.Option(
        None, "--environment-revision-id", help="Override the hosted environment revision."
    ),
    verifier_revision_id: list[str] | None = typer.Option(
        None, "--verifier-revision-id", help="Override a hosted verifier revision."
    ),
) -> None:
    """Publish a Task revision, resolving hosted environment and verifier slugs."""
    try:
        needs_remote = task_push_needs_remote(
            path,
            environment_revision_id=environment_revision_id,
            verifier_revision_ids=verifier_revision_id,
        )
    except (OSError, ValueError) as exc:
        _error(str(exc))
    if not needs_remote:
        task = _validated(load_task, path)
        if environment_revision_id is None or verifier_revision_id is None:
            _error(
                "Task push requires --environment-revision-id and --verifier-revision-id "
                "unless task.yaml uses hosted environment and verifier slugs"
            )
        with _client() as client:
            _emit(
                client.tasks.push(
                    task,
                    environment_revision_id=environment_revision_id,
                    verifier_revision_ids=verifier_revision_id,
                )
            )
        return
    with _client() as client:

        def _load_for_push(target: Path) -> tuple[TaskDefinition, str, list[str]]:
            return load_task_for_push(
                target,
                client=client,
                environment_revision_id=environment_revision_id,
                verifier_revision_ids=verifier_revision_id,
            )

        definition, resolved_environment, resolved_verifiers = _validated(_load_for_push, path)
        _emit(
            client.tasks.push(
                definition,
                environment_revision_id=resolved_environment,
                verifier_revision_ids=resolved_verifiers,
            )
        )


def _task_init_client() -> Client | None:
    """Return a hosted client when task-init collision checks are possible."""
    api_key = os.environ.get("PLURAL_API_KEY")
    if not api_key:
        return None
    try:
        context = resolve_context(credentials=default_credential_store())
        return Client(
            api_key=api_key,
            base_url=resolve_gateway_url(context.api_url),
            project=context.project,
        )
    except (OSError, ValueError, PluralError) as exc:
        _error(str(exc))


def _confirm_task_slug(client: Client, name: str) -> None:
    """Warn about an existing hosted slug and ask whether to continue locally."""
    try:
        existing = find_remote_task(client, name)
    except PluralError as exc:
        _error(str(exc))
    if existing is None:
        return
    typer.echo(
        f"Warning: a task named {name!r} already exists in the current project.",
        err=True,
    )
    try:
        proceed = typer.confirm("Proceed?", default=False)
    except typer.Abort:
        raise typer.Exit(0) from None
    if not proceed:
        raise typer.Exit(0)


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
    harness: str | None = typer.Option(None, "--harness"),
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
    """Publish an Agent parent and immutable revision."""
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


@harness_app.command("list")
def harness_list() -> None:
    """List built-in Harnesses that Agents can attach by name."""
    from plural.harness.builtins import list_builtin_harnesses, summarize_builtin

    _emit([summarize_builtin(item) for item in list_builtin_harnesses()])


@harness_app.command("schema")
def harness_schema(name: str = typer.Argument(..., help="Built-in Harness name.")) -> None:
    """Show the accepted kwargs schema for a built-in Harness."""
    from plural.harness.builtins import builtin_schema

    try:
        _emit(builtin_schema(name))
    except ValueError as exc:
        _error(str(exc))


@harness_app.command("init")
def harness_init(
    path: Path = typer.Argument(Path(".")),
    name: str = typer.Option("harness", "--name"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a custom Harness."""
    try:
        created = scaffold_harness(path, name, force=force)
    except (OSError, ValueError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": [str(item) for item in created]})


@harness_app.command("validate")
def harness_validate(path: Path = typer.Argument(Path("."))) -> None:
    """Validate and lock a Harness."""
    harness = _validated(load_harness, path)
    _emit({"valid": True, "digest": harness.content_hash})


@harness_app.command("show")
def harness_show(path: Path = typer.Argument(Path("."))) -> None:
    """Show a Harness."""
    _emit(_validated(load_harness, path))


@harness_app.command("push")
def harness_push(path: Path = typer.Argument(Path("."))) -> None:
    """Publish a Harness parent and immutable revision."""
    with _client() as client:
        _emit(client.harnesses.push(_validated(load_harness, path)._package()))


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
