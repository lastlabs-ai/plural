"""``@action`` decorator and JSON-schema helpers for App methods.

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

import inspect
from collections.abc import Callable, Iterable
from typing import Any, get_type_hints

from pydantic import TypeAdapter

_ACTION_ATTR = "__plural_action__"
_ACTION_OPTIONS = "__plural_action_options__"


def action(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    read_only: bool = False,
    timeout_seconds: float = 30,
) -> Any:
    """Mark an :class:`~plural.apps.App` method as an action the Agent can take.

    Args:
        fn: Method to register (decorator usage).
        name: Optional explicit action name. Defaults to the method name.
        read_only: The action never changes state. Verifiers may call only
            read-only actions after the episode.
        timeout_seconds: How long one call may run.

    Returns:
        The original method (decorator) or a decorator.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, _ACTION_ATTR, name or func.__name__)
        setattr(
            func,
            _ACTION_OPTIONS,
            {"read_only": read_only, "timeout_seconds": float(timeout_seconds)},
        )
        return func

    if fn is not None:
        return decorator(fn)
    return decorator


def is_env_action(fn: Callable[..., Any]) -> bool:
    """Return whether ``fn`` was decorated with :func:`action`."""
    return hasattr(fn, _ACTION_ATTR)


def action_options(fn: Callable[..., Any]) -> dict[str, Any]:
    """Return the ``read_only`` and ``timeout_seconds`` given to :func:`action`."""
    options = getattr(fn, _ACTION_OPTIONS, None)
    return dict(options) if isinstance(options, dict) else {}


def iter_env_actions(env_cls: type) -> Iterable[tuple[str, Callable[..., Any]]]:
    """Yield ``(action_name, unbound_method)`` from an App class MRO."""
    seen: set[str] = set()
    for cls in env_cls.__mro__:
        for attr, value in cls.__dict__.items():
            if attr in seen or not callable(value) or not is_env_action(value):
                continue
            seen.add(attr)
            yield str(getattr(value, _ACTION_ATTR, attr)), value


def function_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON-schema object from an action callable's signature.

    Constraints such as ``min_length`` and nested models are kept, so a
    five-letter word or a dictionary parameter stays visible to the model
    and to the Actions tab.

    Returns:
        A JSON Schema object describing the callable's parameters.
    """
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    defs: dict[str, Any] = {}
    for param in sig.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.name in {"self", "cls"}:
            continue
        ann = hints.get(param.name, param.annotation)
        if ann is inspect.Parameter.empty:
            ann = str
        properties[param.name] = _parameter_schema(ann, defs)
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    if defs:
        schema["$defs"] = defs
    return schema


def _parameter_schema(ann: Any, defs: dict[str, Any]) -> dict[str, Any]:
    """JSON Schema for one parameter, including constraints and nested models.

    Returns:
        The parameter schema. Nested ``$defs`` are copied into ``defs``.
    """
    try:
        schema = TypeAdapter(ann).json_schema()
    except Exception:
        return _annotation_to_json_schema(ann)
    nested = schema.pop("$defs", None)
    if isinstance(nested, dict):
        defs.update(nested)
    return schema


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
