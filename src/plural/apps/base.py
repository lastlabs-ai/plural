"""The App authoring API: a named bundle of actions with optional state hooks."""

from __future__ import annotations

import inspect
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar, Generic, cast, get_args, get_origin

from pydantic import BaseModel, ValidationError, validate_call

from plural.apps.definition import (
    AppAction,
    AppControl,
    AppDefinition,
    AppKind,
    RewarderDefinition,
    SecretReference,
    derive_control,
)
from plural.environments.action_registry import action_options, function_schema, iter_env_actions
from plural.environments.fingerprint import callable_implementation_digest
from plural.environments.types import Observation, State, StateT

_REWARDER_ATTR = "__plural_rewarder__"
_LIFECYCLE = frozenset({"reset", "snapshot", "call", "close", "view", "terminated", "truncated"})


def rewarder(
    fn: Callable[..., float] | None = None,
    *,
    name: str | None = None,
    weight: float = 1,
    timeout_seconds: float = 30,
) -> Any:
    """Declare a reward signal for each action of the App that defines it.

    The method accepts ``previous_state, current_state, action, result``.
    ``action`` is ``{"name": ..., **arguments}`` and ``result`` is what the
    action returned, which is what the Agent saw. The two states are the App's
    snapshots before and after the action, or ``None`` when the App does not
    snapshot on each step, so a rewarder on a connected system can still judge
    the system's response.

    Rewards are recorded for credit assignment. They never contribute to a
    Verifier score and never reach the Agent.

    Returns:
        The decorated method.
    """

    def decorate(func: Callable[..., float]) -> Callable[..., float]:
        parameters = tuple(inspect.signature(func).parameters)
        if parameters and parameters[0] in {"self", "cls"}:
            parameters = parameters[1:]
        if parameters != ("previous_state", "current_state", "action", "result"):
            raise TypeError("rewarder must accept previous_state, current_state, action, result")
        setattr(
            func,
            _REWARDER_ATTR,
            {"name": name or func.__name__, "weight": weight, "timeout_seconds": timeout_seconds},
        )
        return func

    return decorate(fn) if fn is not None else decorate


def _snake(name: str) -> str:
    words = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return re.sub(r"[^a-z0-9_]+", "_", words).strip("_") or "app"


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return json.loads(json.dumps(value, sort_keys=True, default=str))


