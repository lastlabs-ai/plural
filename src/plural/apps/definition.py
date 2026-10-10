"""Serialized App declarations: the actions, hooks, and secrets of one App."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from plural.common import FrozenModel

AppKind = Literal["python", "mcp", "openapi", "data", "replay"]
AppControl = Literal["owned", "sandboxed", "live", "replayed"]

APP_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
ACTION_SEPARATOR = "__"
RESERVED_ACTIONS = frozenset({"reset", "step", "finish"})


class SecretReference(FrozenModel):
    """A named value an App needs, which it never stores itself.

    In an App's ``secrets`` it is a setup secret, such as a sandbox's admin
    token, supplied by the project for reset and snapshot hooks and Verifiers.
    In its ``credentials`` it is supplied by the Agent that runs, such as the
    Salesforce token of the user that Agent acts as. Either way the value
    reaches only the App host, never the Harness or the model.
    """

    name: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    required: bool = True
    description: str = ""

    @model_validator(mode="before")
    @classmethod
    def _from_name(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    @field_validator("name")
    @classmethod
    def _application_name(cls, value: str) -> str:
        if value in {
            "PATH",
            "HOME",
            "PYTHONPATH",
            "PYTHONHOME",
            "LD_PRELOAD",
            "PLURAL_RESOURCES_DIR",
        } or value.startswith(("DYLD_", "PLURAL_")):
            raise ValueError("Secrets cannot replace execution or resource controls")
        return value


class AppAction(FrozenModel):
    """One move an App offers the Agent.

    ``name`` is the App's own name for the action (a Python method name or an
    MCP tool name). The Environment exposes it to the Agent unprefixed when it
    has one App, and as ``<app>__<name>`` when it has several.
    """

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "additionalProperties": True}
    )
    mutates_state: bool = True
    timeout_seconds: float = Field(default=30, gt=0)
    binding: dict[str, Any] = Field(default_factory=dict)
    """How the App carries out this action, such as an HTTP method and path.

    Never shown to the Agent.
    """

    @field_validator("name")
    @classmethod
    def _tool_name(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError(
                f"action name {value!r} may only contain letters, digits, '_' and '-', "
                "because model providers reject other characters in tool names"
            )
        return value


class RewarderDefinition(FrozenModel):
    """A named reward signal an App computes for each of its own actions."""

    name: str = Field(min_length=1)
    description: str = ""
    implementation_digest: str = ""
    weight: float = Field(default=1, gt=0)
    timeout_seconds: float = Field(default=30, gt=0)


class AppDefinition(FrozenModel):
    """One App inside an Environment.

    ``python`` names the App class as ``file.py:Class`` inside the Environment's
    source package. ``config`` holds the keyword arguments the App was built
    with, so the App host can rebuild the same App inside a Runtime.
    """

    name: str
    kind: AppKind = "python"
    description: str = ""
    python: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    actions: tuple[AppAction, ...] = ()
    secrets: tuple[SecretReference, ...] = ()
    """Setup secrets, from the project: for reset and snapshot hooks and Verifiers."""
    credentials: tuple[SecretReference, ...] = ()
    """Credentials the running Agent supplies, so its actions run as that Agent."""
    rewarders: tuple[RewarderDefinition, ...] = ()
    state_schema: dict[str, Any] = Field(default_factory=dict)
    has_reset: bool = False
    has_snapshot: bool = False
    control: AppControl = "owned"

    @field_validator("name")
    @classmethod
    def _app_name(cls, value: str) -> str:
        if APP_NAME.fullmatch(value) is None or ACTION_SEPARATOR in value:
            raise ValueError(
                f"App name {value!r} must be lowercase letters, digits, and single "
                "underscores, start with a letter, and be at most 40 characters"
            )
        return value

    @model_validator(mode="after")
    def _valid_app(self) -> AppDefinition:
        names = [item.name for item in self.actions]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"App {self.name!r} declares duplicate actions: {duplicates}")
        reserved = sorted(RESERVED_ACTIONS & set(names))
        if reserved:
            raise ValueError(
                f"App {self.name!r} cannot name an action {reserved[0]!r}; "
                "reset, step, and finish belong to the episode, not the App"
            )
        secret_names = [item.name for item in self.secrets]
        if len(secret_names) != len(set(secret_names)):
            raise ValueError(f"App {self.name!r} declares a secret more than once")
        credential_names = [item.name for item in self.credentials]
        if len(credential_names) != len(set(credential_names)):
            raise ValueError(f"App {self.name!r} declares a credential more than once")
        both = sorted(set(secret_names) & set(credential_names))
        if both:
            raise ValueError(
                f"App {self.name!r} lists {both[0]} as both a secret and a credential. "
                "A credential comes from the Agent; a secret from the project. Pick one."
            )
        rewarder_names = [item.name for item in self.rewarders]
        if len(rewarder_names) != len(set(rewarder_names)):
            raise ValueError(f"App {self.name!r} declares a rewarder name more than once")
        if self.kind == "python" and not self.python:
            raise ValueError(f"Python App {self.name!r} needs a file.py:Class reference")
        return self

    @property
    def reproducible(self) -> bool:
        """Whether every Trial starts this App from the same state."""
        return self.control != "live"

    @property
    def read_only(self) -> bool:
        """Whether no action this App offers changes state."""
        return not any(item.mutates_state for item in self.actions)


def derive_control(kind: AppKind, *, local: bool, has_reset: bool) -> AppControl:
    """Return how much of an App's state Plural controls.

    ``local`` means the App's state lives inside the Runtime, so a fresh
    Runtime is a fresh App: a Python App, a data App, or an MCP server started
    as a command. A remote App is ``sandboxed`` when it can be reset and
    ``live`` otherwise.

    Returns:
        The App's control level.
    """
    if kind == "replay":
        return "replayed"
    if local:
        return "owned"
    return "sandboxed" if has_reset else "live"


def exposed_name(app: str, action: str, *, prefixed: bool) -> str:
    """Return the tool name the Agent sees for one App action."""
    return f"{app}{ACTION_SEPARATOR}{action}" if prefixed else action


class ExposedAction(FrozenModel):
    """One action as the Agent sees it: an App action under its exposed name."""

    name: str
    app: str
    action: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    mutates_state: bool = True
    timeout_seconds: float = 30


__all__ = [
    "ACTION_SEPARATOR",
    "AppAction",
    "AppControl",
    "AppDefinition",
    "AppKind",
    "ExposedAction",
    "RESERVED_ACTIONS",
    "RewarderDefinition",
    "SecretReference",
    "derive_control",
    "exposed_name",
]
