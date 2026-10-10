"""``plural agent credential``: the values behind the credentials an Agent carries.

An App names the credentials it needs, such as ``SALESFORCE_TOKEN``. An Agent
lists the ones it carries, with their scopes, in its ``agent.yaml``. The values
live here, encrypted with the hosted Agent, so each Agent acts with its own
token and every Trial records which one it used. `plural run --agent` passes
each value only to the App host, never to the Harness or the model.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import httpx
import typer

from plural.apps.definition import SecretReference
from plural.cli.common import JSON_OPTION, emit, fail, handled, muted, rows, success
from plural.cli.runtime_commands import _project_studio
from plural.credentials import CredentialValue
from plural.errors import NotFoundError, PluralError
from plural.jobs import JobSpec
from plural.project import ProjectError
from plural.studio import Studio, slugify

credential_app = typer.Typer(
    help=(
        "Store the credentials an Agent carries, such as the token of the user it acts as.\n\n"
        "List each one under credentials: in the Agent's agent.yaml, with its scopes. "
        "Set its value with `plural agent credential set AGENT NAME`; `plural run --agent "
        "AGENT` then supplies it to the Apps that need it."
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


@credential_app.command("list")
@handled
def credential_list(
    agent: str = typer.Argument(help="The Agent, by its folder name under agents/."),
    as_json: bool = JSON_OPTION,
) -> None:
    """List an Agent's stored credentials, never their values."""
    studio, project = _project_studio()
    try:
        items = studio.agents.credentials(slugify(agent))
    except NotFoundError:
        items = []
    emit(
        items,
        as_json=as_json,
        text=lambda: (
            rows(
                ((item["name"], item["hint"], item["updated_at"]) for item in items),
                ("NAME", "ENDS WITH", "UPDATED"),
            )
            if items
            else typer.echo(f"No credentials stored for Agent {agent} in project {project}.")
        ),
    )


@credential_app.command("set")
@handled
def credential_set(
    agent: str = typer.Argument(help="The Agent, by its folder name under agents/."),
    name: str = typer.Argument(help="The credential's name, as the App declares it."),
    from_env: bool = typer.Option(
        False, "--from-env", help="Read the value from the environment variable of that name."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Store an Agent's credential. Prompts without echoing."""
    name = _name(name)
    if from_env:
        value = os.environ.get(name, "")
        if not value:
            fail(f"{name} is not set in your environment.")
    elif sys.stdin.isatty():
        value = typer.prompt(f"Value of {name} for Agent {agent}", hide_input=True)
    else:
        value = sys.stdin.read().rstrip("\n")
    if not value:
        fail(f"{name} needs a value.")
    studio, project = _project_studio()
    slug = slugify(agent)
    try:
        item = studio.agents.set_credential(slug, name, value)
    except NotFoundError:
        studio.agents.create(name=agent, slug=slug)
        item = studio.agents.set_credential(slug, name, value)
    emit(
        item,
        as_json=as_json,
        text=lambda: success(
            f"Set {name} for Agent {agent} in project {project} " + muted(f"(ends {item['hint']})")
        ),
    )


@credential_app.command("unset")
@handled
def credential_unset(
    agent: str = typer.Argument(help="The Agent, by its folder name under agents/."),
    name: str = typer.Argument(help="The credential to remove."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Remove an Agent's stored credential."""
    studio, project = _project_studio()
    studio.agents.delete_credential(slugify(agent), _name(name))
    emit(
        {"agent": agent, "name": name, "deleted": True},
        as_json=as_json,
        text=lambda: success(f"Removed {name} from Agent {agent} in project {project}."),
    )


def stored_credentials(
    spec: JobSpec, hosted_agent: str | None, *, err: bool
) -> dict[str, dict[str, CredentialValue]]:
    """The run's Agent credentials stored in the hosted project.

    Only a saved Agent (``--agent``) has stored credentials; ``hosted_agent`` is
    its folder name. Without a hosted project, or when you may not read its
    credentials, the run uses what you exported, and its preflight names
    anything still missing.

    Returns:
        Agent name to credential name to value.
    """
    if hosted_agent is None:
        return {}
    out: dict[str, dict[str, CredentialValue]] = {}
    for binding in spec.agents:
        names = sorted(binding.agent.credentials)
        if not names:
            continue
        try:
            studio, _ = _project_studio()
            grant = _resolve(studio, slugify(hosted_agent), names)
        except NotFoundError:
            continue
        except (PluralError, ProjectError, OSError, httpx.HTTPError) as exc:
            typer.echo(
                f"! Agent credentials: {exc} Using credentials from your environment.", err=True
            )
            continue
        if grant:
            out[binding.name] = grant
            typer.echo(
                f"Using Agent {hosted_agent}'s stored credentials: {', '.join(sorted(grant))}.",
                err=err,
            )
    return out


def _resolve(studio: Studio, agent: str, names: list[str]) -> dict[str, CredentialValue]:
    found = studio.agents.resolve_credentials(agent, names).get("credentials") or {}
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


__all__ = ["credential_app", "stored_credentials"]
