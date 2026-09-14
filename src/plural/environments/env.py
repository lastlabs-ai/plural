"""Canonical Python authoring compiler for schema-v2 Environments."""

from __future__ import annotations

import inspect
import json
import shlex
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Generic, cast, get_args, get_origin

from pydantic import BaseModel

from plural.common import PackageSource
from plural.environments.action_registry import action, function_schema, iter_env_actions
from plural.environments.definition import (
    EnvironmentDefinition,
    EnvironmentResource,
    EnvironmentRuntime,
    ExecutionLimits,
    Guardrail,
    HarnessPolicy,
    NativeAction,
    RewarderDefinition,
    SecretReference,
)
from plural.environments.fingerprint import callable_implementation_digest
from plural.environments.types import Observation, ObsT, State, StateT

_REWARDER_ATTR = "__plural_rewarder__"
_LIFECYCLE = frozenset({"reset", "step"})


def rewarder(
    fn: Callable[..., float] | None = None,
    *,
    name: str | None = None,
    weight: float = 1,
    timeout_seconds: float = 30,
) -> Any:
    """Declare a train-only state-transition rewarder.

    The callable must accept ``previous_state, current_state, action, result``.
    It is compiled into manifest metadata; the Job engine invokes rewarders
    only in train mode.

    Returns:
        A decorated rewarder callable.
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
            {
                "name": name or func.__name__,
                "weight": weight,
                "timeout_seconds": timeout_seconds,
            },
        )
        return func

    return decorate(fn) if fn is not None else decorate


def _model_schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


def _json_snapshot(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return json.loads(encoded)


class Environment(Generic[ObsT, StateT]):
    """A Task-bound world with a Gymnasium ``reset`` / ``step`` episode API.

    Compile typed declarations into one immutable execution view. A Task pins
    one Environment version. The Job or Harness constructs this instance for
    that Task, calls :meth:`reset`, then applies Agent moves with :meth:`step`.
    ``reset`` and ``step`` are not Agent-facing ``@action`` tools.
    """

    name = "environment"
    version = "0.1.0"
    # Compatibility for environments authored before the public version rename.
    revision = "0.1.0"
    description = ""
    overview = ""
    readme = ""
    metadata: dict[str, Any] = {}
    reset_command: tuple[str, ...] = ()
    observation_type: type[Observation] = Observation
    state_type: type[State] = State

    def __init__(
        self,
        *,
        name: str | None = None,
        version: str | None = None,
        revision: str | None = None,
        description: str | None = None,
        overview: str | None = None,
        readme: str | None = None,
        resources: tuple[EnvironmentResource, ...] = (),
        runtime: EnvironmentRuntime | None = None,
        secrets: tuple[SecretReference, ...] = (),
        guardrails: tuple[Guardrail, ...] = (),
        harness_policy: HarnessPolicy | None = None,
        limits: ExecutionLimits | None = None,
        metadata: dict[str, Any] | None = None,
        state: StateT | None = None,
        observation: ObsT | None = None,
        info: Any = None,
        reset_command: tuple[str, ...] | None = None,
    ) -> None:
        if version is not None and revision is not None and version != revision:
            raise ValueError("version and revision cannot disagree")
        self.name = name or type(self).name
        declared_version = (
            type(self).__dict__.get("version")
            or type(self).__dict__.get("revision")
            or type(self).version
        )
        self.version = version or revision or declared_version
        self.revision = self.version
        self.description = type(self).description if description is None else description
        self.overview = type(self).overview if overview is None else overview
        self.readme = type(self).readme if readme is None else readme
        self.resources = resources
        if runtime is None:
            raise ValueError(
                f"Cannot create Environment {self.name!r}.\n"
                "runtime is required and says where the Agent and Environment execute.\n"
                "Use a Harbor-style preset:\n"
                "  Environment(..., runtime=Runtime.docker())\n"
                "  Environment(..., runtime=Runtime.local())\n"
                "  Environment(..., runtime=Runtime.daytona())"
            )
        if isinstance(runtime, Mapping):
            runtime = EnvironmentRuntime.model_validate(runtime)
        self.runtime = runtime
        self.secrets = secrets
        self.guardrails = guardrails
        self.harness_policy = harness_policy or HarnessPolicy()
        self.limits = limits or ExecutionLimits()
        self.metadata = deepcopy(type(self).metadata) if metadata is None else deepcopy(metadata)
        self.source: PackageSource | None = None
        self._adapter_command: tuple[str, ...] | None = None
        self._package_root: Path | None = None
        self._compiled_definition: EnvironmentDefinition | None = None
        self._python_source: Path | None = None
        self._python_object: str | None = None
        self.info = info
        self.reset_command = type(self).reset_command if reset_command is None else reset_command
        observation_type, state_type = self._declared_types()
        self.state = state if state is not None else cast(StateT, state_type())
        self.observation = (
            observation if observation is not None else cast(ObsT, observation_type())
        )

    @classmethod
    def _declared_types(cls) -> tuple[type[Observation], type[State]]:
        observation_type = cls.observation_type
        state_type = cls.state_type
        for owner in cls.__mro__:
            for base in getattr(owner, "__orig_bases__", ()):
                if get_origin(base) is Environment:
                    args = get_args(base)
                    if len(args) == 2:
                        if inspect.isclass(args[0]) and issubclass(args[0], Observation):
                            observation_type = args[0]
                        if inspect.isclass(args[1]) and issubclass(args[1], State):
                            state_type = args[1]
        return observation_type, state_type

    def observation_snapshot(self) -> Any:
        """Return a detached, JSON-safe agent-visible observation."""
        return _json_snapshot(self.observation)

    def state_snapshot(self) -> Any:
        """Return a detached, JSON-safe internal state snapshot."""
        return _json_snapshot(self.state)

    @property
    def content_hash(self) -> str:
        """Stable hash of the compiled Environment configuration and source."""
        return self.definition().content_hash

    @property
    def identity(self) -> Any:
        """Exact Environment identity used by planning."""
        return self.definition().identity

    def view(self) -> dict[str, Any]:
        """Return an optional Environment-owned render document.

        Returns:
            A JSON-safe view. Empty means Intel falls back to the observation.
        """
        return {}

    def persist(self, directory: str | Path = ".") -> None:
        """Write ``state.json``, ``observation.json``, and ``view.json``."""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        root.joinpath("state.json").write_text(
            json.dumps(self.state_snapshot()) + "\n", encoding="utf-8"
        )
        root.joinpath("observation.json").write_text(
            json.dumps(self.observation_snapshot()) + "\n", encoding="utf-8"
        )
        rendered = self.view()
        if rendered:
            root.joinpath("view.json").write_text(json.dumps(rendered) + "\n", encoding="utf-8")

    def package(
        self,
        command: str | tuple[str, ...],
        *,
        source: str | Path | None = None,
    ) -> Environment[ObsT, StateT]:
        """Bind Python actions to a local source tree and command adapter.

        The adapter receives the action name as its final argument and JSON
        parameters on standard input. It should persist state between calls in
        its working directory. ``reset`` uses the same adapter.

        Returns:
            This Environment, ready to place directly on a Task.
        """
        from plural.harness.retrieval import tree_digest

        adapter = tuple(shlex.split(command)) if isinstance(command, str) else tuple(command)
        if not adapter or any(not item for item in adapter):
            raise ValueError("environment package command must contain non-empty arguments")
        if source is None:
            module_file = inspect.getsourcefile(type(self))
            if module_file is None:
                raise ValueError("could not infer Environment source; pass source= explicitly")
            root = Path(module_file).resolve().parent
        else:
            requested = Path(source).expanduser().resolve()
            root = requested.parent if requested.is_file() else requested
        self.source = PackageSource(
            kind="local",
            uri=str(root),
            digest=tree_digest(root),
            trusted=True,
        )
        self._adapter_command = adapter
        self._package_root = root
        if self._python_source is None:
            class_source = inspect.getsourcefile(type(self))
            if class_source is not None:
                self._python_source = Path(class_source).resolve()
        self._python_object = self._python_object or type(self).__qualname__
        return self

    @classmethod
    def from_config(cls, **fields: Any) -> Environment[Any, Any]:
        """Restore a serialized public Environment configuration.

        This is primarily used by :mod:`plural.project`; users normally author
        Python subclasses and call :meth:`package`.

        Returns:
            An Environment backed by the validated serialized configuration.
        """
        definition = EnvironmentDefinition.model_validate(fields)
        environment = cls(
            name=definition.name,
            version=definition.version,
            description=definition.description,
            overview=definition.overview,
            readme=definition.readme,
            resources=definition.resources,
            runtime=definition.runtime,
            secrets=definition.secrets,
            guardrails=definition.guardrails,
            harness_policy=definition.harness_policy,
            limits=definition.limits,
            metadata=definition.metadata,
            reset_command=definition.reset_command,
        )
        environment.source = definition.source
        environment._compiled_definition = definition
        return environment

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[ObsT, dict[str, Any]]:
        """Start a new episode.

        Follows the Gymnasium reset contract: ``(observation, info)``. The Job
        or Harness calls this after attaching the Environment to a Task. It is
        not an Agent action and does not take a Task name. Subclasses override
        this to load the bound Task's initial state. ``options`` is harness
        configuration, not an Agent argument.

        Returns:
            The initial observation and reset information.
        """
        del options
        if seed is not None:
            self.state.seed = seed
        return self.observation, {}

    def step(
        self, action: Any = None, /, **kwargs: Any
    ) -> tuple[ObsT, float, bool, bool, dict[str, Any]]:
        """Apply one Agent action.

        Follows the Gymnasium step contract: ``(observation, reward,
        terminated, truncated, info)``. ``action`` is a mapping with
        ``name`` plus parameters, an action name plus kwargs, or kwargs
        alone when the Environment has a single ``@action``.

        Returns:
            Observation, reward, terminal flags, and step information.
        """
        name, params = self._parse_action(action, kwargs)
        previous = self.state_snapshot()
        result = self._invoke_action(name, params)
        payload = {"name": name, **params}
        reward = float(self.reward(previous, self.state_snapshot(), payload, result))
        return self.observation, reward, self.terminated(), self.truncated(), {}

    def terminated(self) -> bool:
        """Return whether the episode reached a Task success or failure state."""
        observation = self.observation
        return any(getattr(observation, attr, False) for attr in ("done", "solved", "terminated"))

    def truncated(self) -> bool:
        """Return whether the episode ended on a budget or external stop."""
        return False

    def reward(
        self,
        previous_state: Any,
        current_state: Any,
        action: Mapping[str, Any],
        result: Any,
    ) -> float:
        """Return the step reward. Default is ``0``."""
        del previous_state, current_state, action, result
        return 0.0

    def _parse_action(self, action: Any, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        declared = [name for name, _ in iter_env_actions(type(self))]
        if action is None:
            payload = dict(kwargs)
        elif isinstance(action, str):
            return action, dict(kwargs)
        elif isinstance(action, Mapping):
            payload = {**action, **kwargs}
        else:
            raise TypeError("step action must be a name, mapping, or keyword arguments")
        name = payload.pop("name", None) or payload.pop("action", None)
        if name:
            return str(name), payload
        if len(declared) == 1:
            return declared[0], payload
        raise ValueError("step requires an action name")

    def _invoke_action(self, name: str, params: Mapping[str, Any]) -> Any:
        if name in _LIFECYCLE:
            raise ValueError(f"{name} is the episode API, not an Agent action")
        method = getattr(self, name, None)
        if method is None or not callable(method):
            raise ValueError(f"unknown action {name!r}")
        return method(**params)

    @classmethod
    def _actions(cls) -> tuple[NativeAction, ...]:
        declarations: list[NativeAction] = []
        for name, func in iter_env_actions(cls):
            if name in _LIFECYCLE:
                raise TypeError(
                    f"{cls.__name__}.{name} is the Gymnasium episode API; "
                    "do not mark it with @action. The Job or Harness calls "
                    "reset() and step(); the Agent only calls world moves."
                )
            declarations.append(
                NativeAction(
                    name=name,
                    description=(inspect.getdoc(func) or name).strip(),
                    kind="python",
                    parameters=function_schema(func),
                )
            )
        return tuple(declarations)

    @classmethod
    def _rewarders(cls) -> tuple[RewarderDefinition, ...]:
        declarations: list[RewarderDefinition] = []
        seen: set[str] = set()
        for owner in cls.__mro__:
            for value in owner.__dict__.values():
                config = getattr(value, _REWARDER_ATTR, None)
                if not callable(value) or not isinstance(config, dict):
                    continue
                rewarder_name = str(config["name"])
                if rewarder_name in seen:
                    continue
                seen.add(rewarder_name)
                declarations.append(
                    RewarderDefinition(
                        name=rewarder_name,
                        description=(inspect.getdoc(value) or "").strip(),
                        kind="python",
                        implementation_digest=callable_implementation_digest(value),
                        weight=float(config["weight"]),
                        timeout_seconds=float(config["timeout_seconds"]),
                    )
                )
        return tuple(declarations)

    def definition(self) -> EnvironmentDefinition:
        """Compile exactly one canonical Environment revision.

        Returns:
            The immutable definition used by Jobs and hosted publication.
        """
        if self._compiled_definition is not None:
            return self._compiled_definition
        observation_type, state_type = self._declared_types()
        actions = self._actions()
        reset_command = tuple(self.reset_command)
        if self._adapter_command is not None:
            actions = tuple(
                action.model_copy(
                    update={
                        "kind": "command",
                        "command": (*self._adapter_command, action.name),
                    }
                )
                for action in actions
            )
            reset_command = (*self._adapter_command, "reset")
        return EnvironmentDefinition(
            name=self.name,
            version=self.version,
            description=self.description,
            overview=self.overview,
            readme=self.readme,
            actions=actions,
            reset_command=reset_command,
            observation_schema=_model_schema(observation_type),
            state_schema=_model_schema(state_type),
            rewarders=self._rewarders(),
            guardrails=self.guardrails,
            resources=self.resources,
            runtime=self.runtime,
            secrets=self.secrets,
            harness_policy=self.harness_policy,
            limits=self.limits,
            metadata=deepcopy(self.metadata),
            source=self.source,
        )


__all__ = ["Environment", "action", "rewarder"]
