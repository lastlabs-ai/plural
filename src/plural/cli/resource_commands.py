"""Resource commands: the same verbs for every kind of project resource.

``plural <kind> init|validate|push|release|pull|show|list|delete`` for ``env``,
``task``, ``verifier``, ``harness``, ``agent``, and ``benchmark``. Resources
are named by their directory; revisions by number, release version, or hash.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import typer

from plural.cli.common import (
    JSON_OPTION,
    REF_HELP,
    counted,
    deprecated,
    emit,
    handled,
    project_studio,
    relative,
    rows,
    session,
    success,
    workspace,
)
from plural.cli.secret_commands import secret_status
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
from plural.project.layout import AGENT, BENCHMARK, ENVIRONMENT, HARNESS, TASK, split_version
from plural.project.membership import add_task, remove_task
from plural.project.sync import (
    REBUILT_NOTE,
    PushStep,
    hosted_list,
    hosted_resource,
    pull,
    push,
    release,
    revision_label,
    select_revision,
)
from plural.project.templates import STARTER_MODEL, resource_scaffold, starter_scaffolds
from plural.project.versions import holds_version
from plural.studio import slugify

NAME_HELP = "Resource name. Defaults to the resource directory you are in."
VERSIONED_NAME_HELP = f"The resource: {REF_HELP}. Defaults to the resource directory you are in."


def _app_summary(environment: Any) -> list[dict[str, Any]]:
    """Each App's kind, control level, actions, secrets, and credentials, never values.

    Returns:
        One entry per App.
    """
    import os

    from plural.cli.secret_commands import project_secret_names

    definition = environment.definition()
    names = {item.name for app in definition.apps for item in app.secrets}
    stored = project_secret_names() if names - set(os.environ) else set()
    return [
        {
            "name": app.name,
            "kind": app.kind,
            "control": app.control,
            "actions": [
                {"name": item.name, "mutates_state": item.mutates_state} for item in app.actions
            ],
            "secrets": [
                {
                    "name": item.name,
                    "required": item.required,
                    "set": bool(os.environ.get(item.name)) or item.name in stored,
                    "source": "shell"
                    if os.environ.get(item.name)
                    else "project"
                    if item.name in stored
                    else None,
                }
                for item in app.secrets
            ],
            "credentials": [
                {"name": item.name, "required": item.required, "description": item.description}
                for item in app.credentials
            ],
        }
        for app in definition.apps
    ]


def _agent_tools(environment: Any) -> list[dict[str, Any]]:
    """The tools the model is offered, exactly as it sees them.

    Returns:
        One entry per tool, with the App and action it calls.
    """
    return [
        {
            "name": item.name,
            "app": item.app,
            "action": item.action,
            "read_only": not item.mutates_state,
            "description": item.description,
        }
        for item in environment.definition().actions
    ]


def _agent_credentials(agent: Any) -> list[dict[str, Any]]:
    """The credentials an Agent declares, and whether you have a value. Never the value.

    Returns:
        One entry per credential.
    """
    import os

    import httpx

    from plural.cli.common import session, signed_in
    from plural.errors import PluralError

    declared = agent._definition().credentials
    saved: set[str] = set()
    if set(declared) - set(os.environ):
        try:
            studio = signed_in(session()).studio(project=False)
            saved = {str(item["name"]) for item in studio.credentials.list()}
        except (PluralError, ProjectError, OSError, httpx.HTTPError):
            saved = set()
    return [
        {
            "name": key,
            "scopes": list(item.scopes),
            "source": "account" if key in saved else "shell" if os.environ.get(key) else None,
        }
        for key, item in declared.items()
    ]


def _live_apps(benchmark: Any) -> list[str]:
    """Live Apps a Benchmark's Tasks read from, each named once.

    Returns:
        App names, in the order the Tasks first use them.
    """
    live: list[str] = []
    for task in benchmark.tasks:
        for app in task.environment.definition().apps:
            if not app.reproducible and app.name not in live:
                live.append(app.name)
    return live


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
    if kind is ENVIRONMENT:
        from plural.cli.generate_commands import add_generators

        add_generators(app)

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
        apps = _app_summary(resource.value) if kind is ENVIRONMENT else None
        tools = _agent_tools(resource.value) if kind is ENVIRONMENT else []
        if apps is not None:
            payload = {**payload, "apps": apps, "tools": tools}
        credentials = _agent_credentials(resource.value) if kind is AGENT else []
        if kind is AGENT:
            payload = {**payload, "credentials": credentials}
        live = _live_apps(resource.value) if kind is BENCHMARK else []
        if kind is BENCHMARK:
            payload = {**payload, "reproducible": not live, "live_apps": live}
        unfinished = space.unfinished([ref])
        payload = {**payload, "unfinished": unfinished}

        def text() -> None:
            typer.echo(f"{ref} is valid: {resource.content_hash}")
            if unfinished:
                typer.echo(
                    "\nIt runs locally, but these places are unfinished. Finish each one and "
                    "delete its PLURAL-TODO line before you push it or run it with --record:"
                )
                for marker in unfinished:
                    typer.echo(f"  {marker}")
            for app in apps or ():
                typer.echo(f"\nApp {app['name']} ({app['kind']}, {app['control']})")
                for action in app["actions"]:
                    marker = "" if action["mutates_state"] else "  [read-only]"
                    typer.echo(f"  {action['name']}{marker}")
                for secret in app["secrets"]:
                    status = secret_status(secret)
                    typer.echo(f"  secret {secret['name']}: {status}")
                for credential in app["credentials"]:
                    typer.echo(
                        f"  credential {credential['name']}: supplied by the Agent that runs"
                    )
            if tools:
                typer.echo(f"\nThe Agent sees {len(tools)} tool{'s' if len(tools) != 1 else ''}:")
                width = max(len(tool["name"]) for tool in tools)
                for tool in tools:
                    summary = tool["description"].splitlines()[0] if tool["description"] else ""
                    if len(summary) > 72:
                        summary = summary[:71] + "…"
                    typer.echo(f"  {tool['name']:<{width}}  {summary}".rstrip())
                if len(tools) > 40:
                    typer.echo(
                        "  That is a lot for one model to choose from; offer fewer with "
                        "`tools:` or `exclude:` on an App."
                    )
            for credential in credentials:
                scopes = ", ".join(credential["scopes"]) or "no scopes listed"
                status = (
                    "saved in your account"
                    if credential["source"] == "account"
                    else "set in your shell"
                    if credential["source"] == "shell"
                    else f"NOT SET: run `plural credential set {credential['name']}`"
                )
                typer.echo(f"  credential {credential['name']} ({scopes}): {status}")
            if live:
                one = len(live) == 1
                typer.echo(
                    f"\nNot reproducible: {', '.join(live)} "
                    f"{'is a live App that only reads' if one else 'are live Apps that only read'}"
                    ", so results can change as the data behind them changes."
                )

        emit(payload, as_json=as_json, text=text)

    @app.command("push")
    @handled
    def push_command(
        name: str | None = typer.Argument(None, help=NAME_HELP),
        with_deps: bool = typer.Option(
            False, "--with-deps", help="Also push local dependencies that are not hosted yet."
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Add a revision even though the hosted resource moved since you last synced.",
        ),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Validate and push an immutable, private revision to the bound project.

        The hosted project numbers revisions. Pushing content it already holds
        reuses that revision. Without --with-deps, every dependency must
        already be pushed with identical content. Nothing is uploaded unless
        the whole push can succeed.
        """
        space = workspace()
        ref = _ref(space, kind, name)
        studio, binding = project_studio(space, session())
        result = push(space, studio, binding, ref, with_deps=with_deps, force=force)
        _emit_push(binding.project_slug, result.steps, as_json=as_json)

    @app.command("release")
    @handled
    def release_command(
        name: str = typer.Argument(help="Resource to release."),
        version: str = typer.Argument(help="Release version, MAJOR.MINOR.PATCH."),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Label the revision matching your files with a release version, pushing it first.

        A version names one revision forever, so collaborators and Jobs can
        refer to it as name@VERSION.
        """
        space = workspace()
        ref = _ref(space, kind, name)
        studio, binding = project_studio(space, session())
        result = release(space, studio, binding, ref, version)
        _emit_push(binding.project_slug, result.steps, as_json=as_json)

    @app.command("pull")
    @handled
    def pull_command(
        name: str | None = typer.Argument(None, help=VERSIONED_NAME_HELP),
        revision: str | None = typer.Option(None, "--revision", "-r", hidden=True),
        version: str | None = typer.Option(None, "--version", hidden=True),
        with_deps: bool = typer.Option(
            False,
            "--with-deps",
            help=(
                "Also replace dependencies you already have with the exact revisions it pins. "
                "Missing dependencies are always restored."
            ),
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Replace local files that differ. The old copy is kept under .plural/backups.",
        ),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Restore a hosted revision's editable files into this project.

        Name a retained revision as NAME@REF.
        """
        if revision or version:
            deprecated("--revision" if revision else "--version", f"{name or 'NAME'}@REF")
        space = workspace()
        ref, selector = _versioned_ref(space, kind, name, revision or version)
        studio, binding = project_studio(space, session())
        steps = pull(
            space,
            studio,
            ref,
            selector=selector,
            force=force,
            with_deps=with_deps,
            project_id=binding.project_id,
        )
        payload = [
            {
                "resource": str(step.ref),
                "revision": step.label,
                "number": step.number,
                "version": step.version,
                "status": step.status,
                "backup": str(step.backup) if step.backup else None,
                "rebuilt": step.rebuilt,
            }
            for step in steps
        ]

        def text() -> None:
            rows(
                (
                    (
                        step.ref,
                        step.label,
                        step.status
                        + (" (rebuilt from its definition)" if step.rebuilt else "")
                        + (
                            f" (backup: {relative(step.backup, space.project.root)})"
                            if step.backup
                            else ""
                        ),
                    )
                    for step in steps
                ),
                ("resource", "revision", "result"),
            )
            if any(step.rebuilt for step in steps):
                typer.echo(REBUILT_NOTE)

        emit(payload, as_json=as_json, text=text)

    @app.command("show")
    @handled
    def show(
        name: str | None = typer.Argument(None, help=VERSIONED_NAME_HELP),
        local: bool = typer.Option(False, "--local", help="Only read local files."),
        hosted: bool = typer.Option(False, "--hosted", help="Only read the hosted project."),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Show a resource: the local copy if there is one, otherwise the hosted one.

        An invalid local copy is shown with its problems, never swapped for the
        hosted one.
        NAME@REF shows that revision: the working copy when it holds
        exactly that content, otherwise the retained hosted revision.
        """
        if local and hosted:
            raise ProjectError("Choose --local or --hosted, not both.")
        space = workspace()
        ref, version = _versioned_ref(space, kind, name, None)
        if version is not None and not hosted and holds_version(space, ref, version):
            held = _local_payload(space, space.load(ref))
            emit(held, as_json=as_json, text=lambda: _print_local(held))
            return
        if version is not None and local:
            raise ProjectError(
                f"The working copy of {ref} is not revision {version}. "
                f"Restore it with `plural {kind.cli} pull {name}`."
            )
        if version is not None:
            hosted = True
        if kind is HARNESS and ref.name in BUILTIN_HARNESS_NAMES and not space.project.has(ref):
            spec = get_builtin(ref.name)
            payload: dict[str, Any] = {
                "location": "built-in",
                "resource": str(ref),
                "pinned_version": spec.pinned_version,
                "harness_config": builtin_schema(ref.name),
            }
            emit(payload, as_json=as_json, text=lambda: _print_builtin(payload))
            return
        if not hosted and space.project.has(ref):
            try:
                payload = _local_payload(space, space.load(ref))
            except ProjectError as exc:
                payload = _invalid_payload(space, ref, exc)
                emit(payload, as_json=as_json, text=lambda: _print_invalid(payload))
                return
            emit(payload, as_json=as_json, text=lambda: _print_local(payload))
            return
        if local:
            raise ProjectError(f"No local {kind.label} named {ref.name!r} in this project.")
        studio, binding = project_studio(space, session())
        parent, revisions = hosted_resource(studio, ref)
        if version is not None:
            revisions = [select_revision(ref, revisions, version)]
        current_id = parent.get("current_revision_id")
        payload = {
            "location": "hosted",
            "resource": str(ref),
            "project": binding.project_slug,
            "id": parent.get("id"),
            "description": parent.get("description"),
            "revisions": [
                {
                    "number": item.number,
                    "version": item.version,
                    "revision_id": item.revision_id,
                    "content_hash": item.content_hash,
                    "current": item.revision_id == current_id,
                    "restorable": item.package_digest is not None,
                }
                for item in revisions
            ],
        }

        def text() -> None:
            typer.echo(f"{kind.label} {ref.name} (hosted, project {binding.project_slug})")
            rows(
                (
                    (
                        f"#{item.number}" if item.number is not None else "-",
                        item.version or "-",
                        item.content_hash[:19],
                        "current" if item.revision_id == current_id else "",
                        "yes" if item.package_digest else "no",
                    )
                    for item in revisions
                ),
                ("revision", "version", "content hash", "", "pullable"),
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
                            "revision": _locked_label(space, resource),
                            "status": _lock_status(space, resource),
                        }
                    )
                except ProjectError as exc:
                    items.append(
                        {
                            "location": "local",
                            "name": resource_name,
                            "revision": None,
                            "status": f"invalid ({counted(len(exc.problems) or 1, 'problem')})",
                        }
                    )
        if kind is HARNESS and not (local or hosted):
            items.extend(
                {
                    "location": "built-in",
                    "name": builtin,
                    "revision": get_builtin(builtin).pinned_version,
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
                            "revision": revision_label(
                                record.get("current_revision_number"),
                                record.get("current_version"),
                            )
                            or None,
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
                        (item["name"], item["location"], item["revision"] or "-", item["status"])
                        for item in items
                    ),
                    ("name", "where", "revision", "status"),
                )
            if note:
                typer.echo(note)

        emit(items, as_json=as_json, text=text)

    @app.command("delete")
    @handled
    def delete_command(
        name: str = typer.Argument(help=f"The {kind.label} to delete."),
        hosted: bool = typer.Option(
            False,
            "--hosted",
            help="Also delete it from the hosted project. Jobs and Trials that pinned its "
            "revisions can still read them.",
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Delete without asking."),
        as_json: bool = JSON_OPTION,
    ) -> None:
        """Delete a resource's local folder, refusing while other local resources use it.

        Without --hosted this is a local edit: the hosted project keeps the
        resource until you add --hosted.
        """
        space = workspace()
        ref = _ref(space, kind, name, must_exist=False)
        local = space.project.has(ref)
        if not local and not hosted:
            if kind is HARNESS and ref.name in BUILTIN_HARNESS_NAMES:
                raise ProjectError(f"{ref.name} is a built-in Harness; there is nothing to delete.")
            raise ProjectError(
                f"No local {kind.label} named {ref.name!r} in this project. Add --hosted to "
                "delete it from the hosted project."
            )
        users = _dependents(space, ref)
        if users:
            raise ProjectError(
                f"{kind.label} {ref.name} is used by other resources in this project. Change "
                "or delete them first:",
                [str(item) for item in users],
            )
        directory = space.project.resource_dir(ref)
        shown = relative(directory, space.project.root)
        where = " and ".join(
            item for item, wanted in ((shown, local), ("the hosted project", hosted)) if wanted
        )
        if not yes:
            if not sys.stdin.isatty():
                raise ProjectError(f"Deleting {kind.label} {ref.name} needs --yes here.")
            typer.confirm(f"Delete {kind.label} {ref.name} from {where}?", abort=True)
        hosted_status = None
        if hosted:
            studio, binding = project_studio(space, session())
            api = getattr(studio, kind.collection)
            parent = api.find(slugify(ref.name))
            if parent is None:
                hosted_status = f"not in hosted project {binding.project_slug}"
            else:
                api.delete(str(parent["id"]))
                hosted_status = f"deleted from hosted project {binding.project_slug}"
        if local:
            shutil.rmtree(directory)
            lock = space.project.read_lock()
            if lock.resources.pop(str(ref), None) is not None:
                space.project.write_lock(lock)
        payload = {
            "resource": str(ref),
            "local": shown if local else None,
            "hosted": hosted_status,
        }

        def text() -> None:
            if local:
                success(f"Deleted {kind.label} {ref.name} ({shown}).")
            if hosted_status:
                typer.echo(f"{kind.label} {ref.name}: {hosted_status}.")
            if local and not hosted:
                typer.echo(
                    "The hosted project still has it, if you pushed it. Delete it there with "
                    f"`plural {kind.cli} delete {ref.name} --hosted`."
                )

        emit(payload, as_json=as_json, text=text)

    if kind is BENCHMARK:
        _benchmark_membership(app)
    return app


def _dependents(space: Workspace, ref: ResourceRef) -> list[ResourceRef]:
    """Local resources whose manifests name ``ref``.

    Returns:
        Each one, by kind then name.
    """
    found = []
    for other_kind in KINDS:
        for other in space.project.names(other_kind):
            candidate = ResourceRef(other_kind.name, other)
            if candidate == ref:
                continue
            try:
                if ref in space.dependencies(candidate):
                    found.append(candidate)
            except ProjectError:
                continue
    return found


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

    def create_environment(name: str, *, python: bool, bare: bool) -> None:
        space = workspace()
        check_name(name, kind.label)
        root = space.project.root
        directory = space.project.resource_dir(ResourceRef(kind.name, name))
        if directory.exists():
            raise ProjectError(f"{relative(directory, root)} already exists. Choose another name.")
        typer.echo(f"Created {kind.label} {name}:")
        for path in resource_scaffold(kind, name, python=python).write(directory):
            typer.echo(f"  {relative(path, root)}")
        task = None
        if not bare:
            for starter_kind, starter, scaffold in starter_scaffolds(name):
                folder = space.project.resource_dir(ResourceRef(starter_kind.name, starter))
                if folder.exists():
                    typer.echo(f"Kept the existing {starter_kind.label} {starter}.")
                    continue
                typer.echo(f"Created starter {starter_kind.label} {starter}:")
                for path in scaffold.write(folder):
                    typer.echo(f"  {relative(path, root)}")
                if starter_kind is TASK:
                    task = starter
        if task:
            typer.echo(
                f"\nIt runs as it is. Try it:\n"
                f"  plural run --task {task} --model {STARTER_MODEL}\n"
                "Then make it yours: each PLURAL-TODO marks an example to replace, and "
                f"`plural task validate {task}` lists the ones left. Nothing is pushed or "
                "recorded until they are gone."
            )
        else:
            typer.echo(
                "Fill in the places marked PLURAL-TODO, then run "
                f"`plural {kind.cli} validate {name}`."
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
                [], "--verifier", help="Verifier that scores it. Repeat for more."
            ),
        ) -> None:
            """Create a Task with instructions, one Environment, and its Verifiers."""
            create(name, environment=environment, verifiers=tuple(verifier))

    elif kind is AGENT:

        @app.command("init")
        @handled
        def init_agent(
            name: str = typer.Argument(help="Agent name."),
            model: str | None = typer.Option(
                None,
                "--model",
                "-m",
                help="Catalog model id, from `plural model list`. Asked for when omitted "
                "in a terminal.",
            ),
            harness: str | None = typer.Option(None, "--harness", help="Harness name."),
        ) -> None:
            """Create a saved Agent: a model, instructions, and an optional Harness."""
            if not model and sys.stdin.isatty():
                model = typer.prompt(
                    "Model (a catalog id; `plural model list` shows them)", default=STARTER_MODEL
                ).strip()
            if not model:
                raise ProjectError(
                    f"An Agent needs a model. Run `plural agent init {name} --model MODEL`, "
                    f"such as --model {STARTER_MODEL}; `plural model list` shows the models "
                    "you may use."
                )
            create(name, model=model, harness=harness)

    elif kind is ENVIRONMENT:

        @app.command("init")
        @handled
        def init_environment(
            name: str = typer.Argument(help="Environment name."),
            python: bool = typer.Option(
                False,
                "--python",
                help="Start from a Python App class instead of a FastMCP server.",
            ),
            bare: bool = typer.Option(
                False,
                "--bare",
                help="Create only the Environment, without the starter Task and Verifier.",
            ),
        ) -> None:
            """Create an Environment whose App is a FastMCP server you write.

            A starter Task and Verifier come with it, so the example runs and
            scores at once: `plural run --task NAME-first --model MODEL`.
            """
            create_environment(name, python=python, bare=bare)

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
            f"Added Task {task} to Benchmark {ref.name}."
            if changed
            else f"Benchmark {ref.name} already includes Task {task}."
        )
        _maybe_push(space, ref, push_after, changed=changed)

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
        changed = remove_task(space.project, ref.name, task)
        typer.echo(f"Removed Task {task} from Benchmark {ref.name}.")
        _maybe_push(space, ref, push_after, changed=changed)


def _maybe_push(space: Workspace, ref: ResourceRef, enabled: bool, *, changed: bool) -> None:
    if not enabled:
        if changed:
            typer.echo(f"Push the change with `plural benchmark push {ref.name}`.")
        return
    studio, binding = project_studio(space, session())
    result = push(space, studio, binding, ref)
    step = result.steps[-1]
    typer.echo(f"Pushed {ref} {step.label} to {binding.project_slug} ({step.status}).")


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
    if "@" in name:
        bare = name.partition("@")[0]
        raise ProjectError(
            f"This command works on the working copy of {bare!r}, which has one revision. "
            f"Drop '@...', or use `plural {kind.cli} pull {name}` or "
            f"`plural run --{kind.name} {name}` to use a retained revision."
        )
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


def _versioned_ref(
    space: Workspace, kind: ResourceKind, name: str | None, version: str | None
) -> tuple[ResourceRef, str | None]:
    """Resolve ``name`` or ``name@REF``; a deprecated ``--revision`` must agree with ``@``.

    Raises:
        ProjectError: When ``@`` and ``--revision`` name different revisions.
    """
    if name is None or "@" not in name:
        return _ref(space, kind, name, must_exist=False), version
    bare, pinned = split_version(name, kind.label)
    if version is not None and version != pinned:
        raise ProjectError(f"{name} and --revision {version} name different revisions.")
    return ResourceRef(kind.name, bare), pinned


def _lock_status(space: Workspace, resource: LocalResource) -> str:
    entry = space.project.read_lock().resources.get(str(resource.ref))
    if entry is None:
        return "not pushed"
    label = revision_label(entry.number, entry.version, "pushed")
    if entry.content_hash == resource.content_hash:
        return f"pushed ({label})"
    return f"changed since push ({label})"


def _locked_label(space: Workspace, resource: LocalResource) -> str | None:
    entry = space.project.read_lock().resources.get(str(resource.ref))
    if entry is None or entry.content_hash != resource.content_hash:
        return None
    return revision_label(entry.number, entry.version) or None


def _emit_push(project_slug: str, steps: list[PushStep], *, as_json: bool) -> None:
    payload = {
        "project": project_slug,
        "steps": [
            {
                "resource": str(step.ref),
                "revision": step.label,
                "number": step.number,
                "version": step.version,
                "status": step.status,
                "revision_id": step.revision_id,
                "note": step.note,
            }
            for step in steps
        ],
    }

    def text() -> None:
        typer.echo(f"Pushed to hosted project {project_slug} (private):")
        rows(
            ((step.ref, step.label, step.status) for step in steps),
            ("resource", "revision", "result"),
        )
        for step in steps:
            if step.note:
                typer.echo(f"Note: {step.ref} {step.note}, so the new revision has no version.")

    emit(payload, as_json=as_json, text=text)


def _local_payload(space: Workspace, resource: LocalResource) -> dict[str, Any]:
    value = resource.value
    return {
        "location": "local",
        "resource": str(resource.ref),
        "path": relative(resource.directory, space.project.root),
        "revision": _locked_label(space, resource),
        "content_hash": resource.content_hash,
        "description": getattr(value, "description", None) or None,
        "depends_on": [str(item) for item in resource.dependencies],
        "hosted": _lock_status(space, resource),
    }


def _invalid_payload(space: Workspace, ref: ResourceRef, exc: ProjectError) -> dict[str, Any]:
    try:
        depends_on = [str(item) for item in space.dependencies(ref)]
    except ProjectError:
        depends_on = []
    return {
        "location": "local",
        "resource": str(ref),
        "path": relative(space.project.resource_dir(ref), space.project.root),
        "valid": False,
        "problems": list(exc.problems) or [exc.message],
        "depends_on": depends_on,
    }


def _print_invalid(payload: dict[str, Any]) -> None:
    kind, _, name = str(payload["resource"]).partition("/")
    info = next(item for item in KINDS if item.name == kind)
    typer.echo(f"{info.label} {name} (local, {payload['path']}): not valid yet")
    typer.echo(f"  Depends on:   {', '.join(payload['depends_on']) or '-'}")
    typer.echo("  Problems:")
    for problem in payload["problems"]:
        typer.echo(f"    - {problem}")
    typer.echo(f"Fix them, then check with `plural {info.cli} validate {name}`.")


def _print_builtin(payload: dict[str, Any]) -> None:
    name = str(payload["resource"]).partition("/")[2]
    typer.echo(f"Harness {name} (built-in, version {payload['pinned_version']})")
    typer.echo(f"  Use it with `harness: {name}` in agent.yaml or `plural run --harness {name}`.")
    properties = payload["harness_config"].get("properties", {})
    if properties:
        typer.echo("  harness_config:")
        for key, value in properties.items():
            typer.echo(f"    {key}: {value.get('description') or value.get('type') or ''}")


def _print_local(payload: dict[str, Any]) -> None:
    kind, _, name = str(payload["resource"]).partition("/")
    label = next(item.label for item in KINDS if item.name == kind)
    typer.echo(f"{label} {name} (local, {payload['path']})")
    typer.echo(f"  Revision:     {payload['revision'] or 'not pushed'}")
    typer.echo(f"  Content hash: {payload['content_hash']}")
    if payload["description"]:
        typer.echo(f"  Description:  {payload['description']}")
    typer.echo(f"  Depends on:   {', '.join(payload['depends_on']) or '-'}")
    typer.echo(f"  Hosted:       {payload['hosted']}")
