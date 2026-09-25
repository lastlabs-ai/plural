"""``plural project``: create a project and register it with a hosted project."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer

from plural.auth import AuthClient, Profile, Session, load_config, save_config
from plural.cli.common import (
    JSON_OPTION,
    details,
    emit,
    handled,
    note,
    relative,
    rows,
    session,
    signed_in,
    success,
    workspace,
)
from plural.project import (
    KINDS,
    Project,
    ProjectBinding,
    ProjectError,
    check_name,
    find_project_root,
)
from plural.project.sync import ProjectPushPlan, apply_project_push, plan_project_push
from plural.project.templates import project_scaffold

project_app = typer.Typer(help="Create, register, and inspect projects.", no_args_is_help=True)


@project_app.command("init")
@handled
def init(
    name: str = typer.Argument(help="Project name: lowercase letters, digits, and hyphens."),
    push: bool = typer.Option(
        False,
        "--push",
        help="Create a hosted project with this name and select it as your scope.",
    ),
    connect: bool = typer.Option(
        False,
        "--connect",
        help="Bind to the hosted project that already has this name. Requires --push.",
    ),
    hosted_name: str | None = typer.Option(
        None,
        "--name",
        help="Hosted project name, when it should differ from the local project. Requires --push.",
    ),
) -> None:
    """Create a project in ./<name>, or register the project you are in.

    Without --push this works offline. With --push, an existing local project
    is registered as it is; no local file is overwritten. A hosted project
    that already has this name is left alone unless --connect is set.
    """
    check_name(name, "project")
    project = _existing(name)
    if project is None:
        root = Path.cwd() / name
        if root.exists() and any(root.iterdir()):
            raise ProjectError(
                f"{root} already exists and is not an empty directory. Choose another name or "
                "run this inside the existing project."
            )
        written = project_scaffold(name).write(root)
        project = Project.at(root)
        typer.echo(f"Created project {name} in {root}")
        for path in written:
            typer.echo(f"  {relative(path, root)}")
    else:
        typer.echo(
            f"Project {name} already exists in {project.root}; leaving its files as they are."
        )
    if connect and not push:
        raise ProjectError("--connect needs --push.")
    if hosted_name and not push:
        raise ProjectError("--name needs --push.")
    if push:
        binding = _register(project, signed_in(session()), connect=connect, hosted_name=hosted_name)
        success(f"Registered with hosted project {binding.project_slug} (private).")
        details([("Scope", binding.project_slug)])
    if project.root != Path.cwd().resolve():
        typer.echo(f"Next: cd {relative(project.root, Path.cwd().resolve())}")
    typer.echo("Next: plural env init <name>")


@project_app.command("show")
@handled
def show(
    name: str = typer.Argument(help="Project name."),
    local: bool = typer.Option(False, "--local", help="Only look at local files."),
    hosted: bool = typer.Option(False, "--hosted", help="Only look at the hosted project."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show a project, local copy first, then hosted."""
    if local and hosted:
        raise ProjectError("Choose --local or --hosted, not both.")
    project = None if hosted else _existing(name)
    if project is not None:
        payload = _local_view(project)
        emit(payload, as_json=as_json, text=lambda: _print_local(payload))
        return
    if local:
        raise ProjectError(f"No local project named {name!r} here.")
    current = signed_in(session())
    studio = current.studio(project=False)
    found = studio.projects.find(name)
    if found is None:
        raise ProjectError(f"No project named {name!r}, locally or in your hosted account.")
    payload = {"location": "hosted", **found}
    payload.pop("default_api_key", None)

    def text() -> None:
        typer.echo(f"Project {found.get('slug')} (hosted)")
        typer.echo(f"  Name:       {found.get('name')}")
        typer.echo(f"  Id:         {found.get('id')}")
        typer.echo(f"  Visibility: {found.get('visibility')}")
        typer.echo(f"  Your role:  {found.get('role')}")

    emit(payload, as_json=as_json, text=text)


