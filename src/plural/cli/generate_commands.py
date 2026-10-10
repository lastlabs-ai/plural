"""``plural env add|eject-files|serve``: add your systems to an Environment and try them.

``add`` writes ordinary project files, then loads the Environment the way
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
    add_app,
    add_traces,
    app_name,
    mcp_app,
    openapi_app,
)
from plural.project.layout import ENVIRONMENT

APP_HELP = (
    "The App's name. It prefixes an action only when another App offers the same name. "
    "Default: from the source, such as linear for https://mcp.linear.app/mcp. With "
    "--traces, the App for tool calls whose names carry no app__ prefix (default: tools)."
)
RUNTIME_HELP = (
    "Where a new Environment runs: local (a trusted subprocess), docker, or daytona. "
    "Default: local."
)
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
            + "\nName the App with --app."
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
        "updated": generated.updated,
        "notes": generated.notes,
        "files": files,
        "apps": apps,
        "tasks": generated.tasks,
        "benchmark": generated.benchmark,
        "problem": problem,
    }

    def text() -> None:
        if not generated.updated:
            typer.echo(f"Created environment {generated.environment}:")
        elif files:
            typer.echo(f"Updated environment {generated.environment}:")
        else:
            typer.echo(f"Nothing changed in environment {generated.environment}:")
        for note in generated.notes:
            typer.echo(f"  {note}")
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
                f"\nReview the drafted Tasks' instructions, then run Agents on them with "
                f"`plural run --benchmark {generated.benchmark} --model <model>`."
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
    """Register ``add``, ``eject-files``, and ``serve`` on the ``plural env`` group."""

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

    @app.command("add")
    @handled
    def env_add(
        name: str = typer.Argument(help="Environment to add to; created if it does not exist."),
        mcp: str | None = typer.Option(
            None,
            "--mcp",
            help="An MCP server: its Streamable HTTP URL, or the command that starts it over "
            "stdio, such as 'npx -y @modelcontextprotocol/server-memory'.",
        ),
        openapi: str | None = typer.Option(
            None, "--openapi", help="An HTTP API's OpenAPI document: a file or a URL."
        ),
        traces: str | None = typer.Option(
            None,
            "--traces",
            help='Recorded conversations: JSON or JSONL of {"messages": [...]}, or Plural '
            "Traces. Each system they call becomes a replay App, and Tasks and a Benchmark "
            "are drafted from them.",
        ),
        app_name_option: str | None = typer.Option(None, "--app", help=APP_HELP),
        header: list[str] = typer.Option(
            [], "--header", help="An HTTP header, KEY=VALUE. Repeatable. Use ${NAME}."
        ),
        env: list[str] = typer.Option(
            [], "--env", help="An MCP server variable, KEY=VALUE. Repeatable. Use ${NAME}."
        ),
        tool: list[str] = typer.Option(
            [], "--tool", help="Only offer this MCP tool. Repeatable. Default: every tool."
        ),
        base_url: str | None = typer.Option(
            None, "--base-url", help="Where to send API requests. Default: the document's servers."
        ),
        operation: list[str] = typer.Option(
            [], "--operation", help="Only offer this API operationId. Repeatable."
        ),
        secret: list[str] = typer.Option([], "--secret", help=SECRET_HELP),
        credential: list[str] = typer.Option([], "--credential", help=CREDENTIAL_HELP),
        judge_model: str = typer.Option(
            DEFAULT_JUDGE_MODEL, "--judge-model", help="With --traces: model for the drafted judge."
        ),
        max_tasks: int = typer.Option(
            50,
            "--max-tasks",
            min=1,
            help="With --traces: draft at most this many Tasks, preferring traces that call "
            "different tools.",
        ),
        runtime: str | None = typer.Option(None, "--runtime", help=RUNTIME_HELP),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Add a system to an Environment as an App, creating the Environment if it is new.

        Give one source per call: --mcp, --openapi, or --traces. Run it again to
        add another system. With --traces it also drafts Tasks and a Benchmark,
        and running it again with newer traces adds their calls, tools, systems,
        and Tasks; existing Tasks are kept.
        """
        sources = [
            flag
            for flag, value in (("--mcp", mcp), ("--openapi", openapi), ("--traces", traces))
            if value
        ]
        if len(sources) != 1:
            raise ProjectError(
                "Give one system to add: --mcp URL_OR_COMMAND, --openapi SPEC, or --traces FILE."
            )
        check_name(name, ENVIRONMENT.label)
        root = workspace().project.root
        try:
            if traces:
                from plural.recorded import read_traces

                path = Path(traces) if Path(traces).is_file() else root / traces
                if not path.is_file():
                    raise ProjectError(f"No traces file at {traces}.")
                generated = add_traces(
                    name,
                    read_traces(path),
                    default_app=app_name_option or "tools",
                    judge_model=judge_model,
                    max_tasks=max_tasks,
                    runtime=runtime or "local",
                    root=root,
                )
            elif mcp:
                remote = mcp.startswith(("http://", "https://"))
                draft = mcp_app(
                    app_name_option or app_name(mcp, fallback=name),
                    command=() if remote else shlex.split(mcp),
                    url=mcp if remote else None,
                    headers=_pairs(header, "--header"),
                    env=_pairs(env, "--env"),
                    tools=tool,
                    secrets=secret,
                    credentials=credential,
                )
                generated = add_app(root, name, draft, runtime=runtime)
            else:
                assert openapi is not None
                remote = openapi.startswith(("http://", "https://"))
                draft = openapi_app(
                    app_name_option or app_name(openapi, fallback=name),
                    spec=openapi,
                    spec_file=None if remote else _file(openapi, root=root),
                    base_url=base_url,
                    headers=_pairs(header, "--header"),
                    operations=operation,
                    secrets=secret,
                    credentials=credential,
                )
                generated = add_app(root, name, draft, runtime=runtime)
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        _write(generated, as_json=as_json)


__all__ = ["add_generators"]
