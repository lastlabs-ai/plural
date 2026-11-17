"""``@tool``: a tool a Harness offers the model and answers itself.

The model sees a Harness tool exactly as it sees an Environment action: it is
listed by :meth:`~plural.harness.interface.HarnessEnvironment.tools`, and a call
to it goes through :meth:`~plural.harness.interface.HarnessEnvironment.step`.
The tool is ordinary code, so the only decision the model makes is to call it.
Every Environment step the tool runs is recorded inside that call.

Examples:
    >>> from plural.harness.tools import tool
    >>> class Helper:
    ...     @tool
    ...     def best_option(self, environment, material: str) -> dict:
    ...         '''The cheapest way to ship one material.'''
    ...         return {"material": material}
    >>> Helper.best_option.__plural_tool__
    'best_option'
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from plural.environments.action_registry import function_schema

_TOOL_ATTR = "__plural_tool__"
_TOOL_OPTIONS = "__plural_tool_options__"


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    wraps: str | None = None,
) -> Any:
    """Mark a :class:`~plural.harness.models.Harness` method as a tool for the model.

    The method takes the Environment first, then the tool's parameters, which
    become its JSON schema the same way an App ``@action``'s do; its docstring is
    the description. What it returns is the result the model sees::

        @tool
        def find_sourcing_options(self, environment, material: str, tons: float) -> dict:
            '''Every way to fill one line, cheapest on-time first.'''
            stock = environment.step("get_stock", material=material).observation
            ...

    ``wraps`` names an Environment action the tool stands in for: the model sees
    that action, with its own schema and description, and the method receives the
    call's arguments. Inside, ``environment.step`` with the same name runs the real
    action, so a tool can check a call before letting it through.

    Args:
        fn: Method to register (decorator usage).
        name: The tool's name. Defaults to ``wraps`` or the method name.
        description: Overrides the docstring.
        wraps: The Environment action this tool stands in for.

    Returns:
        The original method (decorator) or a decorator.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, _TOOL_ATTR, name or wraps or func.__name__)
        setattr(func, _TOOL_OPTIONS, {"description": description, "wraps": wraps})
        return func

    if fn is not None:
        return decorator(fn)
    return decorator


@dataclass(frozen=True)
class HarnessTool:
    """One ``@tool`` method, bound to its Harness."""

    name: str
    run: Callable[..., Any]
    description: str
    parameters: dict[str, Any]
    wraps: str | None = None


def harness_tools(harness: object) -> Iterator[HarnessTool]:
    """Yield the ``@tool`` methods of a Harness instance, bound to it."""
    seen: set[str] = set()
    for cls in type(harness).__mro__:
        for attr, value in cls.__dict__.items():
            if attr in seen or not callable(value) or not hasattr(value, _TOOL_ATTR):
                continue
            seen.add(attr)
            options = dict(getattr(value, _TOOL_OPTIONS, None) or {})
            parameters = list(inspect.signature(value).parameters)
            injected = {parameters[1]} if len(parameters) > 1 else set()
            yield HarnessTool(
                name=str(getattr(value, _TOOL_ATTR)),
                run=getattr(harness, attr),
                description=str(options.get("description") or inspect.getdoc(value) or ""),
                parameters=function_schema(value, skip=injected),
                wraps=options.get("wraps"),
            )


__all__ = ["HarnessTool", "harness_tools", "tool"]
