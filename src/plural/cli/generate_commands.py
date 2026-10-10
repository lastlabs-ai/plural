"""``plural env from-mcp|from-openapi|from-traces|eject-files|serve``: draft and try an Environment.

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
from plural.mcp import PORT
from plural.project import ProjectError, ResourceRef, Workspace, check_name
from plural.project.generators import (
    DEFAULT_JUDGE_MODEL,
    Generated,
    from_mcp,
    from_openapi,
    from_traces,
)
from plural.project.layout import ENVIRONMENT

APP_HELP = (
    "The App's name. It prefixes an action only when another App offers the same name. "
    "Default: NAME."
)
RUNTIME_HELP = "Where the Environment runs: local (a trusted subprocess), docker, or daytona."
SECRET_HELP = (
    "A setup secret the project supplies, for reset and snapshot hooks. Repeatable. "
    "Without it, ${NAME} in a header or variable is a credential the Agent supplies."
)
CREDENTIAL_HELP = (
    "A credential the running Agent supplies, such as its own API token. Repeatable. "
    "${NAME} in a header or variable is added for you."
)


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
            for credential in app["credentials"]:
                typer.echo(f"  credential {credential['name']}: supplied by the Agent that runs")
        if generated.credentials:
            typer.echo(
                "\nAn Agent supplies each credential. List them under credentials: in its "
                "agent.yaml, store each with `plural agent credential set AGENT NAME`, and "
                "run with --agent."
            )
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
        credential: list[str] = typer.Option([], "--credential", help=CREDENTIAL_HELP),
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
                credentials=credential,
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
        credential: list[str] = typer.Option([], "--credential", help=CREDENTIAL_HELP),
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
            credentials=credential,
            runtime=runtime,
        )
        _write(generated, as_json=as_json)

    @app.command("eject-files")
    @handled
    def env_eject_files(
        name: str = typer.Argument(help="Environment to copy the files server into."),
        filename: str = typer.Option(
            "files_server.py", "--as", help="File to write, in the Environment folder."
        ),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Copy Plural's ready-made files server into an Environment, to change what it offers."""
        import plural.mcp.files

        space = workspace()
        directory = space.project.resource_dir(ResourceRef(ENVIRONMENT.name, name))
        if not directory.is_dir():
            raise ProjectError(f"No Environment {name}. Create it with `plural env init {name}`.")
        target = directory / filename
        if target.suffix != ".py" or target.parent != directory:
            raise ProjectError("--as must be a .py file name, such as files_server.py.")
        if target.exists():
            raise ProjectError(f"{relative(target, space.project.root)} already exists.")
        source = Path(plural.mcp.files.__file__).read_text(encoding="utf-8")
        target.write_text(source, encoding="utf-8")
        reference = f"{filename}:server"
        payload = {"file": relative(target, space.project.root), "server": reference}

        def text() -> None:
            typer.echo(f"Wrote {payload['file']}. Point the App at it in environment.yaml:")
            typer.echo(f"  - name: files\n    mcp:\n      server: {reference}")

        emit(payload, as_json=as_json, text=text)

    @app.command("serve")
    @handled
    def env_serve(
        name: str = typer.Argument(help="Environment whose FastMCP server to serve."),
        app_name: str | None = typer.Option(
            None, "--app", help="App to serve, when the Environment has several servers."
        ),
        port: int = typer.Option(PORT, "--port", help="Port on 127.0.0.1."),
    ) -> None:
        """Serve an App's FastMCP server over HTTP, to try its tools in any MCP client.

        Trials don't use this: they talk to the server over stdin and stdout.
        """
        import os

        import yaml

        from plural.apps.mcp import expand
        from plural.mcp.serve import load_server, serve_http

        space = workspace()
        directory = space.project.resource_dir(ResourceRef(ENVIRONMENT.name, name))
        manifest = directory / "environment.yaml"
        if not manifest.is_file():
            raise ProjectError(f"No Environment {name}. Create it with `plural env init {name}`.")
        apps = (yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("apps") or []
        servers = [
            item
            for item in apps
            if isinstance(item, dict)
            and isinstance(item.get("mcp"), dict)
            and item["mcp"].get("server")
            and (app_name is None or item.get("name") == app_name)
        ]
        if not servers:
            raise ProjectError(
                f"Environment {name} has no FastMCP App"
                + (f" named {app_name}" if app_name else "")
                + ". An App with `mcp: {server: server.py:mcp}` can be served."
            )
        if len(servers) > 1:
            names = ", ".join(str(item.get("name")) for item in servers)
            raise ProjectError(
                f"Environment {name} has several servers ({names}). Pick one with --app."
            )
        settings = servers[0]["mcp"]
        credentials = [
            item if isinstance(item, str) else str(item.get("name"))
            for item in settings.get("credentials") or []
        ]
        for key, value in (settings.get("env") or {}).items():
            os.environ[key] = expand(str(value), credentials=credentials)
        os.chdir(directory)
        server = load_server(str(settings["server"]), directory)
        typer.echo(
            f"Serving {servers[0].get('name')} at http://127.0.0.1:{port}/mcp. "
            "Connect any MCP client; stop with Ctrl+C."
        )
        serve_http(server, port)

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
