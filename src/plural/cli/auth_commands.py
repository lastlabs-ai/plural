"""``plural auth``: credentials and the selected hosted scope."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import typer

from plural.auth import (
    AuthClient,
    AuthStatus,
    Credential,
    Profile,
    Session,
    load_config,
    resolve_session,
    save_config,
)
from plural.cli.common import JSON_OPTION, details, emit, handled, note, session, signed_in, success
from plural.project import Project, ProjectError, find_project_root

auth_app = typer.Typer(
    help="Sign in, sign out, and choose the hosted account or project commands use.",
    no_args_is_help=True,
)


@auth_app.command("login")
@handled
def login(
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the URL only."),
    api_key_stdin: bool = typer.Option(
        False, "--api-key-stdin", help="Store an API key read from standard input instead."
    ),
    from_env: bool = typer.Option(
        False,
        "--from-env",
        help="Store PLURAL_API_KEY from the environment. The value is not printed.",
    ),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Read PLURAL_API_KEY from this file. Other variables in the file are ignored.",
    ),
    api_url: str | None = typer.Option(None, "--api-url", help="Hosted service URL."),
) -> None:
    """Sign in with your browser (or store an API key).

    A browser login acts as you: it reaches every account and project your
    roles allow. Credentials are stored in your OS keyring or a private file
    in your user config directory, never in a project.
    """
    config = load_config()
    current = resolve_session(config=config)
    profile = config.profiles.get(current.profile, Profile())
    if api_url:
        profile = profile.model_copy(update={"api_url": api_url.rstrip("/")})
    target = api_url.rstrip("/") if api_url else current.api_url
    sources = sum((api_key_stdin, from_env, env_file is not None))
    if sources > 1:
        raise ProjectError("Choose one of --api-key-stdin, --from-env, or --env-file.")
    if api_key_stdin:
        credential = Credential(api_key=_prompt_api_key())
    elif from_env or env_file is not None:
        credential = Credential(api_key=_key_from_env(env_file))
    else:
        with AuthClient(target) as client:
            _device, tokens = client.login(
                no_browser=no_browser,
                on_device=lambda device: typer.echo(
                    f"Open {device.verification_uri} and enter code {device.user_code}"
                ),
            )
        credential = tokens.credential()
    assert current.store is not None
    current.store.set(current.profile, credential)
    save_config(config.with_profile(current.profile, profile))
    refreshed = resolve_session()
    profile = _settle_account(refreshed, profile)
    save_config(load_config().with_profile(current.profile, profile))
    success(f"Signed in to {target}")
    _print_scope(resolve_session(), header=False, service=True)


@auth_app.command("logout")
@handled
def logout() -> None:
    """Revoke and remove the stored credential for this profile."""
    current = session()
    if current.credential is not None:
        try:
            with AuthClient(current.api_url) as client:
                client.revoke(current.credential)
        except Exception:  # noqa: BLE001
            typer.echo("Could not reach the service to revoke; removing the local copy.")
    assert current.store is not None
    current.store.delete(current.profile)
    typer.echo("Signed out.")
    if current.environment_key:
        typer.echo("PLURAL_API_KEY is still set in this shell and will keep being used.")


@auth_app.command("status")
@handled
def status(as_json: bool = JSON_OPTION) -> None:
    """Check the credential with the service and show the current scope."""
    current = signed_in(session())
    assert current.token is not None
    with AuthClient(current.api_url) as client:
        remote = client.status(current.token)
    payload = {**_scope_payload(current), "status": remote.model_dump(mode="json")}

    def text() -> None:
        success("Signed in")
        _print_scope(current, header=False, service=True, remote=remote)

    emit(payload, as_json=as_json, text=text)


@auth_app.command("scope")
@handled
def scope(
    target: str | None = typer.Argument(
        None, help="`.` selects account scope. Omit to show the current scope.", metavar="[.]"
    ),
    account: bool = typer.Option(False, "--account", help="Select account scope."),
    project: str | None = typer.Option(
        None, "--project", "-p", help="Select an existing hosted project by name."
    ),
    org: str | None = typer.Option(
        None,
        "--org",
        help="Switch to an organization account (slug or id), or `personal`.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show or change where hosted commands go by default.

    Scope selects a destination; it never changes what your credential may
    do. The new scope is checked with the service before it is saved, and a
    failed check leaves the previous scope in place.
    """
    if target not in {None, "."}:
        raise ProjectError(
            f"Unexpected argument {target!r}. Use `plural auth scope .` for account scope or "
            "`plural auth scope --project <name>`."
        )
    to_account = target == "." or account
    if to_account and project:
        raise ProjectError("Choose account scope or --project, not both.")
    current = session()
    if not (to_account or project or org):
        emit(_scope_payload(current), as_json=as_json, text=lambda: _print_scope(current))
        return
    signed_in(current)
    config = load_config()
    profile = config.profiles.get(current.profile, Profile())
    restriction = _restriction(current)
    account_record = _account(current, org) if org else None
    account_id = account_record["id"] if account_record else current.account_id
    account_slug = account_record["slug"] if account_record else profile.account_slug
    if project:
        studio = current.studio(project=False)
        studio.account = account_id
        found = studio.projects.find(project)
        if found is None:
            raise ProjectError(
                f"No project named {project!r} is available to you"
                + (f" in account {account_slug!r}" if account_slug else "")
                + ". To create it from a local project, run "
                f"`plural project init {project} --push` in its directory."
            )
        if restriction.project_id and restriction.project_id != found["id"]:
            raise ProjectError(
                f"This API key is limited to another project and cannot select {project!r}."
            )
        updated = profile.model_copy(
            update={
                "account_id": str(found.get("owner_account_id") or account_id or "") or None,
                "account_slug": account_slug,
                "project_id": str(found["id"]),
                "project_slug": str(found.get("slug") or project),
            }
        )
    else:
        if restriction.project_id:
            raise ProjectError(
                "This API key is limited to one project, so it cannot use account scope. "
                "Sign in with `plural auth login` for account-level access."
            )
        updated = profile.model_copy(
            update={
                "account_id": account_id,
                "account_slug": account_slug,
                "project_id": None,
                "project_slug": None,
            }
        )
    save_config(config.with_profile(current.profile, updated))
    fresh = resolve_session()
    emit(_scope_payload(fresh), as_json=as_json, text=lambda: _print_scope(fresh))