@project_app.command("push")
@handled
def push(
    yes: bool = typer.Option(False, "--yes", "-y", help="Push without asking."),
    bump: bool = typer.Option(
        False,
        "--bump",
        help="Give each changed resource the next patch version.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Add revisions even if the hosted copy changed since this checkout last synced.",
    ),
    connect: bool = typer.Option(
        False,
        "--connect",
        help="Bind to the hosted project that already has this name.",
    ),
    hosted_name: str | None = typer.Option(
        None,
        "--name",
        help="Hosted project name, when this checkout is not bound yet.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Push every local resource to the bound hosted project.

    New revisions are added dependencies first. Existing revisions are never
    overwritten or deleted. A resource whose files changed but whose version
    did not is refused until you bump the version or pass --bump.
    """
    space = workspace()
    project = space.project
    binding = _register(project, signed_in(session()), connect=connect, hosted_name=hosted_name)
    studio = session().studio(project=binding.project_id)
    plan = plan_project_push(space, studio, binding.project_id, bump=bump, force=force)
    payload = _push_payload(binding, plan)
    if not as_json:
        _print_push_plan(binding, plan)
    if plan.changes and not yes:
        _confirm_push()
    if not plan.changes:
        if as_json:
            emit(payload, as_json=True)
        else:
            success("Everything is already pushed.")
        return
    steps = apply_project_push(space, studio, binding, plan)
    payload["steps"] = [
        {
            "resource": str(step.ref),
            "version": step.version,
            "status": step.status,
            "revision_id": step.revision_id,
        }
        for step in steps
    ]
    emit(
        payload,
        as_json=as_json,
        text=lambda: success(
            f"Pushed {sum(step.status == 'pushed' for step in steps)} revisions "
            f"to {binding.project_slug}."
        ),
    )


def _existing(name: str) -> Project | None:
    """The local project called ``name``: the enclosing one, or ./<name>.

    Raises:
        ProjectError: Inside a different project.
    """
    root = find_project_root()
    if root is not None:
        project = Project.at(root)
        if project.name != name:
            raise ProjectError(
                f"You are inside project {project.name!r} ({project.root}). Projects cannot "
                "be nested; run this from another directory."
            )
        return project
    candidate = Path.cwd() / name
    if (candidate / "project.yaml").is_file():
        return Project.at(candidate)
    return None


def _register(
    project: Project,
    current: Session,
    *,
    connect: bool = False,
    hosted_name: str | None = None,
) -> ProjectBinding:
    """Bind ``project`` to a hosted project, creating it privately if needed.

    A checkout that is already bound to this service keeps that project.
    An unbound checkout never attaches to an existing same-named project
    unless ``connect`` is set, and ``hosted_name`` creates or selects a
    different name.

    Raises:
        ProjectError: When the credential cannot create projects, or when an
            existing hosted project would be reused without ``--connect``.
    """
    target = hosted_name or project.name
    if hosted_name:
        check_name(hosted_name, "project")
    existing = project.read_binding()
    studio = current.studio(project=False)
    if existing is not None and existing.api_url.rstrip("/") == current.api_url.rstrip("/"):
        if hosted_name and hosted_name != existing.project_slug:
            raise ProjectError(
                f"This directory is already bound to {existing.project_slug!r}. "
                "Remove .plural/project.json to bind it somewhere else."
            )
        studio.account = existing.account_id or studio.account
        try:
            record = studio.projects.get(existing.project_id)
        except Exception:  # noqa: BLE001
            record = None
        if record is not None:
            _select(current, existing)
            return existing
    assert current.token is not None
    with AuthClient(current.api_url) as client:
        restriction = client.status(current.token)
    found = studio.projects.find(target)
    if found is None:
        if connect:
            raise ProjectError(
                f"No hosted project named {target!r}. Run without --connect to create it."
            )
        if restriction.project_id:
            raise ProjectError(
                "This API key is limited to one project and cannot create projects. Sign in "
                "with `plural auth login`, or use an account-level API key."
            )
        found = studio.projects.create(name=target, description=project.manifest.description)
    elif not connect:
        raise ProjectError(
            f"{target!r} already exists in this account. "
            "Run again with --connect to use it, or --name to create a new one."
        )
    binding = ProjectBinding(
        api_url=current.api_url.rstrip("/"),
        account_id=str(found.get("owner_account_id") or current.account_id or "") or None,
        project_id=str(found["id"]),
        project_slug=str(found.get("slug") or target),
        project_name=str(found.get("name") or target),
    )
    project.write_binding(binding)
    _select(current, binding)
    return binding


def _select(current: Session, binding: ProjectBinding) -> None:
    config = load_config()
    profile = config.profiles.get(current.profile, Profile())
    save_config(
        config.with_profile(
            current.profile,
            profile.model_copy(
                update={
                    "account_id": binding.account_id,
                    "project_id": binding.project_id,
                    "project_slug": binding.project_slug,
                }
            ),
        )
    )


def _local_view(project: Project) -> dict[str, Any]:
    binding = project.read_binding()
    return {
        "location": "local",
        "name": project.name,
        "description": project.manifest.description,
        "root": str(project.root),
        "hosted_project": binding.project_slug if binding else None,
        "resources": {kind.name: project.names(kind) for kind in KINDS},
    }


def _print_local(payload: dict[str, Any]) -> None:
    typer.echo(f"Project {payload['name']} (local)")
    typer.echo(f"  Path:   {payload['root']}")
    hosted = payload["hosted_project"]
    typer.echo(
        "  Hosted: " + (f"bound to {hosted}" if hosted else "not registered (`--push` to register)")
    )
    rows(
        ((kind, ", ".join(names) or "-") for kind, names in payload["resources"].items()),
        ("resource", "local names"),
    )


def _push_payload(binding: ProjectBinding, plan: ProjectPushPlan) -> dict[str, Any]:
    return {
        "project": binding.project_slug,
        "steps": [
            {
                "resource": str(step.ref),
                "version": step.version,
                "previous_version": step.previous_version,
                "action": step.action,
            }
            for step in plan.steps
        ],
        "hosted_only": [str(ref) for ref in plan.hosted_only],
    }


def _print_push_plan(binding: ProjectBinding, plan: ProjectPushPlan) -> None:
    typer.echo(f"Project {binding.project_slug}")
    rows(
        (
            (
                step.ref,
                f"{step.previous_version} -> {step.version}" if step.bumped else step.version,
                step.action,
            )
            for step in plan.steps
        ),
        ("resource", "version", "result"),
    )
    if plan.hosted_only:
        note("These hosted resources are not in this checkout and will be left as they are:")
        for ref in plan.hosted_only:
            typer.echo(f"  {ref}")


def _confirm_push() -> None:
    if not sys.stdin.isatty():
        raise ProjectError("Pass --yes to push without a prompt.")
    if not typer.confirm("Push these revisions?"):
        raise ProjectError("Nothing was uploaded.")
