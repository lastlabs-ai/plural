"""``plural secret``: values for the secrets Apps and Verifiers declare.

An App names the secrets it needs, such as ``SALESFORCE_TOKEN``; it never holds
their values. Set a value here and the hosted project keeps it encrypted.
`plural run` fills any secret you have not exported from the project, and
passes each value only to the App, Verifier, or endpoint that declared it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import typer

from plural.apps.definition import SecretReference
from plural.cli.common import JSON_OPTION, emit, fail, handled, muted, rows, success
from plural.cli.runtime_commands import _project_studio
from plural.errors import PluralError
from plural.project import ProjectError

secret_app = typer.Typer(
    help=(
        "Set the project's setup values, stored encrypted in the hosted project.\n\n"
        "Apps' reset and snapshot commands and Verifiers use secrets; the model never "
        "sees them. `plural env validate` lists the secrets each App needs. Set one with "
        "`plural secret set NAME`; `plural run` then supplies it to the App. For your own "
        "values, such as your API token, use `plural credential`."
    ),
    no_args_is_help=True,
)


def _name(value: str) -> str:
    try:
        return SecretReference(name=value).name
    except ValueError as exc:
        fail(
            f"{value!r} is not a usable secret name. Use upper-case letters, digits, "
            "and underscores, such as SALESFORCE_TOKEN.",
            [str(exc).splitlines()[-1].strip()],
        )


@secret_app.command("list")
@handled
def secret_list(as_json: bool = JSON_OPTION) -> None:
    """List the secrets set in the project, never their values."""
    studio, project = _project_studio()
    items = studio.secrets.list()
    emit(
        items,
        as_json=as_json,
        text=lambda: (
            rows(
                ((item["name"], item["hint"], item["updated_at"]) for item in items),
                ("NAME", "ENDS WITH", "UPDATED"),
            )
            if items
            else typer.echo(f"No secrets set in project {project}.")
        ),
    )


@secret_app.command("set")
@handled
def secret_set(
    name: str = typer.Argument(help="The secret's name, as the App declares it."),
    from_env: bool = typer.Option(
        False, "--from-env", help="Read the value from the environment variable of that name."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Set a secret's value in the hosted project. Prompts without echoing."""
    name = _name(name)
    if from_env:
        value = os.environ.get(name, "")
        if not value:
            fail(f"{name} is not set in your environment.")
    elif sys.stdin.isatty():
        value = typer.prompt(f"Value for {name}", hide_input=True)
    else:
        value = sys.stdin.read().rstrip("\n")
    if not value:
        fail(f"{name} needs a value.")
    studio, project = _project_studio()
    item = studio.secrets.set(name, value)
    emit(
        item,
        as_json=as_json,
        text=lambda: success(f"Set {name} in project {project} " + muted(f"(ends {item['hint']})")),
    )


@secret_app.command("delete")
@handled
def secret_delete(
    name: str = typer.Argument(help="The secret to remove."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Remove a secret's value from the hosted project."""
    studio, project = _project_studio()
    studio.secrets.delete(_name(name))
    emit(
        {"name": name, "deleted": True},
        as_json=as_json,
        text=lambda: success(f"Deleted {name} from project {project}."),
    )


__all__ = ["secret_app"]


def project_secret_source() -> Callable[[str], str | None]:
    """Look up a secret you have not exported in the hosted project, once per name.

    ``plural env validate`` and the rest load an App by reaching its server,
    which can need a secret. Without a hosted project, or when you may not read
    its secrets, the lookup finds nothing and the App reports what is missing.
    """
    found: dict[str, str | None] = {}

    def lookup(name: str) -> str | None:
        if name not in found:
            found[name] = None
            try:
                studio, _ = _project_studio()
                grant = studio.secrets.resolve([name])
            except (PluralError, ProjectError, OSError, httpx.HTTPError):
                return None
            value = (grant.get("environ") or {}).get(name)
            if value:
                found[name] = str(value)
                typer.echo(muted(f"Using project secret {name}."), err=True)
        return found[name]

    return lookup


def project_secret_names() -> set[str]:
    """Names set in the hosted project, or none without one you may read.

    Returns:
        The stored names; never their values.
    """
    try:
        studio, _ = _project_studio()
        return {str(item["name"]) for item in studio.secrets.list()}
    except (PluralError, ProjectError, OSError, httpx.HTTPError):
        return set()


def secret_status(secret: Mapping[str, Any]) -> str:
    """How a run gets one App secret, for ``validate`` and the ``from-*`` commands.

    Returns:
        A short phrase naming where the value comes from, or how to supply it.
    """
    if secret.get("source") == "shell":
        return "set in your shell"
    if secret.get("source") == "project":
        return "set in the hosted project"
    return f"NOT SET: export it, or run `plural secret set {secret['name']}`"