class App(Generic[StateT]):
    """A named bundle of actions the Agent can take, with optional state hooks.

    Subclass ``App`` and mark methods with :func:`~plural.action`. What an
    action returns is what the Agent sees next. Hidden facts belong on
    ``self.state``, a typed :class:`~plural.State` that Verifiers read and the
    Agent never sees::

        class Wordle(App[Game]):
            @action
            def guess(self, word: str) -> str: ...

    A Python App is ``owned``: a fresh Runtime is a fresh App, its default
    :meth:`reset` loads the Task's initial state, and its default
    :meth:`snapshot` returns ``self.state``. Connect an existing system with
    :meth:`App.mcp` or :meth:`App.openapi` instead.

    Keyword arguments passed to the constructor are kept, so a Job can rebuild
    the same App inside a Runtime. Pass settings as JSON-safe keywords.
    """

    name: str = ""
    description: str = ""
    kind: ClassVar[AppKind] = "python"
    state_type: ClassVar[type[State]] = State
    secrets: Sequence[str | SecretReference] = ()
    credentials: Sequence[str | SecretReference] = ()
    control: ClassVar[AppControl | None] = None
    snapshot_on_step: ClassVar[bool] = True

    _init_config: dict[str, Any]
    _source_file: ClassVar[Path | None] = None
    state: StateT
    task_info: Any = None
    """The Task's ``info``, available to :meth:`reset`."""
    workspace: Path
    """The Environment workspace: the folder holding its files in a Runtime."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._source_file = _defining_file(cls)

    def __new__(cls, *args: Any, **kwargs: Any) -> App[Any]:
        """Keep the constructor keywords so the App can be rebuilt in a Runtime.

        Returns:
            The new App.
        """
        if args:
            raise TypeError(
                f"Pass {cls.__name__} settings as keyword arguments, such as "
                f"{cls.__name__}(name='crm'), so a Job can rebuild it in a Runtime"
            )
        instance = super().__new__(cls)
        instance._init_config = dict(kwargs)
        instance.workspace = Path.cwd()
        return instance

    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        secrets: Iterable[str | SecretReference] | None = None,
        credentials: Iterable[str | SecretReference] | None = None,
    ) -> None:
        self.name = name or type(self).name or _snake(type(self).__name__)
        if description is None:
            # The built-in kinds' docstrings document Plural, not the user's App.
            builtin = type(self).__module__.startswith("plural.")
            own_doc = None if builtin else type(self).__dict__.get("__doc__")
            description = type(self).description or (inspect.cleandoc(own_doc) if own_doc else "")
        self.description = description
        declared = type(self).secrets if secrets is None else tuple(secrets)
        self.secrets = tuple(SecretReference.model_validate(item) for item in declared)
        needed = type(self).credentials if credentials is None else tuple(credentials)
        self.credentials = tuple(SecretReference.model_validate(item) for item in needed)
        self.state = cast(StateT, self._state_type()())

    # Factories for Apps that connect existing systems.

    @staticmethod
    def mcp(name: str, **settings: Any) -> App[Any]:
        """Connect an MCP server as an App. See :class:`plural.apps.MCPApp`.

        Returns:
            An MCP App.
        """
        from plural.apps.mcp import MCPApp

        return MCPApp(name=name, **settings)

    @staticmethod
    def openapi(name: str, **settings: Any) -> App[Any]:
        """Connect an HTTP API described by an OpenAPI document as an App.

        Returns:
            An OpenAPI App.
        """
        from plural.apps.openapi import OpenAPIApp

        return OpenAPIApp(name=name, **settings)

    @staticmethod
    def replay(name: str, **settings: Any) -> App[Any]:
        """Answer actions from recorded traces.

        Returns:
            A replay App.
        """
        from plural.apps.replay import ReplayApp

        return ReplayApp(name=name, **settings)

    # Lifecycle hooks. Override what the App needs.

    def reset(self, initial_state: Mapping[str, Any]) -> Any:
        """Start an episode from the Task's initial state for this App.

        The default loads ``initial_state`` into ``self.state``. Override it
        to finish setting up, and return what the Agent should see first, or
        ``None`` for nothing.

        Returns:
            The App's opening observation, or ``None``.
        """
        self.state = cast(StateT, self._state_type().model_validate(dict(initial_state)))
        return None

    def snapshot(self) -> Any:
        """Return this App's state as JSON for Verifiers and rewarders.

        Returns:
            The App's state, or ``None`` when it cannot be read.
        """
        return self.state.model_dump(mode="json")

    def terminated(self) -> bool:
        """Return whether this App ended the episode."""
        return False

    def truncated(self) -> bool:
        """Return whether this App cut the episode short."""
        return False

    def step_info(self) -> dict[str, Any]:
        """Bookkeeping about the last action, recorded on the step.

        It goes in the step's ``info``, which reward ledgers and the run viewer
        read and the Agent never sees.

        Returns:
            A JSON-safe mapping, empty by default.
        """
        return {}

    def view(self) -> dict[str, Any]:
        """Return an optional render document for the run viewer.

        Returns:
            A JSON-safe view, or an empty mapping.
        """
        return {}

    def close(self) -> None:
        """Release connections when the episode ends."""

    # Introspection used by the Environment and the App host.

    @classmethod
    def _state_type(cls) -> type[State]:
        for owner in cls.__mro__:
            for base in getattr(owner, "__orig_bases__", ()):
                if get_origin(base) is not None and issubclass(get_origin(base), App):
                    args = get_args(base)
                    if args and inspect.isclass(args[0]) and issubclass(args[0], State):
                        return args[0]
        return cls.state_type

    def _state_schema(self) -> dict[str, Any]:
        return self._state_type().model_json_schema()

    def actions(self) -> tuple[AppAction, ...]:
        """Return every action this App offers the Agent."""
        declared: list[AppAction] = []
        for action_name, func in iter_env_actions(type(self)):
            if action_name in _LIFECYCLE:
                raise TypeError(
                    f"{type(self).__name__}.{action_name} is an App hook; "
                    "do not mark it with @action"
                )
            options = action_options(func)
            declared.append(
                AppAction(
                    name=action_name,
                    description=(inspect.getdoc(func) or action_name).strip(),
                    parameters=function_schema(func),
                    mutates_state=not options.get("read_only", False),
                    timeout_seconds=float(options.get("timeout_seconds", 30)),
                )
            )
        return tuple(declared)

    def call(self, action: str, arguments: Mapping[str, Any]) -> Any:
        """Run one action and return what the Agent sees.

        Invalid arguments raise ``ValueError``, which the Agent sees as an
        error while the episode continues.

        Returns:
            The action's observation.
        """
        method = None
        for action_name, func in iter_env_actions(type(self)):
            if action_name == action:
                method = getattr(self, func.__name__)
                break
        if method is None:
            available = ", ".join(item.name for item in self.actions()) or "none"
            raise ValueError(f"unknown action {action!r}; available actions: {available}")
        try:
            return validate_call(method)(**dict(arguments))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}"
                for error in exc.errors()
            )
            raise ValueError(f"invalid arguments for {action!r}: {problems}") from None

    def has_reset(self) -> bool:
        """Whether this App sets up its own starting state.

        Returns:
            True when ``reset`` prepares each episode.
        """
        return True

    def has_snapshot(self) -> bool:
        """Whether this App can report its state.

        Returns:
            True when ``snapshot`` returns the App's state.
        """
        return True

    def is_local(self) -> bool:
        """Whether this App's state lives inside the Runtime.

        Returns:
            True when the App runs in the Runtime's workspace.
        """
        return True

    def resolved_control(self) -> AppControl:
        """How much of this App's state Plural controls.

        Returns:
            The declared control level, or the one derived from the App's hooks.
        """
        if type(self).control is not None:
            return type(self).control  # type: ignore[return-value]
        return derive_control(self.kind, local=self.is_local(), has_reset=self.has_reset())

    def _rewarder_methods(self) -> tuple[tuple[dict[str, Any], Callable[..., float]], ...]:
        bound: list[tuple[dict[str, Any], Callable[..., float]]] = []
        seen: set[str] = set()
        for owner in type(self).__mro__:
            for attribute, value in owner.__dict__.items():
                config = getattr(value, _REWARDER_ATTR, None)
                if not callable(value) or not isinstance(config, dict):
                    continue
                if config["name"] in seen:
                    continue
                seen.add(str(config["name"]))
                bound.append((config, getattr(self, attribute)))
        return tuple(bound)

    def _rewarders(self) -> tuple[RewarderDefinition, ...]:
        return tuple(
            RewarderDefinition(
                name=str(config["name"]),
                description=(inspect.getdoc(method) or "").strip(),
                implementation_digest=callable_implementation_digest(method),
                weight=float(config["weight"]),
                timeout_seconds=float(config["timeout_seconds"]),
            )
            for config, method in self._rewarder_methods()
        )

    def _config(self) -> dict[str, Any]:
        config = {key: value for key, value in self._init_config.items() if key != "name"}
        try:
            return cast(dict[str, Any], _json_safe(config))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"App {self.name!r} settings must be JSON-safe so a Job can rebuild it: {exc}"
            ) from exc

    def _class_file(self) -> Path | None:
        return type(self).__dict__.get("_source_file") or _defining_file(type(self))

    def _python_reference(self, root: Path | None) -> str | None:
        """Return ``file.py:Class`` relative to the Environment source, if user code."""
        if type(self).__module__.startswith("plural."):
            return None
        class_file = self._class_file()
        if class_file is None:
            raise ValueError(
                f"Cannot use App {self.name!r}: Plural could not find the file that "
                "defines it. Define the App class in a .py file."
            )
        if root is None:
            raise ValueError(
                f"Cannot use App {self.name!r}: its Environment has no source folder. "
                "Define the Environment in a .py file next to the App."
            )
        try:
            relative = class_file.relative_to(root).as_posix()
        except ValueError:
            raise ValueError(
                f"App {self.name!r} is defined in {class_file}, outside the Environment "
                f"source folder {root}. Move it into that folder so a Job can upload it."
            ) from None
        return f"{relative}:{type(self).__qualname__}"

    def definition(self, root: Path | None = None) -> AppDefinition:
        """Compile this App into its serialized declaration.

        ``root`` is the Environment's source folder; a user-defined App class
        must live inside it.

        Returns:
            The App's declaration.
        """
        return AppDefinition(
            name=self.name,
            kind=self.kind,
            description=self.description,
            python=self._python_reference(root),
            config=self._config(),
            actions=self.actions(),
            secrets=tuple(SecretReference.model_validate(item) for item in self.secrets),
            credentials=tuple(SecretReference.model_validate(item) for item in self.credentials),
            rewarders=self._rewarders(),
            state_schema=self._state_schema(),
            has_reset=self.has_reset(),
            has_snapshot=self.has_snapshot(),
            control=self.resolved_control(),
        )


def _defining_file(cls: type) -> Path | None:
    """The file that defines ``cls``, read while its module is still registered.

    Returns:
        The resolved path, or ``None`` for classes with no source file.
    """
    module = sys.modules.get(cls.__module__)
    filename = getattr(module, "__file__", None) if module is not None else None
    if filename:
        return Path(filename).resolve()
    try:
        source = inspect.getsourcefile(cls)
    except TypeError:
        return None
    return Path(source).resolve() if source else None


def observation_payload(value: Any) -> tuple[Any, str]:
    """Split an action result into its JSON form and the text the Agent reads.

    Returns:
        The JSON-safe observation and its rendered text.
    """
    if value is None:
        return None, ""
    if isinstance(value, Observation):
        return value.model_dump(mode="json"), value.render()
    if isinstance(value, str):
        return {"text": value}, value
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
        return payload, json.dumps(payload, sort_keys=True)
    payload = _json_safe(value)
    if isinstance(payload, dict) and isinstance(payload.get("text"), str) and len(payload) == 1:
        return payload, payload["text"]
    return payload, json.dumps(payload, sort_keys=True)


__all__ = ["App", "observation_payload", "rewarder"]
