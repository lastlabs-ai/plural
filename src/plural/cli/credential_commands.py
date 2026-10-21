"""``plural credential``: your values for the credentials Agents carry.

An App names the credentials it needs, such as ``SALESFORCE_TOKEN``. An Agent
lists the ones it carries, with their scopes, in its ``agent.yaml``. The values
are yours: you save each one once, encrypted in your Plural account, and every
Agent you run that carries that name acts with it. A coworker running the same
Agent supplies their own. `plural run` passes each value only to the App host,
never to the Harness or the model.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import datetime

import httpx
import typer

from plural.apps.definition import SecretReference
from plural.cli.common import (
    JSON_OPTION,
    alias,
    emit,
    fail,
    handled,
    rows,
    session,
    signed_in,
    success,
)
from plural.credentials import CredentialValue
from plural.errors import PluralError
from plural.jobs import JobSpec
from plural.project import ProjectError
from plural.studio import Studio

credential_app = typer.Typer(
    help=(
        "Save your own values for the credentials Agents carry, such as your CRM token.\n\n"
        "Credentials are yours, not the project's. An App declares the credentials it "
        "needs; the Agent that runs supplies them, with the scopes it lists under "
        "credentials: in its agent.yaml. Save your value once with "
        "`plural credential set NAME`; every Agent you run that carries NAME uses it, "
        "and your coworkers save their own. For project setup values, use `plural secret`."
    ),
    no_args_is_help=True,
)


def _name(value: str) -> str:
    try:
        return SecretReference(name=value).name
    except ValueError as exc:
        fail(
            f"{value!r} is not a usable credential name. Use upper-case letters, digits, "
            "and underscores, such as SALESFORCE_TOKEN.",
            [str(exc).splitlines()[-1].strip()],
        )


def _studio() -> Studio:
    return signed_in(session()).studio(project=False)


@credential_app.command("list")
@handled
def credential_list(as_json: bool = JSON_OPTION) -> None:
    """List the credentials you saved, never their values."""
    items = _studio().credentials.list()
    emit(
        items,
        as_json=as_json,
        text=lambda: (
            rows(
                ((item["name"], item["hint"], item["updated_at"]) for item in items),
                ("NAME", "ENDS WITH", "UPDATED"),
            )
            if items
            else typer.echo("You have not saved any credentials.")
        ),
    )


@credential_app.command("set")
@handled
def credential_set(
    name: str = typer.Argument(help="The credential's name, as the App declares it."),
    from_env: bool = typer.Option(
        False, "--from-env", help="Read the value from the environment variable of that name."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Save your value for a credential. Prompts without echoing."""
    name = _name(name)
    if from_env:
        value = os.environ.get(name, "")
        if not value:
            fail(f"{name} is not set in your environment.")
    elif sys.stdin.isatty():
        value = typer.prompt(f"Your value of {name}", hide_input=True)
    else:
        value = sys.stdin.read().rstrip("\n")
    if not value:
        fail(f"{name} needs a value.")
    item = _studio().credentials.set(name, value)
    emit(
        item,
        as_json=as_json,
        text=lambda: success(f"Saved {name} to your account (ends {item['hint']})."),
    )


@credential_app.command("delete")
@handled
def credential_delete(
    name: str = typer.Argument(help="The credential to delete."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Delete one of your saved credentials."""
    _studio().credentials.delete(_name(name))
    emit(
        {"name": name, "deleted": True},
        as_json=as_json,
        text=lambda: success(f"Deleted {name} from your account."),
    )


credential_app.command("unset", hidden=True)(
    alias(credential_delete, "plural credential unset", "plural credential delete")
)


def stored_credentials(
    spec: JobSpec, hosted_agent: str | None, *, err: bool
) -> dict[str, dict[str, CredentialValue]]:
    """Your saved values for the credentials the run's Agents carry.

    When you are not signed in, or with a key that may not read your
    credentials (such as one made for CI), the run uses what you exported, and
    its preflight names anything still missing.

    Returns:
        Agent name to credential name to value.
    """
    del hosted_agent
    wanted = {
        binding.name: sorted(binding.agent.credentials)
        for binding in spec.agents
        if binding.agent.credentials
    }
    if not wanted:
        return {}
    names = sorted({name for group in wanted.values() for name in group})
    try:
        grant = _resolve(_studio(), names)
    except (PluralError, ProjectError, OSError, httpx.HTTPError) as exc:
        typer.echo(f"! Credentials: {exc} Using credentials from your environment.", err=True)
        return {}
    if grant:
        typer.echo(f"Using your saved credentials: {', '.join(sorted(grant))}.", err=err)
    return {
        agent: {name: grant[name] for name in group if name in grant}
        for agent, group in wanted.items()
    }


def account_credential_source() -> Callable[[str], str | None]:
    """Look up one of your saved credentials, once per name.

    Planning a run loads its Apps, and a server that needs your token to list
    its tools gets it here. When you are not signed in, or the key may not
    read your credentials, the lookup finds nothing and the App names what is
    missing.
    """
    found: dict[str, str | None] = {}

    def lookup(name: str) -> str | None:
        if name not in found:
            found[name] = None
            try:
                grant = _resolve(_studio(), [name])
            except (PluralError, ProjectError, OSError, httpx.HTTPError):
                return None
            if name in grant:
                found[name] = grant[name].value
        return found[name]

    return lookup


def _resolve(studio: Studio, names: list[str]) -> dict[str, CredentialValue]:
    found = studio.credentials.resolve(names).get("credentials") or {}
    out: dict[str, CredentialValue] = {}
    for name, item in found.items():
        if not isinstance(item, dict) or not item.get("value"):
            continue
        updated = item.get("updated_at")
        out[str(name)] = CredentialValue(
            str(item["value"]),
            source="hosted",
            set_at=datetime.fromisoformat(updated) if isinstance(updated, str) else None,
        )
    return out


__all__ = ["account_credential_source", "credential_app", "stored_credentials"]
