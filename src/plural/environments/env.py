"""Canonical Python authoring compiler for schema-v2 Environments."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Generic, cast, get_args, get_origin

from pydantic import BaseModel

from plural.common import PackageSource
from plural.environments.action_registry import action, function_schema, iter_env_actions
from plural.environments.fingerprint import callable_implementation_digest
from plural.environments.manifest import (
    EnvironmentManifest,
    EnvironmentResource,
    EnvironmentRuntime,
    ExecutionLimits,
    Guardrail,
    HarnessPolicy,
    NativeAction,
    RewarderDefinition,
    SecretReference,
)
from plural.environments.types import Observation, ObsT, State, StateT

_REWARDER_ATTR = "__plural_rewarder__"


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
    """Compile typed Python declarations into one ``EnvironmentManifest``.

    This class is authoring-only. It has no Task collection, model loop,
    Verifier phase or episode lifecycle.
    """

    name = "environment"
    revision = "0.1.0"
    description = ""
    overview = ""
    readme = ""
    metadata: dict[str, Any] = {}
    observation_type: type[Observation] = Observation
    state_type: type[State] = State

    def __init__(
        self,
        *,
        name: str | None = None,
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
        source: PackageSource | None = None,
        state: StateT | None = None,
        observation: ObsT | None = None,
    ) -> None:
        self.name = name or type(self).name
        self.revision = revision or type(self).revision
        self.description = type(self).description if description is None else description
        self.overview = type(self).overview if overview is None else overview
        self.readme = type(self).readme if readme is None else readme
        self.resources = resources
        self.runtime = runtime or EnvironmentRuntime()
        self.secrets = secrets
        self.guardrails = guardrails
        self.harness_policy = harness_policy or HarnessPolicy()
        self.limits = limits or ExecutionLimits()
        self.metadata = deepcopy(type(self).metadata) if metadata is None else deepcopy(metadata)
        self.source = source
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

    @classmethod
    def _actions(cls) -> tuple[NativeAction, ...]:
        declarations: list[NativeAction] = []
        for name, func in iter_env_actions(cls):
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

    def manifest(self) -> EnvironmentManifest:
        """Compile exactly one canonical Environment revision.

        Returns:
            The immutable manifest used by Jobs and hosted publication.
        """
        observation_type, state_type = self._declared_types()
        return EnvironmentManifest(
            name=self.name,
            revision=self.revision,
            description=self.description,
            overview=self.overview,
            readme=self.readme,
            actions=self._actions(),
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