def _restriction(current: Session) -> AuthStatus:
    assert current.token is not None
    with AuthClient(current.api_url) as client:
        return client.status(current.token)


def _account(current: Session, selector: str) -> dict[str, Any]:
    accounts = current.studio(project=False).accounts.list()
    for item in accounts:
        if selector == "personal" and item.get("type") == "personal":
            return dict(item)
        if selector in {item.get("id"), item.get("slug")}:
            return dict(item)
    available = ", ".join(str(item.get("slug")) for item in accounts) or "none"
    raise ProjectError(f"No account {selector!r} is available to you. Available: {available}.")


def _settle_account(current: Session, profile: Profile) -> Profile:
    """Keep the saved account and project if the new credential still reaches them."""
    try:
        accounts = current.studio(project=False).accounts.list()
    except Exception:  # noqa: BLE001
        return profile
    by_id = {str(item.get("id")): item for item in accounts}
    if profile.account_id and profile.account_id in by_id:
        return profile
    personal = next((item for item in accounts if item.get("type") == "personal"), None)
    chosen = personal or (accounts[0] if accounts else None)
    return profile.model_copy(
        update={
            "account_id": str(chosen["id"]) if chosen else None,
            "account_slug": str(chosen.get("slug")) if chosen else None,
            "project_id": None,
            "project_slug": None,
        }
    )


def _describe_credential(current: Session, remote: AuthStatus | None = None) -> str:
    kind = current.credential_kind
    if kind is None:
        return "none (run `plural auth login`)"
    source = "PLURAL_API_KEY" if current.environment_key else "stored"
    if kind == "login":
        return f"browser login ({source}); acts with your roles"
    if remote is not None and remote.project_id:
        return f"API key ({source}); limited to project {remote.project_id}"
    return f"API key ({source})"


def _scope_payload(current: Session) -> dict[str, Any]:
    binding = _local_binding()
    return {
        "profile": current.profile,
        "api_url": current.api_url,
        "credential": current.credential_kind,
        "account_id": current.account_id,
        "project": current.project_slug or current.project,
        "scope": "project" if current.project else "account",
        "local_project": binding,
    }


def _local_binding() -> dict[str, Any] | None:
    root = find_project_root()
    if root is None:
        return None
    try:
        project = Project.at(root)
        binding = project.read_binding()
    except ProjectError:
        return None
    return {
        "name": project.name,
        "root": str(project.root),
        "bound_to": binding.project_slug if binding else None,
    }


def _prompt_api_key() -> str:
    """Read one API key from stdin after telling the user what to paste."""
    typer.echo("Enter API key:")
    typer.echo(">> ", nl=False)
    key = sys.stdin.readline().strip()
    if not key:
        raise ProjectError("No API key on standard input.")
    return key


def _key_from_env(env_file: Path | None) -> str:
    """Return PLURAL_API_KEY from the environment or one env file.

    Other names in an env file are ignored and never printed.
    """
    if env_file is not None:
        key = _dotenv_value(env_file, "PLURAL_API_KEY")
        if not key:
            raise ProjectError(f"No PLURAL_API_KEY in {env_file}.")
        return key
    key = os.environ.get("PLURAL_API_KEY", "").strip()
    if not key:
        raise ProjectError(
            "No PLURAL_API_KEY in the environment. Export it, or pass --env-file .env."
        )
    return key


def _dotenv_value(path: Path, name: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProjectError(f"Could not read {path}.") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip() or None
    return None


def _print_scope(
    current: Session,
    *,
    header: bool = True,
    service: bool = False,
    remote: AuthStatus | None = None,
) -> None:
    payload = _scope_payload(current)
    if header:
        success("Signed in")
    profile = load_config().profiles.get(current.profile, Profile())
    account = profile.account_slug or current.account_id or "personal"
    if current.project:
        scope_label = f"project {payload['project']} (account {account})"
    else:
        scope_label = f"account {account}"
    pairs: list[tuple[str, str]] = []
    if service:
        pairs.append(("Service", current.api_url))
    pairs.append(("Credential", _describe_credential(current, remote)))
    pairs.append(("Scope", scope_label))
    local = payload["local_project"]
    if local:
        bound = local["bound_to"]
        directory = f"project {local['name']}, " + (
            f"bound to hosted project {bound}" if bound else "not registered (local only)"
        )
        pairs.append(("Directory", directory))
    details(pairs)
    if local and local["bound_to"] and current.project and payload["project"] != local["bound_to"]:
        note(
            f"Pushes from here will be refused until the scope selects {local['bound_to']} "
            "or account scope."
        )
