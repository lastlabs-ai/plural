"""Changes a diagnostic fork makes at the fork point.

A fork changes the Agent. To find a cause, it may instead change one thing the
Agent sees at step *k*, with ``plural trial fork --change NAME --payload JSON``.
Such a fork is **diagnostic**: it explains a failure, and is never shipped.

Each change is a function registered with :func:`change`. It edits a
:class:`ForkPoint`, the Job's copy of what the forked Agent will be given:

.. code-block:: python

    from plural.changes import ForkPoint, change


    @change("hide_prices")
    def hide_prices(point: ForkPoint) -> None:
        point.rendered = point.rendered.replace("$", "")

A project registers its own in any module its ``plural.yaml`` loads.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ChangeFunction = Callable[["ForkPoint"], None]


@dataclass
class ForkPoint:
    """What a change may alter at the fork point, before the forked Agent starts.

    Attributes:
        payload: The ``--payload`` the change was given.
        messages: The forked seat's conversation up to step *k*.
        observation: Observation *k*, which the Agent's reset returns.
        rendered: Observation *k* as text.
        environment: The Environment as the Harness is told it: actions and
            their descriptions.
        note: A message added after the history.
        forced: Actions the App host runs first, as the Agent's next actions.
        oracles: Added tools, by name, with the App and the path in its State
            each one answers from.
        fresh: Whether the Agent starts with no history at all.
        compactions: Each compaction of the Agent's context before step *k*,
            with the instructions and Task it started from.
    """

    payload: dict[str, Any]
    messages: list[dict[str, Any]]
    observation: Any
    rendered: str
    environment: dict[str, Any]
    note: str = ""
    forced: list[dict[str, Any]] = field(default_factory=list)
    oracles: dict[str, dict[str, str]] = field(default_factory=dict)
    fresh: bool = False
    compactions: list[dict[str, Any]] = field(default_factory=list)

    def text(self, key: str) -> str:
        """A required, non-empty string from the payload.

        Returns:
            The string.

        Raises:
            ValueError: When the payload has no such string.
        """
        value = self.payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"needs a non-empty {key!r} in --payload")
        return value

    def action(self, name: str) -> dict[str, Any]:
        """An Environment action the Harness is told about.

        Returns:
            The action's entry, which the change may edit.

        Raises:
            ValueError: When the Environment has no such action.
        """
        for item in self.environment.get("actions") or ():
            if isinstance(item, dict) and item.get("name") == name:
                return item
        known = ", ".join(str(item.get("name")) for item in self.environment.get("actions") or ())
        raise ValueError(
            f"the Environment has no action {name!r} (it has {known or 'none'}). A Harness's "
            "own tools are its vendor's, and can't be changed."
        )


_CHANGES: dict[str, ChangeFunction] = {}


def change(name: str) -> Callable[[ChangeFunction], ChangeFunction]:
    """Register a change a diagnostic fork can make, under ``name``.

    Returns:
        A decorator that registers the function and returns it unchanged.

    Raises:
        ValueError: When another change already has the name.
    """

    def register(function: ChangeFunction) -> ChangeFunction:
        if name in _CHANGES and _CHANGES[name] is not function:
            raise ValueError(f"a change named {name!r} is already registered")
        _CHANGES[name] = function
        return function

    return register


def registered() -> tuple[str, ...]:
    """Every change's name, sorted.

    Returns:
        The names.
    """
    return tuple(sorted(_CHANGES))


def apply_change(name: str, point: ForkPoint) -> ForkPoint:
    """Make change ``name`` at a fork point.

    Returns:
        The same point, changed.

    Raises:
        ValueError: When no change has the name, or its payload doesn't fit.
    """
    function = _CHANGES.get(name)
    if function is None:
        raise ValueError(
            f"no change named {name!r}; the registered ones are {', '.join(registered())}"
        )
    try:
        function(point)
    except ValueError as exc:
        raise ValueError(f"change {name!r} {exc}") from None
    return point


@change("observation")
def _observation(point: ForkPoint) -> None:
    """Replace observation *k* with ``{"text": ...}``."""
    text = point.text("text")
    point.observation = {"text": text}
    point.rendered = text
    for message in reversed(point.messages):
        if message.get("role") == "tool":
            message["content"] = text
            break


@change("message")
def _message(point: ForkPoint) -> None:
    """Add a message after the history: ``{"text": ...}``."""
    point.note = point.text("text")


@change("action")
def _action(point: ForkPoint) -> None:
    """Run one action first, as the Agent's next: ``{"action": ..., "arguments": {...}}``."""
    name = point.text("action")
    point.action(name)
    arguments = point.payload.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("needs 'arguments' to be an object")
    point.forced.append({"action": name, "arguments": arguments})


