"""``@action`` decorator and JSON-schema helpers for environment methods.

Examples:
    >>> from plural.environments.action_registry import action
    >>> @action
    ... def ping() -> str:
    ...     '''Health check.'''
    ...     return "pong"
    >>> ping.__plural_action__
    'ping'
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from plural.tracing.schema import ActionStep
from plural.types import FunctionDefinition, Tool

_ACTION_ATTR = "__plural_action__"
_INSTRUMENTED = "_plural_instrumented"
_action_stack: ContextVar[list[ActionStep] | None] = ContextVar("plural_action_stack", default=None)
_action_roots: ContextVar[list[ActionStep] | None] = ContextVar("plural_action_roots", default=None)


def action(fn: Callable[..., Any] | None = None, *, name: str | None = None) -> Any:
    """Mark an :class:`~plural.environments.env.Environment` method as a native action.

    Args:
        fn: Method to register (decorator usage).
        name: Optional explicit action name. Defaults to the method name.

    Returns:
        The original method (decorator) or a decorator.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, _ACTION_ATTR, name or func.__name__)
        return func

    if fn is not None:
        return decorator(fn)
    return decorator


def is_env_action(fn: Callable[..., Any]) -> bool:
    """Return whether ``fn`` was decorated with :func:`action`."""
    return hasattr(fn, _ACTION_ATTR)


def iter_env_actions(env_cls: type) -> Iterable[tuple[str, Callable[..., Any]]]:
    """Yield ``(action_name, unbound_method)`` from an environment class MRO."""
    seen: set[str] = set()
    for cls in env_cls.__mro__:
        for attr, value in cls.__dict__.items():
            if attr in seen or not callable(value) or not is_env_action(value):
                continue
            seen.add(attr)
            yield str(getattr(value, _ACTION_ATTR, attr)), value


@contextmanager
def action_root_scope() -> Iterator[None]:
    """Collect top-level action steps recorded while a turn runs."""
    token = _action_roots.set([])
    try:
        yield
    finally:
        _action_roots.reset(token)


def root_action_steps() -> list[ActionStep]:
    """Return action steps recorded in the current :func:`action_root_scope`."""
    return list(_action_roots.get() or [])


def instrument_action(action_name: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``func`` so nested ``@action`` calls become step children.

    Returns:
        The instrumented callable, or ``func`` if it is already wrapped.
    """
    if getattr(func, _INSTRUMENTED, False):
        return func

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        recorded = call_arguments(func, args, kwargs)
        started_at = datetime.now(timezone.utc)
        step = ActionStep(
            name=action_name,
            arguments=recorded,
            source="environment_native",
            started_at=started_at,
        )
        stack = list(_action_stack.get() or [])
        if stack:
            step.parent = stack[-1].name
            stack[-1].children.append(step)
        else:
            roots = list(_action_roots.get() or [])
            roots.append(step)
            _action_roots.set(roots)
        stack.append(step)
        token = _action_stack.set(stack)
        started = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            step.result = result
            step.observation = result
            step.latency_ms = (time.perf_counter() - started) * 1000
            step.ended_at = datetime.now(timezone.utc)
            return result
        except Exception as exc:
            step.error = str(exc)
            step.result = {"error": str(exc)}
            step.observation = step.result
            step.latency_ms = (time.perf_counter() - started) * 1000
            step.ended_at = datetime.now(timezone.utc)
            raise
        finally:
            _action_stack.reset(token)

    setattr(wrapper, _INSTRUMENTED, True)
    return wrapper


def call_arguments(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Map positional args onto parameter names for the trace.

    Returns:
        Combined keyword arguments including positional values by name.
    """
    recorded = dict(kwargs)
    if not args:
        return recorded
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return recorded
    names = [p.name for p in sig.parameters.values() if p.name not in {"self", "cls"}]
    for name, value in zip(names, args, strict=False):
        recorded.setdefault(name, value)
    return recorded


def function_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON-schema object from an action callable's signature.

    Returns:
        A JSON Schema object describing the callable's parameters.
    """
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    hints = getattr(fn, "__annotations__", {})
    for param in sig.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.name in {"self", "cls"}:
            continue
        ann = hints.get(param.name, str)
        properties[param.name] = _annotation_to_json_schema(ann)
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def make_action_def(name: str, source: Callable[..., Any]) -> Tool:
    """Build a chat :class:`~plural.types.Tool` from a Python callable.

    Returns:
        A tool definition the native path can send to a model.
    """
    return Tool(
        function=FunctionDefinition(
            name=name,
            description=(inspect.getdoc(source) or "").strip() or None,
            parameters=function_schema(source),
        )
    )


def _annotation_to_json_schema(ann: Any) -> dict[str, Any]:
    if ann is int:
        return {"type": "integer"}
    if ann is float:
        return {"type": "number"}
    if ann is bool:
        return {"type": "boolean"}
    if ann is str:
        return {"type": "string"}
    origin = getattr(ann, "__origin__", None)
    if origin is list:
        return {"type": "array"}
    if origin is dict:
        return {"type": "object"}
    return {"type": "string"}
