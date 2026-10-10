"""``plural secret``: values for the secrets Apps and Verifiers declare.

An App names the secrets it needs, such as ``SALESFORCE_TOKEN``; it never holds
their values. Set a value here and the hosted project keeps it encrypted.
`plural run` fills any secret you have not exported from the project, and
passes each value only to the App, Verifier, or endpoint that declared it.
"""

from __future__ import annotations

import os
import sys

import typer

from plural.apps.definition import SecretReference
from plural.cli.common import JSON_OPTION, emit, fail, handled, muted, rows, success
from plural.cli.runtime_commands import _project_studio

secret_app = typer.Typer(
    help=(
        "Set the secrets your Apps need in the hosted project.\n\n"
        "`plural env validate` lists the secrets each App needs. Set one with "
        "`plural secret set NAME`; `plural run` then supplies it to the App."
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
