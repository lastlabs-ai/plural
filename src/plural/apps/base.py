"""The App authoring API: a named bundle of actions with optional state hooks."""

from __future__ import annotations

import inspect
import json
import random
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar, Generic, cast, get_args, get_origin

from pydantic import BaseModel, ValidationError, validate_call

from plural.apps.definition import (
    AppAction,
    AppControl,
    AppDefinition,
    AppKind,
    SecretReference,
    derive_control,
)
from plural.environments.action_registry import action_options, function_schema, iter_env_actions
from plural.environments.types import Observation, State, StateT

_LIFECYCLE = frozenset({"reset", "snapshot", "call", "close", "view", "terminated", "truncated"})


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
    seats: tuple[str, ...] = ()
    """The Task's seats, such as ``("button", "big_blind")``, when several Agents
    play. Empty for a Task one Agent works alone. Set before :meth:`reset`."""
    seat: str | None = None
    """The seat taking the current action, while an action runs; ``None`` alone."""
    seed: int | None = None
    """The episode's seed. In a Job it is the same for every Agent on one attempt
    of a Task, so they face the same world. Set before :meth:`reset`."""
    rng: random.Random
    """Random numbers drawn from :attr:`seed`, so an episode can be repeated. Use
    it instead of the ``random`` module. Set before :meth:`reset`."""

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
        instance.rng = random.Random()
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
        """Return this App's state as JSON for Verifiers and verifiers.

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

    def turn(self) -> str | Sequence[str] | None:
        """Which seats may act now, when several Agents share the episode.

        Return one seat, as in a turn-based game; several, for moves made at
        the same time; an empty sequence while nobody may; or ``None``, the
        default, when any seat may act whenever it likes. An action from a seat
        that may not act is refused before it runs. With several Apps, a seat
        may act only when every App that answers allows it.

        Returns:
            The seats that may act, or ``None`` for any.
        """
        return None

    def observe(self, seat: str) -> Any:
        """What ``seat`` sees when its turn comes, such as its own cards.

        Each seat's Agent gets this before it acts, and only its own. Return
        ``None``, the default, when a seat learns everything from its actions.

        Returns:
            The seat's observation, or ``None``.
        """
        return None

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


__all__ = ["App", "observation_payload"]
