"""``plural env from-mcp|from-openapi|from-data|from-traces``: draft an Environment.

Each command writes ordinary project files, then loads the Environment the way
``plural env validate`` does, which is when an MCP server's tools and an API's
operations are discovered, and prints what the Agent will be offered.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import typer

from plural.cli.common import JSON_OPTION, emit, handled, relative, workspace
from plural.cli.secret_commands import secret_status
from plural.project import ProjectError, ResourceRef, Workspace, check_name
from plural.project.generators import (
    DEFAULT_JUDGE_MODEL,
    Generated,
    from_data,
    from_mcp,
    from_openapi,
    from_traces,
)
from plural.project.layout import ENVIRONMENT

APP_HELP = "The App's name, which prefixes its actions when there are several. Default: NAME."
RUNTIME_HELP = "Where the Environment runs: local (a trusted subprocess), docker, or daytona."
SECRET_HELP = "A secret the App needs. ${NAME} in a header or variable is added for you."


def _pairs(values: list[str], option: str) -> dict[str, str]:
    pairs = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key.strip():
            raise ProjectError(f"{option} takes KEY=VALUE, got {value!r}.")
        pairs[key.strip()] = item
    return pairs


def _write(generated: Generated, *, as_json: bool) -> None:
    space = workspace()
    check_name(generated.environment, ENVIRONMENT.label)
    root = space.project.root
    taken = generated.conflicts(root)
    if taken:
        raise ProjectError(
            "These files already exist, so nothing was written:\n"
            + "\n".join(f"  {item}" for item in taken)
            + "\nChoose another name."
        )
    written = generated.write(root)
    from plural.cli.resource_commands import _app_summary

    apps: list[dict[str, Any]] = []
    problem = None
    try:
        loaded = Workspace(space.project).load(ResourceRef(ENVIRONMENT.name, generated.environment))
        apps = _app_summary(loaded.value)
    except (ProjectError, ValueError, OSError, RuntimeError) as exc:
        problem = str(exc)
    files = [relative(path, root) for path in written]
    payload = {
        "environment": generated.environment,
        "files": files,
        "apps": apps,
        "tasks": generated.tasks,
        "benchmark": generated.benchmark,
        "problem": problem,
    }

    def text() -> None:
        typer.echo(f"Drafted environment {generated.environment}:")
        for path in files:
            typer.echo(f"  {path}")
        for app in apps:
            typer.echo(f"\nApp {app['name']} ({app['kind']}, {app['control']}) offers:")
            for action in app["actions"]:
                marker = "" if action["mutates_state"] else "  [read-only]"
                typer.echo(f"  {action['name']}{marker}")
            for secret in app["secrets"]:
                status = secret_status(secret)
                typer.echo(f"  secret {secret['name']}: {status}")
        if problem:
            typer.echo(
                f"\nThe files are written, but loading the Environment failed:\n  {problem}\n"
                f"Fix that, then run `plural env validate {generated.environment}`."
            )
        if generated.benchmark:
            typer.echo(
                f"\nDrafted {len(generated.tasks)} Task(s) and benchmark {generated.benchmark}. "
                "Review the instructions, then score the recorded agent with "
                f"`plural run --benchmark {generated.benchmark} --traces <file>`."
            )

    emit(payload, as_json=as_json, text=text)


def _file(path: str, *, root: Path) -> tuple[str, bytes]:
    source = Path(path)
    if not source.is_absolute():
        source = Path.cwd() / source
    if not source.is_file():
        source = root / path
    if not source.is_file():
        raise ProjectError(f"No file at {path}.")
    return source.name, source.read_bytes()


def add_generators(app: typer.Typer) -> None:
    """Register the ``from-*`` commands on the ``plural env`` group."""

    @app.command("from-mcp")
    @handled
    def env_from_mcp(
        name: str = typer.Argument(help="Environment name."),
        command: str | None = typer.Option(
            None, "--command", help="Start a stdio server, such as 'npx -y @scope/server'."
        ),
        url: str | None = typer.Option(None, "--url", help="Reach a Streamable HTTP server."),
        header: list[str] = typer.Option(
            [], "--header", help="An HTTP header, KEY=VALUE. Repeatable. Use ${SECRET}."
        ),
        env: list[str] = typer.Option(
            [], "--env", help="A server variable, KEY=VALUE. Repeatable. Use ${SECRET}."
        ),
        tool: list[str] = typer.Option(
            [], "--tool", help="Only offer this tool. Repeatable. Default: every tool."
        ),
        secret: list[str] = typer.Option([], "--secret", help=SECRET_HELP),
        app_name: str | None = typer.Option(None, "--app", help=APP_HELP),
        runtime: str = typer.Option("local", "--runtime", help=RUNTIME_HELP),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Draft an Environment whose App is an MCP server; its tools become actions."""
        try:
            generated = from_mcp(
                name,
                app=app_name or name.replace("-", "_"),
                command=shlex.split(command) if command else (),
                url=url,
                headers=_pairs(header, "--header"),
                env=_pairs(env, "--env"),
                tools=tool,
                secrets=secret,
                runtime=runtime,
            )
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        _write(generated, as_json=as_json)

    @app.command("from-openapi")
    @handled
    def env_from_openapi(
        name: str = typer.Argument(help="Environment name."),
        spec: str = typer.Option(..., "--spec", help="The OpenAPI document: a file or a URL."),
        base_url: str | None = typer.Option(
            None, "--base-url", help="Where to send requests. Default: the document's servers."
        ),
        header: list[str] = typer.Option(
            [], "--header", help="An HTTP header, KEY=VALUE. Repeatable. Use ${SECRET}."
        ),
        operation: list[str] = typer.Option(
            [], "--operation", help="Only offer this operationId. Repeatable."
        ),
        secret: list[str] = typer.Option([], "--secret", help=SECRET_HELP),
        app_name: str | None = typer.Option(None, "--app", help=APP_HELP),
        runtime: str = typer.Option("local", "--runtime", help=RUNTIME_HELP),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Draft an Environment whose App is an HTTP API; its operations become actions."""
        remote = spec.startswith(("http://", "https://"))
        generated = from_openapi(
            name,
            app=app_name or name.replace("-", "_"),
            spec=spec,
            spec_file=None if remote else _file(spec, root=workspace().project.root),
            base_url=base_url,
            headers=_pairs(header, "--header"),
            operations=operation,
            secrets=secret,
            runtime=runtime,
        )
        _write(generated, as_json=as_json)

    @app.command("from-data")
    @handled
    def env_from_data(
        name: str = typer.Argument(help="Environment name."),
        files: list[str] = typer.Argument(
            None, help="CSV, JSON, or JSONL files; each is a table named after the file."
        ),
        database: str | None = typer.Option(None, "--database", help="A SQLite file instead."),
        key: list[str] = typer.Option(
            [], "--key", help="A table's key column, TABLE=COLUMN. Default: id, else rowid."
        ),
        read_only: bool = typer.Option(False, "--read-only", help="Offer no writes."),
        sql: bool = typer.Option(False, "--sql", help="Also offer read-only SQL as `query`."),
        app_name: str | None = typer.Option(None, "--app", help=APP_HELP),
        runtime: str = typer.Option("local", "--runtime", help=RUNTIME_HELP),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Draft an Environment whose App is tables of data, for a system with no API."""
        root = workspace().project.root
        tables = {Path(item).stem.replace("-", "_"): _file(item, root=root) for item in files or ()}
        try:
            generated = from_data(
                name,
                app=app_name or name.replace("-", "_"),
                tables=tables,
                database=_file(database, root=root) if database else None,
                keys=_pairs(key, "--key"),
                read_only=read_only,
                sql=sql,
                runtime=runtime,
            )
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        _write(generated, as_json=as_json)

    @app.command("from-traces")
    @handled
    def env_from_traces(
        name: str = typer.Argument(help="Environment name; also names the drafted Benchmark."),
        traces: str = typer.Option(
            ...,
            "--traces",
            help='Recorded conversations: JSONL of {"messages": [...]}, or Plural Traces.',
        ),
        app_name: str = typer.Option(
            "tools", "--app", help="App for tool calls whose names carry no app__ prefix."
        ),
        judge_model: str = typer.Option(
            DEFAULT_JUDGE_MODEL, "--judge-model", help="Model for the drafted judge Verifier."
        ),
        max_tasks: int = typer.Option(50, "--max-tasks", min=1, help="Draft at most this many."),
        runtime: str = typer.Option("local", "--runtime", help=RUNTIME_HELP),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Draft replay Apps from recorded tool calls, a Task per trace, and a Benchmark."""
        from plural.recorded import read_traces

        root = workspace().project.root
        path = Path(traces) if Path(traces).is_file() else root / traces
        if not path.is_file():
            raise ProjectError(f"No traces file at {traces}.")
        try:
            generated = from_traces(
                name,
                read_traces(path),
                default_app=app_name,
                judge_model=judge_model,
                max_tasks=max_tasks,
                runtime=runtime,
            )
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        _write(generated, as_json=as_json)


__all__ = ["add_generators"]
