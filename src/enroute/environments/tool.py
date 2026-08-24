"""``@tool`` decorator and JSON-schema helpers for environment methods.

Examples:
    >>> from enroute.environments.tool import tool
    >>> @tool
    ... def ping() -> str:
    ...     '''Health check.'''
    ...     return "pong"
    >>> ping.__enroute_tool__
    'ping'
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from enroute.tracing.schema import ToolCallStep
from enroute.types import FunctionDefinition, Tool

_TOOL_ATTR = "__enroute_tool__"
_INSTRUMENTED = "_enroute_instrumented"
_tool_stack: ContextVar[list[ToolCallStep] | None] = ContextVar("enroute_tool_stack", default=None)
_tool_roots: ContextVar[list[ToolCallStep] | None] = ContextVar("enroute_tool_roots", default=None)


def tool(fn: Callable[..., Any] | None = None, *, name: str | None = None) -> Any:
    """Mark an :class:`~enroute.environments.env.Environment` method as a tool.

    Args:
        fn: Method to register (decorator usage).
        name: Optional explicit tool name. Defaults to the method name.

    Returns:
        The original method (decorator) or a decorator.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, _TOOL_ATTR, name or func.__name__)
        return func

    if fn is not None:
        return decorator(fn)
    return decorator


def is_env_tool(fn: Callable[..., Any]) -> bool:
    """Return whether ``fn`` was decorated with :func:`tool`.

    Args:
        fn: Callable to inspect.

    Returns:
        ``True`` if ``@tool`` marked the function.
    """
    return hasattr(fn, _TOOL_ATTR)


def iter_env_tools(env_cls: type) -> Iterable[tuple[str, Callable[..., Any]]]:
    """Yield ``(tool_name, unbound_method)`` from an environment class MRO.

    Args:
        env_cls: Environment class (not instance).

    Yields:
        Tool name and the unbound method that carries ``@tool``.
    """
    seen: set[str] = set()
    for cls in env_cls.__mro__:
        for attr, value in cls.__dict__.items():
            if attr in seen or not callable(value) or not is_env_tool(value):
                continue
            seen.add(attr)
            yield str(getattr(value, _TOOL_ATTR, attr)), value


@contextmanager
def tool_root_scope() -> Iterator[None]:
    """Collect top-level tool steps recorded while a decision runs."""
    token = _tool_roots.set([])
    try:
        yield
    finally:
        _tool_roots.reset(token)


def root_tool_steps() -> list[ToolCallStep]:
    """Return tool steps recorded in the current :func:`tool_root_scope`.

    Returns:
        Top-level tool steps for the open decision, or an empty list.
    """
    return list(_tool_roots.get() or [])


def instrument_tool(tool_name: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``func`` so nested ``@tool`` calls become ``ToolCallStep`` children.

    Args:
        tool_name: Registered tool name.
        func: Bound or unbound callable to wrap.

    Returns:
        The instrumented callable (idempotent).
    """
    if getattr(func, _INSTRUMENTED, False):
        return func

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        recorded = call_arguments(func, args, kwargs)
        step = ToolCallStep(name=tool_name, arguments=recorded)
        stack = list(_tool_stack.get() or [])
        if stack:
            step.parent = stack[-1].name
            stack[-1].children.append(step)
        else:
            roots = list(_tool_roots.get() or [])
            roots.append(step)
            _tool_roots.set(roots)
        stack.append(step)
        token = _tool_stack.set(stack)
        started = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            step.result = result
            step.latency_ms = (time.perf_counter() - started) * 1000
            return result
        except Exception as exc:
            step.error = str(exc)
            step.result = {"error": str(exc)}
            step.latency_ms = (time.perf_counter() - started) * 1000
            raise
        finally:
            _tool_stack.reset(token)

    setattr(wrapper, _INSTRUMENTED, True)
    return wrapper


def call_arguments(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Map positional args onto parameter names for the trace.

    Args:
        func: Callable whose signature is used.
        args: Positional arguments from the call.
        kwargs: Keyword arguments from the call.

    Returns:
        A flat argument dict for ``ToolCallStep.arguments``.
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
    """Build a JSON-schema object from a tool callable's signature.

    Args:
        fn: Tool callable.

    Returns:
        A JSON Schema object for the function parameters.
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


def make_tool_def(name: str, source: Callable[..., Any]) -> Tool:
    """Build a chat :class:`~enroute.types.Tool` from a Python callable.

    Args:
        name: Tool name exposed to the model.
        source: Callable whose docstring and signature become the schema.

    Returns:
        A :class:`~enroute.types.Tool` definition.
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
