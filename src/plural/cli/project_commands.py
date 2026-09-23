"""``plural project``: create a project and register it with a hosted project."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from plural.auth import AuthClient, Profile, Session, load_config, save_config
from plural.cli.common import JSON_OPTION, emit, handled, relative, rows, session, signed_in
from plural.project import (
    KINDS,
    Project,
    ProjectBinding,
    ProjectError,
    check_name,
    find_project_root,
)
from plural.project.templates import project_scaffold

project_app = typer.Typer(help="Create, register, and inspect projects.", no_args_is_help=True)


@project_app.command("init")
@handled
def init(
    name: str = typer.Argument(help="Project name: lowercase letters, digits, and hyphens."),
    push: bool = typer.Option(
        False,
        "--push",
        help="Also create (or connect) the hosted project and select it as your scope.",
    ),
) -> None:
    """Create a project in ./<name>, or register the project you are in.

    Without --push this works offline. With --push, an existing local project
    is registered as it is; no local file is overwritten.
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
    if push:
        binding = _register(project, signed_in(session()))
        typer.echo(
            f"Registered with hosted project {binding.project_slug} (private). "
            "Your scope now selects it."
        )
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


def _register(project: Project, current: Session) -> ProjectBinding:
    """Bind ``project`` to a hosted project, creating it privately if needed.

    Raises:
        ProjectError: When the credential cannot create projects.
    """
    existing = project.read_binding()
    studio = current.studio(project=False)
    if existing is not None and existing.api_url.rstrip("/") == current.api_url.rstrip("/"):
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
    found = studio.projects.find(project.name)
    if found is None:
        if restriction.project_id:
            raise ProjectError(
                "This API key is limited to one project and cannot create projects. Sign in "
                "with `plural auth login`, or use an account-level API key."
            )
        found = studio.projects.create(name=project.name, description=project.manifest.description)
    binding = ProjectBinding(
        api_url=current.api_url.rstrip("/"),
        account_id=str(found.get("owner_account_id") or current.account_id or "") or None,
        project_id=str(found["id"]),
        project_slug=str(found.get("slug") or project.name),
        project_name=str(found.get("name") or project.name),
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
