"""Agent credentials: what an Environment's Apps need, supplied by the running Agent.

An App lists the credentials it needs, such as ``SALESFORCE_TOKEN``. An Agent
lists the credentials it carries and the scopes each one grants. When a Trial
starts, every credential the Apps need must be one the Agent declares and has a
value for. The value goes to the App host only, never to the Harness or the
model, and the Trial records which Agent supplied which credential, from where,
and a fingerprint of the value, so a run can be audited without storing it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from plural.agents.models import AgentDefinition
from plural.common import FrozenModel
from plural.environments.definition import EnvironmentDefinition

CredentialSource = Literal["hosted", "provided", "environment"]


@dataclass(frozen=True)
class CredentialValue:
    """One credential value and where it came from. Never serialized."""

    value: str
    source: CredentialSource = "provided"
    set_at: datetime | None = None

    def __repr__(self) -> str:
        return f"CredentialValue(source={self.source!r}, value=***)"


class CredentialUse(FrozenModel):
    """The audit record of one credential one Trial used. Never the value.

    ``fingerprint`` is a short hash of the value, enough to tell two tokens
    apart and to match a token you hold, not to recover it.
    """

    app: str
    name: str
    agent: str
    agent_revision: str
    scopes: tuple[str, ...] = ()
    source: CredentialSource
    fingerprint: str
    set_at: datetime | None = None


class CredentialError(ValueError):
    """A credential the Apps need is not declared by the Agent or has no value."""


def fingerprint(value: str) -> str:
    """A short, non-reversible identifier of a credential value.

    Returns:
        ``sha256:`` and the first 12 hex characters of the value's digest.
    """
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()[:12]


def needed(environment: EnvironmentDefinition) -> dict[str, list[str]]:
    """Each credential the Environment's Apps need, and the Apps that need it.

    Returns:
        Credential name to App names, for required credentials.
    """
    out: dict[str, list[str]] = {}
    for app in environment.apps:
        for item in app.credentials:
            if item.required:
                out.setdefault(item.name, []).append(app.name)
    return out


def resolve(
    environment: EnvironmentDefinition,
    agent: AgentDefinition,
    supplied: Mapping[str, CredentialValue | str],
    environ: Mapping[str, str],
) -> tuple[dict[str, str], tuple[CredentialUse, ...]]:
    """The credential values for one Trial, and what to record about them.

    A value comes from ``supplied`` (the running user's saved credentials, or
    ones passed to the Job) first, then from an exported variable of the same name.

    Returns:
        Name to value for the App host, and one audit record per App and name.

    Raises:
        CredentialError: The Agent does not declare a credential the Apps
            need, or has no value for one.
    """
    wanted = needed(environment)
    optional = {
        item.name
        for app in environment.apps
        for item in app.credentials
        if not item.required and item.name in agent.credentials
    }
    undeclared = sorted(name for name in wanted if name not in agent.credentials)
    if undeclared:
        lines = [f"  {name}, for App {', '.join(wanted[name])}" for name in undeclared]
        raise CredentialError(
            f"Environment {environment.name!r} needs credentials that Agent "
            f"{agent.name!r} does not carry:\n"
            + "\n".join(lines)
            + "\nA credential belongs to the Agent that acts with it. List it under "
            "credentials: in that Agent's agent.yaml, with the scopes it grants, and run "
            "with --agent."
        )
    unscoped = [
        f"  {item.name} for App {app.name!r}: {', '.join(lacking)}"
        for app in environment.apps
        for item in app.credentials
        if item.name in agent.credentials
        and (lacking := sorted(set(item.scopes) - set(agent.credentials[item.name].scopes)))
    ]
    if unscoped:
        raise CredentialError(
            f"Agent {agent.name!r} does not grant the scopes Environment "
            f"{environment.name!r} needs:\n"
            + "\n".join(unscoped)
            + "\nAdd them to the credential's scopes in that Agent's agent.yaml, if the "
            "credential really grants them."
        )
    values: dict[str, CredentialValue] = {}
    missing: list[str] = []
    for name in sorted({*wanted, *optional}):
        found = supplied.get(name)
        if isinstance(found, str):
            found = CredentialValue(found) if found else None
        if found is None and environ.get(name):
            found = CredentialValue(environ[name], source="environment")
        if found is not None:
            values[name] = found
        elif name in wanted:
            missing.append(name)
    if missing:
        raise CredentialError(
            f"Agent {agent.name!r} declares {', '.join(missing)} but has no value for "
            + ("it" if len(missing) == 1 else "them")
            + ". Save your value of each with `plural credential set NAME`, or "
            "export it for a local run."
        )
    uses = tuple(
        CredentialUse(
            app=app.name,
            name=item.name,
            agent=agent.name,
            agent_revision=agent.revision,
            scopes=agent.credentials[item.name].scopes,
            source=values[item.name].source,
            fingerprint=fingerprint(values[item.name].value),
            set_at=values[item.name].set_at,
        )
        for app in environment.apps
        for item in app.credentials
        if item.name in values
    )
    return {name: item.value for name, item in values.items()}, uses


__all__ = [
    "CredentialError",
    "CredentialSource",
    "CredentialUse",
    "CredentialValue",
    "fingerprint",
    "needed",
    "resolve",
]
