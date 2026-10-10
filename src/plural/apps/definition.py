"""Serialized App declarations: the actions, hooks, and secrets of one App."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from plural.common import FrozenModel

AppKind = Literal["python", "mcp", "openapi", "replay"]
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
    MCP tool name), which is how the App is called. The Agent sees it under
    its exposed name: the same name, with any character a model provider
    rejects replaced, and prefixed ``<app>__`` only when another App offers
    the same name.
    """

    name: str = Field(min_length=1, max_length=128)
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
        if not value.strip() or any(not character.isprintable() for character in value):
            raise ValueError(f"action name {value!r} must be printable text")
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
    Runtime is a fresh App: a Python App, or an MCP server named with ``server`` or started
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


TOOL_NAME_LIMIT = 64
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _safe(name: str) -> str:
    return _UNSAFE.sub("_", name).strip("_") or "action"


def _fit(name: str, key: str) -> str:
    if len(name) <= TOOL_NAME_LIMIT:
        return name
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"{name[: TOOL_NAME_LIMIT - 9]}_{digest}"


def exposed_names(apps: Sequence[tuple[str, Sequence[str]]]) -> dict[tuple[str, str], str]:
    """The tool name the Agent sees for each App action.

    Each action keeps its own name, with characters model providers reject
    replaced by ``_``. Only a name another App also offers, or one of the
    episode's own (``reset``, ``step``, ``finish``), is prefixed with the App's
    name, so adding an App never renames the tools of the others. Names stay
    within 64 characters and are unique.

    Returns:
        ``(app, action)`` to the exposed name.
    """
    base = {(app, action): _safe(action) for app, actions in apps for action in actions}
    owners: dict[str, set[str]] = {}
    for (app, _), name in base.items():
        owners.setdefault(name, set()).add(app)
    exposed: dict[tuple[str, str], str] = {}
    for (app, action), name in base.items():
        if len(owners[name]) > 1 or name in RESERVED_ACTIONS:
            name = f"{app}{ACTION_SEPARATOR}{name}"
        exposed[(app, action)] = _fit(name, f"{app}/{action}")
    counts: dict[str, int] = {}
    for name in exposed.values():
        counts[name] = counts.get(name, 0) + 1
    for key, name in exposed.items():
        if counts[name] > 1:
            digest = hashlib.sha256(f"{key[0]}/{key[1]}".encode()).hexdigest()[:8]
            exposed[key] = f"{name[: TOOL_NAME_LIMIT - 9]}_{digest}"
    return exposed


def tool_parameters(schema: Any) -> dict[str, Any]:
    """An action's parameters as a JSON Schema every model provider accepts.

    Returns:
        An object schema with ``properties``, without ``$schema`` or ``$id``.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    normalized = {key: value for key, value in schema.items() if key not in {"$schema", "$id"}}
    kind = normalized.get("type")
    if kind is None or (isinstance(kind, list) and "object" in kind):
        normalized["type"] = "object"
    if normalized.get("type") == "object" and not isinstance(normalized.get("properties"), dict):
        normalized["properties"] = {}
    return normalized


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
    "TOOL_NAME_LIMIT",
    "derive_control",
    "exposed_names",
    "tool_parameters",
]