@change("tool_description")
def _tool_description(point: ForkPoint) -> None:
    """Describe one action differently: ``{"tool": ..., "description": ...}``."""
    point.action(point.text("tool"))["description"] = point.text("description")


@change("context")
def _context(point: ForkPoint) -> None:
    """Cut the history: ``trim``, ``summarize``, or ``fresh``; or ``restore`` it.

    ``{"mode": "trim", "keep": 4}`` keeps the last messages; ``summarize`` needs a
    ``"summary"`` you write. ``restore`` puts back the Task's own messages, which
    a compaction of the Agent's context dropped before the fork point, so a fork
    shows whether losing them caused the failure.
    """
    mode = point.payload.get("mode")
    if mode == "restore":
        if not point.compactions:
            raise ValueError("found no compaction before the fork point to undo")
        opening = [dict(item) for item in point.compactions[0].get("opening") or ()]
        missing = [item for item in opening if item not in point.messages]
        if not missing:
            raise ValueError("found the Task's messages still in the context; nothing to restore")
        system = [item for item in missing if item.get("role") == "system"]
        rest = [item for item in missing if item.get("role") != "system"]
        head = 1 if point.messages and point.messages[0].get("role") == "system" else 0
        point.messages = [
            *system,
            *point.messages[:head],
            *rest,
            *point.messages[head:],
        ]
    elif mode == "fresh":
        point.messages = []
        point.fresh = True
    elif mode == "trim":
        keep = point.payload.get("keep", 4)
        if not isinstance(keep, int) or keep < 1:
            raise ValueError("needs 'keep' to be a positive whole number")
        kept = point.messages[-keep:]
        # A tool result is never left without the call it answers.
        while kept and kept[0].get("role") == "tool":
            kept = kept[1:]
        point.messages = kept
    elif mode == "summarize":
        point.messages = [
            {"role": "user", "content": f"What happened so far:\n{point.text('summary')}"}
        ]
    else:
        raise ValueError("needs 'mode' to be trim, summarize, fresh, or restore")


@change("oracle_tool")
def _oracle_tool(point: ForkPoint) -> None:
    """Add one tool that returns a fact from App State: ``{"name", "description", "path"}``.

    ``path`` names one value in the App's State, with ``.`` between keys and
    list indexes, such as ``quote.unit_price``. ``app`` names the App when the
    Environment has several. The App host reads the value when the Agent calls
    the tool, and only that value reaches the Agent, in this diagnostic fork.
    """
    name = point.text("name")
    path = point.text("path")
    apps = sorted(
        {
            str(item["app"])
            for item in point.environment.get("actions") or ()
            if isinstance(item, dict) and item.get("app")
        }
    )
    app = point.payload.get("app")
    if app is None and len(apps) == 1:
        app = apps[0]
    if not isinstance(app, str) or app not in apps:
        raise ValueError(f"needs 'app' to be one of the Environment's Apps: {', '.join(apps)}")
    if any(item.get("name") == name for item in point.environment.get("actions") or ()):
        raise ValueError(f"can't add {name!r}: the Environment already has an action by that name")
    from plural.execution.apps import HOST_COMMAND

    point.environment.setdefault("actions", []).append(
        {
            "name": name,
            "app": None,
            "description": point.text("description"),
            "parameters": {"type": "object", "properties": {}},
            "mutates_state": False,
            "timeout_seconds": None,
            "command": [*HOST_COMMAND, "oracle", name],
        }
    )
    point.oracles[name] = {"app": app, "path": path}


__all__ = ["ChangeFunction", "ForkPoint", "apply_change", "change", "registered"]
