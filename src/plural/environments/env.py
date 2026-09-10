"""Gym-shaped :class:`Environment`: reset, step, and scored episodes.

Subclass this class to write a game or work env — name, version, tools,
observations, and rewards live on that class. :meth:`Environment.step` owns
lifecycle and trace orchestration; override :meth:`Environment.apply_action`
for non-tool action semantics.

``TaskData``, ``StepResult``, ``Rollout``, and ``tool`` live in sibling
modules. They are re-exported here so older imports still resolve.

Examples:
    >>> from plural.environments.env import Environment
    >>> from plural.environments.task import TaskData
    >>> env = Environment(name="support-triage", version="0.1.0")
    >>> @env.scorer(weight=1.0)
    ... def always_one(rollout):
    ...     return 1.0
    >>> list(env.scorers)[0][0]
    'always_one'
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import time
from collections.abc import Callable, Iterator
from functools import partial
from typing import Any, Generic, cast, final, get_args, get_origin

from plural.client import Client
from plural.environments.action import ActionResult, is_tool_action, normalize_action
from plural.environments.action_registry import (
    action,
    action_root_scope,
    instrument_action,
    iter_env_actions,
    make_action_def,
    root_action_steps,
)
from plural.environments.episode import Episode, episode_metrics
from plural.environments.fingerprint import (
    callable_implementation_digest,
    stable_fingerprint_value,
)
from plural.environments.policy import PluralPolicy, Policy
from plural.environments.rollout import Rollout, ScorerFn
from plural.environments.runtime import LocalRuntime, Runtime
from plural.environments.step import StepResult
from plural.environments.stop import EpisodeError, EpisodeState, StopReason, is_stopped
from plural.environments.task import TaskData, TaskFn
from plural.environments.types import (
    Observation,
    ObsT,
    State,
    StateT,
    as_text,
    is_empty_observation,
    serialize_observation,
)
from plural.tracing.schema import (
    ActionStep,
    Outcome,
    ParsedAction,
    RewardEvent,
    Trace,
    TraceContext,
)
from plural.types import ChatRequest, ChatResponse, Message, Tool

__all__ = ["Environment", "Rollout", "StepResult", "TaskData", "action"]


def _references_instance(value: Any, instance: Any, seen: set[int] | None = None) -> bool:
    """Recursively detect a captured environment through closures and containers.

    Returns:
        Whether ``value`` references ``instance``.
    """
    if value is instance:
        return True
    if value is None or isinstance(value, (bool, int, float, complex, str, bytes)):
        return False
    if inspect.isclass(value) or inspect.ismodule(value):
        return False
    visited = seen if seen is not None else set()
    value_id = id(value)
    if value_id in visited:
        return False
    visited.add(value_id)

    try:
        bound_self = inspect.getattr_static(value, "__self__")
    except (AttributeError, TypeError):
        bound_self = None
    if bound_self is instance or (
        bound_self is not None and _references_instance(bound_self, instance, visited)
    ):
        return True
    try:
        target = inspect.unwrap(value) if callable(value) else value
    except (ValueError, TypeError):
        target = value
    closure = getattr(target, "__closure__", None) or ()
    for cell in closure:
        try:
            if _references_instance(cell.cell_contents, instance, visited):
                return True
        except ValueError:
            continue
    defaults = getattr(target, "__defaults__", None)
    if defaults is not None and _references_instance(defaults, instance, visited):
        return True
    kwdefaults = getattr(target, "__kwdefaults__", None)
    if kwdefaults is not None and _references_instance(kwdefaults, instance, visited):
        return True
    if isinstance(value, partial) and (
        _references_instance(value.func, instance, visited)
        or _references_instance(value.args, instance, visited)
        or _references_instance(value.keywords, instance, visited)
    ):
        return True
    if isinstance(value, dict):
        return any(
            _references_instance(key, instance, visited)
            or _references_instance(item, instance, visited)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_references_instance(item, instance, visited) for item in value)
    try:
        namespace = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError):
        namespace = None
    if isinstance(namespace, dict) and any(
        _references_instance(item, instance, visited) for item in namespace.values()
    ):
        return True
    for owner in type(value).__mro__:
        slots = owner.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            slot_names = (slots,)
        elif isinstance(slots, dict):
            slot_names = tuple(slots)
        else:
            try:
                slot_names = tuple(slots)
            except TypeError:
                continue
        for declared_name in slot_names:
            if not isinstance(declared_name, str) or declared_name in {"__dict__", "__weakref__"}:
                continue
            name = declared_name
            if name.startswith("__") and not name.endswith("__"):
                name = f"_{owner.__name__.lstrip('_')}{name}"
            descriptor = owner.__dict__.get(name)
            if descriptor is None or not (
                inspect.ismemberdescriptor(descriptor) or inspect.isgetsetdescriptor(descriptor)
            ):
                continue
            try:
                item = descriptor.__get__(value, type(value))
            except (AttributeError, TypeError):
                continue
            if _references_instance(item, instance, visited):
                return True
    if callable(value) and not inspect.isroutine(target):
        try:
            call_implementation = inspect.getattr_static(type(value), "__call__")
        except (AttributeError, TypeError):
            call_implementation = None
        if call_implementation is not None and _references_instance(
            call_implementation, instance, visited
        ):
            return True
    return False


def _model_schema(model: type[Any]) -> dict[str, Any]:
    """Return a JSON Schema for a Pydantic observation or state model."""
    schema_fn = getattr(model, "model_json_schema", None)
    if not callable(schema_fn):
        return {}
    try:
        schema = schema_fn()
    except Exception:  # noqa: BLE001
        return {}
    return schema if isinstance(schema, dict) else {}


def _normalize_records(
    values: list[Any] | None,
    *,
    name_key: str,
    text_keys: tuple[str, ...],
) -> list[dict[str, str]]:
    """Turn strings or dicts into stable ``{name, rule}``-shaped records.

    Returns:
        Normalized guardrail records.
    """
    records: list[dict[str, str]] = []
    for raw in values or []:
        if isinstance(raw, str):
            text = raw.strip()
            if text:
                record = {name_key: text} if name_key == "rule" else {name_key: "", "rule": text}
                records.append(record)
            continue
        if not isinstance(raw, dict):
            continue
        name = str(raw.get(name_key) or raw.get("name") or "").strip()
        text = ""
        for key in text_keys:
            candidate = raw.get(key)
            if isinstance(candidate, str) and candidate.strip():
                text = candidate.strip()
                break
        if not text:
            text = name
        if name or text:
            records.append({"name": name, "rule": text})
    return records


class Environment(Generic[ObsT, StateT]):
    """Versioned world: instructions, actions, observation/state, and guardrails.

    Subclass this as ``Environment[MyObservation, MyState]``. Put writable
    memory and hidden data on ``self.state``, expose a typed observation,
    and decorate actions with :func:`tool`. Drive an agent with
    :meth:`reset` / :meth:`step` or :meth:`rollout` — not :meth:`observe`.

    The model is not part of the environment. :meth:`step` is framework-owned:
    it records the decision and advances the lifecycle. Override
    :meth:`apply_action` when actions are not tool calls.

    Class attributes ``name``, ``version``, ``description``, ``readme``,
    ``system_prompt``, ``max_turns``, ``guardrails``, and ``skills`` are
    the defaults; constructor kwargs override them. Only ``name`` and
    ``version`` are required for a working env.

    Args:
        name: Environment name.
        version: Semver version string. Bump when tools, observations, or
            reward semantics change.
        system_prompt: Optional instructions prepended to every episode.
        max_turns: Maximum model↔tool turns per episode.
        description: One-line summary of what this world does.
        readme: Markdown overview shown on the hosted environment.
        guardrails: Rules that constrain the agent and the world.
        skills: Optional named groupings of actions.
        metadata: Arbitrary environment metadata.

    Examples:
        >>> from plural.environments.env import Environment
        >>> from plural.environments.action_registry import action
        >>> from plural.environments.types import Observation, State
        >>> class CounterState(State):
        ...     n: int = 0
        >>> class CounterObservation(Observation):
        ...     n: int = 0
        ...
        ...     def render(self) -> str:
        ...         return f"count={self.n}"
        >>> class CounterEnv(Environment[CounterObservation, CounterState]):
        ...     name = "counter"
        ...     version = "0.1.0"
        ...
        ...     def setup(self, task):
        ...         super().setup(task)
        ...         self.state = CounterState(seed=self.seed, n=0)
        ...
        ...     def observe(self):
        ...         return CounterObservation(n=self.state.n)
        ...
        ...     @action
        ...     def inc(self, by: int = 1) -> dict:
        ...         '''Increment the counter.'''
        ...         self.state.n += by
        ...         return {"n": self.state.n}
        >>> env = CounterEnv()
        >>> "inc" in env.actions
        True
    """

    name: str = "environment"
    version: str = "0.1.0"
    description: str = ""
    readme: str = ""
    system_prompt: str | None = None
    max_turns: int = 8
    guardrails: list[Any] = []
    skills: list[Any] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "step" in cls.__dict__:
            raise TypeError(
                "Environment.step() is framework-owned; override apply_action() instead"
            )

    def __init__(
        self,
        name: str | None = None,
        version: str | None = None,
        *,
        system_prompt: str | None = None,
        max_turns: int | None = None,
        description: str | None = None,
        readme: str | None = None,
        guardrails: list[Any] | None = None,
        skills: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        cls = type(self)
        self.name = cls.name if name is None else name
        self.version = cls.version if version is None else version
        self.description = cls.description if description is None else description
        self.readme = cls.readme if readme is None else readme
        self.system_prompt = cls.system_prompt if system_prompt is None else system_prompt
        self.max_turns = cls.max_turns if max_turns is None else max_turns
        self.guardrails = list(cls.guardrails if guardrails is None else guardrails)
        self.skills = list(cls.skills if skills is None else skills)
        self.metadata = metadata or {}
        self.remote_id: str | None = None
        self.action_functions: dict[str, Callable[..., Any]] = {}
        self.action_defs: list[Tool] = []
        self.scorers: list[tuple[str, ScorerFn, float]] = []
        self._tasks_fn: TaskFn | None = None
        self.task: Any = None
        self.seed: int | None = None
        self._state: State = State()
        self._observation: Observation | None = None
        self._episode: Episode | None = None
        self._register_class_actions()

    @property
    def slug(self) -> str:
        """Project-unique slug derived from :attr:`name`."""
        value = re.sub(r"[^a-z0-9]+", "-", (self.name or "").lower()).strip("-")
        return value[:80] or "environment"

    def observation_schema(self) -> dict[str, Any]:
        """JSON Schema for the per-action observation the agent can see.

        Returns:
            A JSON Schema object for the observation model.
        """
        return _model_schema(self._contract_types()[0])

    def state_schema(self) -> dict[str, Any]:
        """JSON Schema for persistent environment state, including hidden fields.

        Returns:
            A JSON Schema object for the state model.
        """
        return _model_schema(self._contract_types()[1])

    def context_policy(self) -> dict[str, Any]:
        """How a turn is assembled into the policy's ``ChatRequest``.

        Override when the conversation should not be instructions plus the
        rendered observation plus history.

        Returns:
            Context assembly defaults such as roles and ``max_turns``.
        """
        return {
            "instructions_role": "system",
            "observation_role": "user",
            "include_history": True,
            "max_turns": self.max_turns,
        }

    def normalized_guardrails(self) -> list[dict[str, str]]:
        """Return guardrails as ``{name, rule}`` records.

        Returns:
            Normalized guardrail records.
        """
        return _normalize_records(
            self.guardrails,
            name_key="name",
            text_keys=("rule", "text", "description"),
        )

    def normalized_skills(self) -> list[dict[str, Any]]:
        """Return skills as hosted manifest records."""
        records: list[dict[str, Any]] = []
        for raw in self.skills or []:
            if isinstance(raw, str):
                name = raw.strip()
                if name:
                    records.append(
                        {
                            "name": name,
                            "description": "",
                            "instructions": "",
                            "tool_names": [],
                        }
                    )
                continue
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            tool_names = raw.get("tool_names") or raw.get("tools") or []
            records.append(
                {
                    "name": name,
                    "description": str(raw.get("description") or ""),
                    "instructions": str(raw.get("instructions") or ""),
                    "tool_names": (
                        [str(item) for item in tool_names] if isinstance(tool_names, list) else []
                    ),
                }
            )
        return records

    def overridden_hooks(self) -> list[str]:
        """Author hooks this subclass implements beyond the defaults.

        Returns:
            Hook names implemented on the subclass.
        """
        names: list[str] = []
        for hook in (
            "setup",
            "observe",
            "apply_action",
            "done",
            "snapshot",
            "step_reward",
        ):
            current = getattr(type(self), hook, None)
            base = getattr(Environment, hook, None)
            if current is not None and current is not base:
                names.append(hook)
        return names

    @property
    def state(self) -> StateT:
        """Current episode :class:`~plural.environments.types.State`."""
        return self._state  # type: ignore[return-value]

    @state.setter
    def state(self, value: StateT) -> None:
        self._state = value
        if value.seed is not None:
            self.seed = value.seed

    @property
    def episode_state(self) -> EpisodeState:
        """Current lifecycle state for this environment instance."""
        if self._episode is None:
            return EpisodeState.IDLE
        if self._episode.closed:
            return EpisodeState.CLOSED
        if is_stopped(self._episode.stop_reason):
            return EpisodeState.STOPPED
        return EpisodeState.OPEN

    @property
    def episode_trace(self) -> Trace | None:
        """A read-only snapshot of the current or last episode trace.

        The snapshot remains available after the episode closes. Mutating it
        does not alter environment bookkeeping.
        """
        if self._episode is None:
            return None
        return self._episode.trace.model_copy(deep=True)

    @property
    def observation(self) -> ObsT:
        """Last observation produced by :meth:`reset` or :meth:`step`.

        Tools should read this cached view. Do not call :meth:`observe` from
        tools or from an agent loop.
        """
        if self._observation is None:
            return self.observe()
        return self._observation  # type: ignore[return-value]

    def setup(self, task: TaskData) -> None:
        """Seed ``self.state`` from ``task``. Override in subclasses.

        This is an author hook. Callers driving an agent use :meth:`reset`.

        Args:
            task: Task data with optional ``metadata["seed"]``.
        """
        self.task = task
        raw = None
        metadata = getattr(task, "metadata", None)
        if isinstance(metadata, dict):
            raw = metadata.get("seed")
        self.seed = int(raw) if raw is not None else None
        self.state = State(seed=self.seed)  # type: ignore[assignment]

    def observe(self) -> ObsT:
        """Build the current observation from ``self.state``.

        Author hook — :meth:`reset` and :meth:`step` call this. Drive an
        agent with those methods (or :meth:`rollout`), not ``observe``.

        Returns:
            An :class:`~plural.environments.types.Observation`. Empty
            ``text`` on the first turn falls back to the task input.
        """
        return Observation()  # type: ignore[return-value]

    def done(self) -> bool:
        """Return whether the episode has reached a natural end.

        Returns:
            ``True`` to terminate. Default is ``False`` (run until truncated).
        """
        return False

    def snapshot(self) -> dict[str, Any] | None:
        """Return an explicitly trace-safe snapshot of :attr:`state`.

        Returns:
            ``None``. Environment authors must override this hook to persist
            state in traces.
        """
        return None

    def step_reward(self, action_name: str, result: Any) -> float | None:
        """Optional dense reward after one native action.

        Args:
            action_name: Action that just ran.
            result: Action result payload.

        Returns:
            A float reward, or ``None`` to record nothing.
        """
        return None

    def spawn(self) -> Environment[ObsT, StateT]:
        """Return a fresh instance for a concurrent episode.

        Copies tools, scorers, and tasks. Game state starts empty — call
        :meth:`reset` on the result. One instance is one episode; Benchmark
        uses this so worker threads do not share ``self``.
        """
        try:
            other = type(self)(
                name=self.name,
                version=self.version,
                system_prompt=self.system_prompt,
                max_turns=self.max_turns,
                metadata=dict(self.metadata),
            )
        except TypeError as exc:
            raise RuntimeError(
                f"{type(self).__name__}.spawn() could not construct a fresh environment; "
                "override spawn() or pass Benchmark(environment_factory=...)"
            ) from exc
        for action_name, func in self.action_functions.items():
            if action_name not in other.action_functions:
                if _references_instance(func, self):
                    raise RuntimeError(
                        f"dynamic action {action_name!r} references the original environment and "
                        "cannot be isolated by spawn(); use Benchmark(environment_factory=...)"
                    )
                other._add_action(action_name, func)

        fresh_scorers = list(other.scorers)
        rebuilt_scorers: list[tuple[str, ScorerFn, float]] = []
        for index, (scorer_name, scorer_fn, weight) in enumerate(self.scorers):
            fresh_fn: ScorerFn | None = None
            if index < len(fresh_scorers):
                fresh_name, candidate, fresh_weight = fresh_scorers[index]
                if (
                    fresh_name == scorer_name
                    and fresh_weight == weight
                    and callable_implementation_digest(candidate)
                    == callable_implementation_digest(scorer_fn)
                ):
                    fresh_fn = candidate
            if getattr(scorer_fn, "__self__", None) is self:
                method = cast(Any, scorer_fn)
                scorer_fn = method.__func__.__get__(other, type(other))
            elif _references_instance(scorer_fn, self):
                if fresh_fn is None:
                    raise RuntimeError(
                        f"scorer {scorer_name!r} references the original environment and "
                        "cannot be isolated by spawn(); use Benchmark(environment_factory=...)"
                    )
                scorer_fn = fresh_fn
            rebuilt_scorers.append((scorer_name, scorer_fn, weight))
        other.scorers = rebuilt_scorers

        tasks_fn = self._tasks_fn
        if tasks_fn is not None and getattr(tasks_fn, "__self__", None) is self:
            method = cast(Any, tasks_fn)
            tasks_fn = method.__func__.__get__(other, type(other))
        elif tasks_fn is not None and _references_instance(tasks_fn, self):
            fresh_tasks_fn = other._tasks_fn
            if fresh_tasks_fn is None or callable_implementation_digest(
                fresh_tasks_fn
            ) != callable_implementation_digest(tasks_fn):
                raise RuntimeError(
                    "tasks provider references the original environment and cannot be isolated "
                    "by spawn(); use Benchmark(environment_factory=...)"
                )
            tasks_fn = fresh_tasks_fn
        other._tasks_fn = tasks_fn
        other.description = self.description
        other.readme = self.readme
        other.guardrails = list(self.guardrails)
        other.skills = list(self.skills)
        return other

    def action(self, fn: Callable[..., Any] | None = None, *, name: str | None = None) -> Any:
        """Register a Python function as a native action.

        Args:
            fn: Function to register (decorator usage).
            name: Optional explicit action name.

        Returns:
            The original function (decorator) or a decorator.
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._add_action(name or func.__name__, func)
            return func

        if fn is not None:
            return decorator(fn)
        return decorator

    @property
    def actions(self) -> dict[str, Callable[..., Any]]:
        """Registered native action callables."""
        return self.action_functions

    def scorer(
        self,
        fn: ScorerFn | None = None,
        *,
        weight: float = 1.0,
        name: str | None = None,
    ) -> Any:
        """Register a scorer.

        Args:
            fn: Scorer callable ``(rollout) -> float``.
            weight: Weight in the aggregate reward.
            name: Optional scorer name.

        Returns:
            The original function (decorator) or a decorator.
        """

        def decorator(func: ScorerFn) -> ScorerFn:
            self.scorers.append((name or func.__name__, func, weight))
            return func

        if fn is not None:
            return decorator(fn)
        return decorator

    def tasks(self, fn: TaskFn) -> TaskFn:
        """Register a tasks provider.

        Args:
            fn: Callable returning an iterable of :class:`~plural.environments.task.TaskData`.

        Returns:
            The original function.
        """
        self._tasks_fn = fn
        return fn

    def iter_tasks(self) -> Iterator[TaskData]:
        """Yield all tasks.

        Yields:
            Task data instances.

        Raises:
            RuntimeError: If no tasks provider was registered.
        """
        if self._tasks_fn is None:
            raise RuntimeError(f"environment '{self.name}' has no tasks provider")
        yield from self._tasks_fn()

    def fingerprint_payload(self) -> Any:
        """Return stable constructor or external configuration for fingerprinting.

        Override this when behavior depends on configuration not otherwise
        represented by tools, scorers, hooks, or standard environment fields.
        Returned values must be deterministic and free of secrets.
        """
        return {}

    def fingerprint(self) -> str:
        """Hash the action surface and scoring contract.

        Two episodes with the same fingerprint saw the same tools,
        instructions, and scorer weights.

        Returns:
            Hex SHA256 digest.
        """
        obs_name, state_name = self._contract_names()
        tool_schemas = {
            definition.function.name: definition.model_dump(mode="json")
            for definition in self.action_defs
        }
        payload = {
            "name": self.name,
            "version": self.version,
            "max_turns": self.max_turns,
            "instructions": self.system_prompt,
            "observation": obs_name,
            "state": state_name,
            "observation_schema": self.observation_schema(),
            "state_schema": self.state_schema(),
            "guardrails": self.normalized_guardrails(),
            "skills": self.normalized_skills(),
            "configuration": stable_fingerprint_value(self.fingerprint_payload()),
            "tools": [
                {
                    "name": name,
                    "schema": tool_schemas.get(name),
                    "implementation": callable_implementation_digest(fn),
                }
                for name, fn in sorted(self.action_functions.items())
            ],
            "scorers": [
                {
                    "name": name,
                    "weight": weight,
                    "implementation": callable_implementation_digest(fn),
                }
                for name, fn, weight in sorted(self.scorers, key=lambda item: item[0])
            ],
            "hooks": {
                hook: callable_implementation_digest(getattr(self, hook))
                for hook in (
                    "setup",
                    "observe",
                    "apply_action",
                    "done",
                    "snapshot",
                    "step_reward",
                )
            },
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def create(self, client: Client, **kwargs: Any) -> dict[str, Any]:
        """Alias for ``client.create(self)``.

        Args:
            client: Authenticated Plural client.
            **kwargs: Optional ``name`` or ``description``.

        Returns:
            Created revision plus ``environment_id`` and ``slug``.
        """
        return client.create(self, **kwargs)

    def update(self, client: Client, **kwargs: Any) -> dict[str, Any]:
        """Alias for ``client.update(self)``.

        Args:
            client: Authenticated Plural client.
            **kwargs: Optional ``environment_id``, ``name``, or ``description``.

        Returns:
            Updated revision plus ``environment_id`` and ``slug``.
        """
        return client.update(self, **kwargs)

    def push(self, client: Client, **kwargs: Any) -> dict[str, Any]:
        """Create or update this environment by slug.

        Prefer :meth:`create` or :meth:`update` when the intent is explicit.

        Args:
            client: Authenticated Plural client.
            **kwargs: Optional ``environment_id``, ``name``, or ``description``.

        Returns:
            Created revision plus ``environment_id`` and ``slug``.
        """
        return client.push(self, **kwargs)

    def reset(
        self,
        task: TaskData,
        *,
        model: str | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        """Start an episode. Gymnasium-shaped: ``obs, info = env.reset(task)``.

        Args:
            task: Task that seeds this instance via :meth:`setup`.
            model: Optional policy id recorded on the episode trace.

        Returns:
            ``(observation, info)``.

        Raises:
            EpisodeError: If the current episode is still open.
        """
        if self.episode_state in {EpisodeState.OPEN, EpisodeState.STOPPED}:
            raise EpisodeError(
                "cannot reset before closing the current episode",
                self.episode_state,
            )
        self.setup(task)
        observation = self._initial_observation(task)
        self._observation = observation if isinstance(observation, Observation) else None
        messages: list[Message] = []
        if self.system_prompt:
            messages.append(Message(role="system", content=self.system_prompt))
        messages.append(Message(role="user", content=as_text(observation)))

        trace = Trace(
            trace_kind="episode",
            environment=self.name,
            environment_version=self.version,
            environment_fingerprint=self.fingerprint(),
            task_id=task.task_id,
            model=model,
            initial_state=self._safe_snapshot(),
            metadata={**self.metadata, "task": task.trace_payload()},
            tags={"environment": self.name},
        )
        trace.episode_trace_id = trace.trace_id
        self._episode = Episode(
            task=task,
            trace=trace,
            messages=messages,
            observation=observation,
        )
        info = {
            "task_id": task.task_id,
            "environment": self.name,
            "environment_version": self.version,
            "environment_fingerprint": trace.environment_fingerprint,
        }
        return observation, info

    def messages(self) -> list[Message]:
        """Return the current episode conversation for the policy.

        After :meth:`reset`, this is instructions plus the first observation.
        After :meth:`step`, tool results and the next observation are
        appended so the next ``chat`` sees the same board the decision
        recorded.

        Returns:
            A copy of the open episode's messages.

        Raises:
            RuntimeError: If :meth:`reset` has not been called.
        """
        return list(self._require_episode(allow_stopped=True).messages)

    def trace_context(self) -> TraceContext:
        """Return lineage for a model call made inside the current episode."""
        trace = self._require_episode().trace
        return TraceContext(parent_trace_id=trace.trace_id, episode_trace_id=trace.trace_id)

    def record_response(self, response: ChatResponse) -> None:
        """Append one policy response to the open episode conversation.

        :meth:`step` calls this automatically when a response is supplied.
        Manual advanced integrations may call it when recording a response
        without stepping.
        """
        episode = self._require_episode()
        assistant = response.message
        last = episode.messages[-1] if episode.messages else None
        already = (
            last is not None
            and last.role == "assistant"
            and last.tool_calls == assistant.tool_calls
            and last.content == assistant.content
        )
        if not already:
            episode.messages.append(assistant)
        episode.last_response = response

    def apply_action(
        self,
        action: Any,
        *,
        runtime: Runtime,
        response: ChatResponse | None = None,
    ) -> ActionResult:
        """Apply author-defined semantics for one policy action.

        The base implementation normalizes model tool calls, dispatches them
        through ``runtime``, and returns trace data for :meth:`step` to record.
        Tool-based environments normally do not override this hook. Scalar or
        custom text environments can mutate state here and return their own
        :class:`~plural.environments.action.ActionResult`.

        This hook must not call :meth:`record_turn` or :meth:`finish_turn`;
        framework-owned :meth:`step` performs that bookkeeping.

        Args:
            action: Raw policy action.
            runtime: Runtime used to execute normalized tool calls.
            response: Optional policy response associated with the action.

        Returns:
            Applied action, tool, reward, stop, and diagnostic fields.
        """
        parsed, tool_calls_in = normalize_action(action, response)
        action_steps: list[ActionStep] = []
        reward_events: list[RewardEvent] = []

        for parsed_action, tool_call_id in zip(parsed, tool_calls_in, strict=False):
            if not is_tool_action(parsed_action):
                if parsed_action.source == "environment_native":
                    parsed_action.source = "model_text"
                continue
            with action_root_scope():
                result, latency_ms, error = self._invoke_tool(
                    runtime, parsed_action.name, parsed_action.arguments
                )
                roots = root_action_steps()
            action_step = roots[0] if roots else None
            if action_step is None:
                action_step = ActionStep(
                    name=parsed_action.name,
                    arguments=parsed_action.arguments,
                    source="environment_native",
                    observation=result,
                    result=result,
                    error=error,
                    latency_ms=latency_ms,
                )
            action_step.tool_call_id = tool_call_id
            action_steps.append(action_step)
            value = self.step_reward(parsed_action.name, result)
            if value is not None:
                reward_events.append(RewardEvent(name=parsed_action.name, value=float(value)))

        stop_reason = None
        if not parsed or all(not is_tool_action(item) for item in parsed):
            stop_reason = StopReason.POLICY_STOP
        return ActionResult(
            parsed_actions=parsed,
            actions=action_steps,
            reward_events=reward_events,
            stop_reason=stop_reason,
        )

    @final
    def step(
        self,
        action: Any = None,
        *,
        request: ChatRequest | dict[str, Any] | None = None,
        response: ChatResponse | None = None,
        runtime: Runtime | None = None,
    ) -> StepResult:
        """Apply one policy decision. Unpack as Gymnasium's 5-tuple.

        This method is framework-owned and cannot be overridden. It records
        the policy response, delegates action semantics to :meth:`apply_action`
        exactly once, records a :class:`~plural.tracing.schema.Turn`, and
        advances the lifecycle. Override :meth:`apply_action` for scalar or
        custom text actions.

        Args:
            action: Parsed actions, tool calls, a :class:`ChatResponse`, or
                ``None`` to take tool calls from ``response``.
            request: Chat request the policy saw (stored on the decision).
            response: Chat response for this turn.
            runtime: Tool runtime; defaults to :class:`LocalRuntime`.

        Returns:
            :class:`~plural.environments.step.StepResult`.

        Raises:
            RuntimeError: If :meth:`reset` has not been called.
        """
        self._require_episode()
        try:
            return self._step_once(
                action,
                request=request,
                response=response,
                runtime=runtime,
            )
        except Exception as exc:
            self._abort_episode(exc)
            raise

    def _step_once(
        self,
        action: Any,
        *,
        request: ChatRequest | dict[str, Any] | None,
        response: ChatResponse | None,
        runtime: Runtime | None,
    ) -> StepResult:
        """Orchestrate one action on an active episode.

        Returns:
            The completed step result.
        """
        episode = self._require_episode()
        policy_response = (
            action if response is None and isinstance(action, ChatResponse) else response
        )
        if policy_response is not None:
            self.record_response(policy_response)
        observation = episode.observation
        if runtime is None:
            runtime = LocalRuntime(self.action_functions)

        action_result = self.apply_action(action, runtime=runtime, response=policy_response)
        if not isinstance(action_result, ActionResult):
            raise TypeError("Environment.apply_action() must return ActionResult")

        episode.tool_errors = self._tool_errors(action_result.actions)
        for action_step in action_result.actions:
            episode.messages.append(
                Message(
                    role="tool",
                    tool_call_id=action_step.tool_call_id,
                    name=action_step.name,
                    content=(
                        json.dumps(action_step.observation)
                        if not isinstance(action_step.observation, str)
                        else action_step.observation
                    )
                    if action_step.observation is not None
                    else (
                        json.dumps(action_step.result)
                        if not isinstance(action_step.result, str)
                        else action_step.result
                    ),
                )
            )

        self.record_turn(
            observation=observation,
            model_context=request,
            model_output=policy_response,
            parsed_action=action_result.parsed_actions,
            actions=action_result.actions,
            reward_events=action_result.reward_events,
        )
        step_result = self.finish_turn(
            action_result.reward_events,
            stop_reason=action_result.stop_reason,
        )
        step_result.info = {**action_result.info, **step_result.info}
        return step_result

    def record_turn(
        self,
        *,
        observation: Any = None,
        model_context: ChatRequest | dict[str, Any] | None = None,
        model_output: ChatResponse | None = None,
        parsed_action: list[ParsedAction] | None = None,
        actions: list[ActionStep] | None = None,
        reward_events: list[RewardEvent] | None = None,
    ) -> None:
        """Append a turn to the open episode trace.

        :meth:`step` calls this automatically from the
        :class:`~plural.environments.action.ActionResult` returned by
        :meth:`apply_action`. It remains public for advanced manual use.
        """
        episode = self._require_episode()
        episode.trace.add_turn(
            turn=episode.turn,
            observation=serialize_observation(observation),
            model_context=model_context,
            model_output=model_output,
            parsed_action=parsed_action or [],
            actions=actions or [],
            reward_events=reward_events or [],
        )
        if model_output is not None:
            episode.last_response = model_output

    def finish_turn(
        self,
        reward_events: list[RewardEvent] | None = None,
        *,
        stop_reason: StopReason | str | None = None,
    ) -> StepResult:
        """Advance the episode after an action and return a Gym 5-tuple.

        Increments the turn, rebuilds the observation, reads :meth:`done`,
        and marks truncation at ``max_turns``. It remains public for advanced
        manual use; :meth:`apply_action` should normally return an
        :class:`~plural.environments.action.ActionResult` instead of calling
        this method.

        Args:
            reward_events: Events whose values sum to this step's reward.
            stop_reason: Explicit stop reason, if the policy or execution stopped.

        Returns:
            :class:`~plural.environments.step.StepResult`.
        """
        episode = self._require_episode()
        events = reward_events or []
        episode.turn += 1
        next_obs = self.observe()
        if is_empty_observation(next_obs):
            next_obs = episode.observation
        self._observation = next_obs if isinstance(next_obs, Observation) else None
        episode.observation = next_obs
        self._append_observation(next_obs)
        terminated = self.done()
        truncated = episode.turn >= self.max_turns and not terminated
        normalized_stop = StopReason(stop_reason) if stop_reason is not None else None
        if normalized_stop is not StopReason.FAILURE:
            if terminated:
                normalized_stop = StopReason.TERMINATED
            elif truncated:
                normalized_stop = StopReason.TRUNCATED
        episode.terminated = terminated
        episode.truncated = truncated
        episode.stop_reason = normalized_stop
        return StepResult(
            observation=next_obs,
            reward=sum(event.value for event in events),
            terminated=terminated,
            truncated=truncated,
            info={
                "turn": episode.turn,
                "stop_reason": normalized_stop.value if normalized_stop is not None else None,
                "tool_errors": list(episode.tool_errors),
            },
        )

    def close_episode(
        self,
        *,
        response: ChatResponse | None = None,
        client: Client | None = None,
    ) -> Rollout:
        """Score the open episode.

        Args:
            response: Final model response, if not already stored.
            client: If given, persist the episode trace on its writer.

        Returns:
            A scored :class:`~plural.environments.rollout.Rollout`.

        Raises:
            RuntimeError: If :meth:`reset` has not been called.
        """
        episode = self._require_episode(allow_stopped=True)
        final_response = response or episode.last_response
        rollout = Rollout(
            task=episode.task,
            trace=episode.trace,
            messages=episode.messages,
            response=final_response,
            env=self,
        )
        try:
            scores, reward = self._score(rollout)
        except Exception as exc:
            self._abort_episode(exc, client=client)
            raise
        episode.trace.outcome = Outcome(scores=scores, reward=reward if self.scorers else None)
        episode.trace.final_state = self._safe_snapshot()
        episode.trace.terminated = episode.terminated
        episode.trace.truncated = episode.truncated
        episode.trace.stop_reason = (
            episode.stop_reason.value if episode.stop_reason is not None else None
        )
        episode.trace.failed = episode.stop_reason is StopReason.FAILURE
        if episode.trace.failed:
            episode.trace.metadata.setdefault(
                "failure",
                {"type": "StopReason", "message": "episode stopped with failure"},
            )
        episode.trace.metrics = episode_metrics(episode)
        episode.closed = True
        if client is not None:
            client.writer.record(episode.trace)
        return rollout

    def run_episode(
        self,
        task: TaskData,
        policy: Policy,
        *,
        model: str | None = None,
        runtime: Runtime | None = None,
        persist_with: Client | None = None,
    ) -> Rollout:
        """Run one complete episode with a synchronous policy.

        Args:
            task: Task to run.
            policy: Policy used to choose each action.
            model: Optional policy id recorded on requests and the trace.
            runtime: Tool runtime; defaults to an in-process runtime.
            persist_with: Optional client used only for the final trace.

        Returns:
            The closed, scored rollout.
        """
        if runtime is None:
            runtime = LocalRuntime(self.action_functions)
        self.reset(task, model=model)
        trace_context = self.trace_context()
        final_response: ChatResponse | None = None

        try:
            for _ in range(self.max_turns):
                request = ChatRequest(
                    model=model or "policy",
                    messages=self.messages(),
                    tools=self.action_defs or None,
                )
                policy_output = policy.act(request, trace_context=trace_context)
                response = policy_output if isinstance(policy_output, ChatResponse) else None
                if not isinstance(policy_output, (ChatResponse, ParsedAction, list)):
                    raise TypeError(
                        "Policy.act() must return ChatResponse, ParsedAction, or list[ParsedAction]"
                    )
                if isinstance(policy_output, list) and not all(
                    isinstance(item, ParsedAction) for item in policy_output
                ):
                    raise TypeError("Policy.act() returned a list containing a non-ParsedAction")
                if response is not None:
                    final_response = response
                result = self.step(
                    policy_output,
                    request=request,
                    response=response,
                    runtime=runtime,
                )
                if is_stopped(result.info.get("stop_reason")):
                    break
        except Exception as exc:
            self._abort_episode(exc, client=persist_with)
            raise

        return self.close_episode(response=final_response, client=persist_with)

    def rollout(
        self,
        task: TaskData,
        client: Client,
        *,
        model: str,
        models: list[str] | None = None,
        runtime: Runtime | None = None,
        temperature: float | None = None,
        record_llm_traces: bool = False,
    ) -> Rollout:
        """Convenience: reset, LLM policy loop, :meth:`step` until done, score.

        Prefer :meth:`reset` / :meth:`step` when writing a training loop.
        This helper is what :class:`~plural.benchmarks.runner.Benchmark` uses.

        Args:
            task: Task to run.
            client: Client used for model calls.
            model: Primary model id.
            models: Optional fallback chain.
            runtime: Tool runtime; defaults to an in-process :class:`LocalRuntime`.
            temperature: Optional sampling temperature.
            record_llm_traces: Persist linked per-call traces in addition to
                the episode trace.

        Returns:
            A :class:`~plural.environments.rollout.Rollout` containing a scored
            :class:`~plural.tracing.schema.Trace`.
        """
        policy = PluralPolicy(
            client,
            model,
            fallbacks=models,
            temperature=temperature,
            tags={"environment": self.name, "task_id": task.task_id},
            record_llm_traces=record_llm_traces,
        )
        return self.run_episode(
            task,
            policy,
            model=model,
            runtime=runtime,
            persist_with=client,
        )

    def _require_episode(self, *, allow_stopped: bool = False) -> Episode:
        episode = self._episode
        if episode is None or episode.closed:
            raise EpisodeError(
                "operation requires an open episode; call Environment.reset() first",
                self.episode_state,
            )
        if not allow_stopped and is_stopped(episode.stop_reason):
            raise EpisodeError(
                "episode has stopped; only messages() and close_episode() remain available",
                self.episode_state,
            )
        return episode

    def _abort_episode(self, exc: Exception, *, client: Client | None = None) -> None:
        """Close the current episode as a persisted failure when possible."""
        episode = self._episode
        if episode is None:
            return
        message = " ".join(str(exc).split())[:300] or type(exc).__name__
        failure = {"type": type(exc).__name__, "message": message}
        episode.stop_reason = StopReason.FAILURE
        episode.trace.stop_reason = StopReason.FAILURE.value
        episode.trace.failed = True
        episode.trace.metadata["failure"] = failure
        outcome = episode.trace.outcome or Outcome()
        outcome.feedback = f"{failure['type']}: {failure['message']}"
        episode.trace.outcome = outcome
        if not episode.closed:
            episode.trace.final_state = self._safe_snapshot()
            episode.trace.terminated = episode.terminated
            episode.trace.truncated = episode.truncated
            episode.trace.metrics = episode_metrics(episode)
            episode.closed = True
        if client is not None and not episode.failure_persisted:
            client.writer.record(episode.trace)
            episode.failure_persisted = True

    def _append_observation(self, observation: Any) -> None:
        """Put the latest observation on the conversation the policy will see.

        Tool JSON is not enough: Wordle's board and letter key live on the
        observation. Skip empty or duplicate consecutive user turns.
        """
        text = as_text(observation)
        if not text:
            return
        episode = self._require_episode()
        last = episode.messages[-1] if episode.messages else None
        if last is not None and last.role == "user" and last.content == text:
            return
        episode.messages.append(Message(role="user", content=text))

    @staticmethod
    def _tool_errors(action_steps: list[ActionStep]) -> list[str]:
        errors: list[str] = []

        def collect(action_step: ActionStep) -> None:
            if action_step.error:
                errors.append(action_step.error)
            for child in action_step.children:
                collect(child)

        for action_step in action_steps:
            collect(action_step)
        return errors

    def _append_assistant(self, response: ChatResponse | None) -> None:
        if response is None:
            return
        self.record_response(response)

    def _score(self, rollout: Rollout) -> tuple[dict[str, float], float]:
        scores: dict[str, float] = {}
        reward = 0.0
        total_weight = 0.0
        for scorer_name, fn, weight in self.scorers:
            weight = float(weight)
            if not math.isfinite(weight):
                raise ValueError(f"scorer {scorer_name!r} has a non-finite weight")
            value = float(fn(rollout))
            if not math.isfinite(value):
                raise ValueError(f"scorer {scorer_name!r} returned a non-finite value")
            scores[scorer_name] = value
            reward += value * weight
            total_weight += weight
            if not math.isfinite(reward) or not math.isfinite(total_weight):
                raise ValueError("scorer aggregate produced a non-finite reward")
        if total_weight > 0:
            reward /= total_weight
        if not math.isfinite(reward):
            raise ValueError("scorer aggregate produced a non-finite reward")
        return scores, reward

    def _register_class_actions(self) -> None:
        for action_name, func in iter_env_actions(type(self)):
            bound = getattr(self, func.__name__)
            self._add_action(action_name, bound, schema_from=func, bind_method=func.__name__)

    def _add_action(
        self,
        action_name: str,
        func: Callable[..., Any],
        *,
        schema_from: Callable[..., Any] | None = None,
        bind_method: str | None = None,
    ) -> None:
        source = schema_from or func
        wrapped = instrument_action(action_name, func)
        self.action_functions[action_name] = wrapped
        if bind_method:
            setattr(self, bind_method, wrapped)
        self.action_defs.append(make_action_def(action_name, source))

    def _contract_types(self) -> tuple[type[Any], type[Any]]:
        for cls in type(self).__mro__:
            for base in getattr(cls, "__orig_bases__", ()):
                if get_origin(base) is Environment:
                    args = get_args(base)
                    if len(args) >= 2 and isinstance(args[0], type) and isinstance(args[1], type):
                        return args[0], args[1]
        return Observation, State

    def _contract_names(self) -> tuple[str, str]:
        observation, state = self._contract_types()
        return observation.__name__, state.__name__

    def _initial_observation(self, task: TaskData) -> Any:
        observed: Any = self.observe()
        if is_empty_observation(observed):
            observed = Observation(text=as_text(task.input))
        if isinstance(observed, Observation):
            self._observation = observed
        return observed

    def _safe_snapshot(self) -> dict[str, Any] | None:
        try:
            value = self.snapshot()
        except Exception:  # noqa: BLE001
            return None
        if value is None:
            return None
        return value if isinstance(value, dict) else {"value": value}

    def _invoke_tool(
        self,
        runtime: Runtime,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[Any, float, str | None]:
        started = time.perf_counter()
        try:
            if isinstance(runtime, LocalRuntime):
                result, latency_ms = runtime.call_timed(name, arguments)
            else:
                result = runtime.call(name, arguments)
                latency_ms = (time.perf_counter() - started) * 1000
            return result, latency_ms, None
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}, (time.perf_counter() - started) * 1000, str(exc)
