"""Resource commands: the same verbs for every kind of project resource.

``plural <kind> init|validate|push|pull|show|list`` for ``env``, ``task``,
``verifier``, ``harness``, ``agent``, and ``benchmark``. Resources are named
by their directory, never by revision id.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from plural.cli.common import (
    JSON_OPTION,
    emit,
    handled,
    project_studio,
    relative,
    rows,
    session,
    workspace,
)
from plural.harness.builtins import BUILTIN_HARNESS_NAMES, builtin_schema, get_builtin
from plural.project import (
    KINDS,
    LocalResource,
    ProjectError,
    ResourceKind,
    ResourceRef,
    Workspace,
    check_name,
)
from plural.project.layout import AGENT, BENCHMARK, HARNESS, TASK
from plural.project.membership import add_task, remove_task
from plural.project.sync import hosted_list, hosted_resource, pull, push
from plural.project.templates import resource_scaffold

NAME_HELP = "Resource name. Defaults to the resource directory you are in."


def resource_app(kind: ResourceKind) -> typer.Typer:
    """Build the command group for one resource kind.

    Returns:
        The Typer group.
    """
    app = typer.Typer(
        help=f"Create, validate, push, pull, and inspect {kind.plural_label}.",
        no_args_is_help=True,
    )
    _init_command(app, kind)

    @app.command("validate")
    @handled
    def validate(
        name: str | None = typer.Argument(None, help=NAME_HELP),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Check a resource and everything it depends on, without uploading."""
        space = workspace()
        ref = _ref(space, kind, name)
        resource = space.load(ref)
        payload = _local_payload(space, resource)
        emit(
            payload,
            as_json=as_json,
            text=lambda: typer.echo(
                f"{ref} is valid: version {resource.version}, {resource.content_hash}"
            ),
        )

    @app.command("push")
    @handled
    def push_command(
        name: str | None = typer.Argument(None, help=NAME_HELP),
        with_deps: bool = typer.Option(
            False, "--with-deps", help="Also push local dependencies that are not hosted yet."
        ),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Validate and push an immutable, private revision to the bound project.

        Pushing unchanged content reuses the existing revision. Without
        --with-deps, every dependency must already be pushed with identical
        content. Nothing is uploaded unless the whole push can succeed.
        """
        space = workspace()
        ref = _ref(space, kind, name)
        studio, binding = project_studio(space, session())
        result = push(space, studio, binding, ref, with_deps=with_deps)
        payload = {
            "project": binding.project_slug,
            "steps": [
                {
                    "resource": str(step.ref),
                    "version": step.version,
                    "status": step.status,
                    "revision_id": step.revision_id,
                }
                for step in result.steps
            ],
        }

        def text() -> None:
            typer.echo(f"Pushed to hosted project {binding.project_slug} (private):")
            rows(
                ((step.ref, step.version, step.status) for step in result.steps),
                ("resource", "version", "result"),
            )

        emit(payload, as_json=as_json, text=text)

    @app.command("pull")
    @handled
    def pull_command(
        name: str | None = typer.Argument(None, help=NAME_HELP),
        version: str | None = typer.Option(None, "--version", help="Version to restore."),
        with_deps: bool = typer.Option(
            False, "--with-deps", help="Also restore the exact dependency revisions it pins."
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Replace local files that differ. The old copy is kept under .plural/backups.",
        ),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Restore a hosted revision's editable files into this project."""
        space = workspace()
        ref = _ref(space, kind, name, must_exist=False)
        studio, binding = project_studio(space, session())
        steps = pull(
            space,
            studio,
            ref,
            version=version,
            force=force,
            with_deps=with_deps,
            project_id=binding.project_id,
        )
        payload = [
            {
                "resource": str(step.ref),
                "version": step.version,
                "status": step.status,
                "backup": str(step.backup) if step.backup else None,
            }
            for step in steps
        ]

        def text() -> None:
            rows(
                (
                    (
                        step.ref,
                        step.version,
                        step.status
                        + (
                            f" (backup: {relative(step.backup, space.project.root)})"
                            if step.backup
                            else ""
                        ),
                    )
                    for step in steps
                ),
                ("resource", "version", "result"),
            )

        emit(payload, as_json=as_json, text=text)

    @app.command("show")
    @handled
    def show(
        name: str | None = typer.Argument(None, help=NAME_HELP),
        local: bool = typer.Option(False, "--local", help="Only read local files."),
        hosted: bool = typer.Option(False, "--hosted", help="Only read the hosted project."),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Show a resource: the local copy if there is one, otherwise the hosted one.

        An invalid local copy is an error, not a reason to show the hosted one.
        """
        if local and hosted:
            raise ProjectError("Choose --local or --hosted, not both.")
        space = workspace()
        ref = _ref(space, kind, name, must_exist=False)
        if kind is HARNESS and ref.name in BUILTIN_HARNESS_NAMES and not space.project.has(ref):
            spec = get_builtin(ref.name)
            payload: dict[str, Any] = {
                "location": "built-in",
                "resource": str(ref),
                "pinned_version": spec.pinned_version,
                "harness_kwargs": builtin_schema(ref.name),
            }
            emit(payload, as_json=as_json, text=lambda: _print_builtin(payload))
            return
        if not hosted and space.project.has(ref):
            resource = space.load(ref)
            payload = _local_payload(space, resource)
            emit(payload, as_json=as_json, text=lambda: _print_local(payload))
            return
        if local:
            raise ProjectError(f"No local {kind.label} named {ref.name!r} in this project.")
        studio, binding = project_studio(space, session())
        parent, revisions = hosted_resource(studio, ref)
        payload = {
            "location": "hosted",
            "resource": str(ref),
            "project": binding.project_slug,
            "id": parent.get("id"),
            "description": parent.get("description"),
            "revisions": [
                {
                    "version": item.version,
                    "revision_id": item.revision_id,
                    "content_hash": item.content_hash,
                    "restorable": item.package_digest is not None,
                }
                for item in revisions
            ],
        }

        def text() -> None:
            typer.echo(f"{kind.label} {ref.name} (hosted, project {binding.project_slug})")
            rows(
                (
                    (item.version, item.revision_id, "yes" if item.package_digest else "no")
                    for item in revisions
                ),
                ("version", "revision", "pullable"),
            )

        emit(payload, as_json=as_json, text=text)

    @app.command("list")
    @handled
    def list_command(
        local: bool = typer.Option(False, "--local", help="Only list local resources."),
        hosted: bool = typer.Option(False, "--hosted", help="Only list hosted resources."),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """List resources of this kind, labeled local or hosted."""
        if local and hosted:
            raise ProjectError("Choose --local or --hosted, not both.")
        space = workspace()
        items: list[dict[str, Any]] = []
        if not hosted:
            for resource_name in space.project.names(kind):
                ref = ResourceRef(kind.name, resource_name)
                try:
                    resource = space.load(ref)
                    items.append(
                        {
                            "location": "local",
                            "name": resource_name,
                            "version": resource.version,
                            "status": _lock_status(space, resource),
                        }
                    )
                except ProjectError as exc:
                    items.append(
                        {
                            "location": "local",
                            "name": resource_name,
                            "version": None,
                            "status": f"invalid ({len(exc.problems) or 1} problem(s))",
                        }
                    )
        if kind is HARNESS and not (local or hosted):
            items.extend(
                {
                    "location": "built-in",
                    "name": builtin,
                    "version": get_builtin(builtin).pinned_version,
                    "status": "available",
                }
                for builtin in BUILTIN_HARNESS_NAMES
            )
        note = None
        if not local:
            current = session()
            if space.project.read_binding() is None or current.token is None:
                note = "Hosted resources not shown: this directory is not registered or signed in."
                if hosted:
                    project_studio(space, current)
            else:
                studio, _binding = project_studio(space, current)
                for record in hosted_list(studio, kind):
                    items.append(
                        {
                            "location": "hosted",
                            "name": record.get("slug") or record.get("name"),
                            "version": record.get("current_version") or record.get("version"),
                            "status": "hosted",
                        }
                    )

        def text() -> None:
            if not items:
                typer.echo(
                    f"No {kind.plural_label} yet. Create one with `plural {kind.cli} init <name>`."
                )
            else:
                rows(
                    (
                        (item["name"], item["location"], item["version"] or "-", item["status"])
                        for item in items
                    ),
                    ("name", "where", "version", "status"),
                )
            if note:
                typer.echo(note)

        emit(items, as_json=as_json, text=text)

    if kind is BENCHMARK:
        _benchmark_membership(app)
    if kind is AGENT:

        @app.command("serve")
        def serve(
            name: str | None = typer.Argument(None, help="Agent to serve."),
        ) -> None:
            """Reserved: serve an Agent as an endpoint (not available yet)."""
            typer.echo(
                "Error: `plural agent serve` is not available yet. Run an Agent with "
                "`plural run --agent <name> --task <name>`.",
                err=True,
            )
            raise typer.Exit(2)

    return app


def _init_command(app: typer.Typer, kind: ResourceKind) -> None:
    def create(name: str, **options: Any) -> None:
        space = workspace()
        check_name(name, kind.label)
        ref = ResourceRef(kind.name, name)
        directory = space.project.resource_dir(ref)
        if directory.exists():
            raise ProjectError(
                f"{relative(directory, space.project.root)} already exists. Choose another name."
            )
        written = resource_scaffold(kind, name, **options).write(directory)
        typer.echo(f"Created {kind.label} {name}:")
        for path in written:
            typer.echo(f"  {relative(path, space.project.root)}")
        typer.echo(
            f"Fill in the places marked PLURAL-TODO, then run `plural {kind.cli} validate {name}`."
        )

    if kind is TASK:

        @app.command("init")
        @handled
        def init_task(
            name: str = typer.Argument(help="Task name."),
            environment: str | None = typer.Option(
                None, "--environment", "-e", help="Environment the Task runs in."
            ),
            verifier: list[str] = typer.Option(
                [], "--verifier", "-v", help="Verifier that scores it. Repeat for more."
            ),
        ) -> None:
            """Create a Task with instructions, one Environment, and its Verifiers."""
            create(name, environment=environment, verifiers=tuple(verifier))

    elif kind is AGENT:

        @app.command("init")
        @handled
        def init_agent(
            name: str = typer.Argument(help="Agent name."),
            model: str | None = typer.Option(None, "--model", "-m", help="Catalog model id."),
            harness: str | None = typer.Option(None, "--harness", help="Harness name."),
        ) -> None:
            """Create a saved Agent: a model, instructions, and an optional Harness."""
            create(name, model=model, harness=harness)

    else:

        @app.command("init")
        @handled
        def init(name: str = typer.Argument(help=f"{kind.label} name.")) -> None:
            """Create a new resource from the standard template."""
            create(name)

        init.__doc__ = f"Create a new {kind.label} from the standard template."


def _benchmark_membership(app: typer.Typer) -> None:
    benchmark_option = typer.Option(
        None, "--benchmark", "-b", help="Benchmark to edit. Defaults to the one you are in."
    )
    push_option = typer.Option(False, "--push", help="Push the Benchmark afterwards.")

    @app.command("add")
    @handled
    def add(
        task: str = typer.Argument(help="Task to add."),
        benchmark: str | None = benchmark_option,
        push_after: bool = push_option,
    ) -> None:
        """Add a Task to a Benchmark (a local edit until you push)."""
        space = workspace()
        ref = _ref(space, BENCHMARK, benchmark)
        changed = add_task(space.project, ref.name, task)
        typer.echo(
            f"Added task {task} to benchmark {ref.name}."
            if changed
            else f"Benchmark {ref.name} already includes task {task}."
        )
        _maybe_push(space, ref, push_after)

    @app.command("remove")
    @handled
    def remove(
        task: str = typer.Argument(help="Task to remove."),
        benchmark: str | None = benchmark_option,
        push_after: bool = push_option,
    ) -> None:
        """Remove a Task from a Benchmark (a local edit until you push)."""
        space = workspace()
        ref = _ref(space, BENCHMARK, benchmark)
        remove_task(space.project, ref.name, task)
        typer.echo(f"Removed task {task} from benchmark {ref.name}.")
        _maybe_push(space, ref, push_after)


def _maybe_push(space: Workspace, ref: ResourceRef, enabled: bool) -> None:
    if not enabled:
        typer.echo(f"Push it with `plural benchmark push {ref.name}`.")
        return
    studio, binding = project_studio(space, session())
    result = push(space, studio, binding, ref)
    step = result.steps[-1]
    typer.echo(f"Pushed {ref} {step.version} to {binding.project_slug} ({step.status}).")


def _ref(
    space: Workspace, kind: ResourceKind, name: str | None, *, must_exist: bool = True
) -> ResourceRef:
    """Resolve a named resource, or the one whose directory contains the cwd.

    Raises:
        ProjectError: When no name is given outside a resource directory, or
            the named resource does not exist locally and must.
    """
    if name is None:
        here = space.project.resource_at(Path.cwd())
        if here is None or here.kind != kind.name:
            raise ProjectError(
                f"Name the {kind.label}, or run this inside {kind.directory}/<name>/."
            )
        return here
    check_name(name, kind.label)
    ref = ResourceRef(kind.name, name)
    if must_exist and not space.project.has(ref):
        known = ", ".join(space.project.names(kind)) or "none"
        raise ProjectError(
            f"No {kind.label} named {name!r} in this project (local {kind.directory}: {known}). "
            f"Create it with `plural {kind.cli} init {name}` or restore it with "
            f"`plural {kind.cli} pull {name}`."
        )
    return ref


def _lock_status(space: Workspace, resource: LocalResource) -> str:
    entry = space.project.read_lock().resources.get(str(resource.ref))
    if entry is None:
        return "not pushed"
    if entry.content_hash == resource.content_hash and entry.version == resource.version:
        return f"pushed ({entry.version})"
    return f"changed since push ({entry.version})"


def _local_payload(space: Workspace, resource: LocalResource) -> dict[str, Any]:
    value = resource.value
    return {
        "location": "local",
        "resource": str(resource.ref),
        "path": relative(resource.directory, space.project.root),
        "version": resource.version,
        "content_hash": resource.content_hash,
        "description": getattr(value, "description", None) or None,
        "depends_on": [str(item) for item in resource.dependencies],
        "hosted": _lock_status(space, resource),
    }


def _print_builtin(payload: dict[str, Any]) -> None:
    name = str(payload["resource"]).partition("/")[2]
    typer.echo(f"Harness {name} (built-in, version {payload['pinned_version']})")
    typer.echo(f"  Use it with `harness: {name}` in agent.yaml or `plural run --harness {name}`.")
    properties = payload["harness_kwargs"].get("properties", {})
    if properties:
        typer.echo("  harness_kwargs:")
        for key, value in properties.items():
            typer.echo(f"    {key}: {value.get('description') or value.get('type') or ''}")


def _print_local(payload: dict[str, Any]) -> None:
    kind, _, name = str(payload["resource"]).partition("/")
    label = next(item.label for item in KINDS if item.name == kind)
    typer.echo(f"{label} {name} (local, {payload['path']})")
    typer.echo(f"  Version:      {payload['version']}")
    typer.echo(f"  Content hash: {payload['content_hash']}")
    if payload["description"]:
        typer.echo(f"  Description:  {payload['description']}")
    typer.echo(f"  Depends on:   {', '.join(payload['depends_on']) or '-'}")
    typer.echo(f"  Hosted:       {payload['hosted']}")
