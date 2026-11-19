"""How an Agent describes the Environment's tools to its model.

An Agent's ``tool_overrides`` field rewrites, by tool name, how an action is
described to the model, or hides it. The Environment and its Apps are not
changed: the override is part of the Agent, so it is versioned with the Agent
and a fix to it is a new Agent revision.

.. code-block:: yaml

    tool_overrides:
      check_schedule:
        description: Required before promising any delivery date.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field, model_validator

from plural.common import FrozenModel


class ToolOverride(FrozenModel):
    """How one tool is described to the model.

    Attributes:
        description: The description the model reads instead of the action's own.
        hidden: Leave the tool out of what the model is offered.
    """

    description: str | None = Field(default=None, min_length=1)
    hidden: bool = False

    @model_validator(mode="after")
    def _one_change(self) -> ToolOverride:
        if self.hidden and self.description is not None:
            raise ValueError("a hidden tool has no description; set one or the other")
        if not self.hidden and self.description is None:
            raise ValueError("a tool override needs a description, or hidden: true")
        return self


def tool_override_map(value: Any) -> Any:
    """Accept a bare string as a description override.

    Returns:
        The value, with each string turned into ``{"description": ...}``.
    """
    if isinstance(value, Mapping):
        return {
            key: {"description": item} if isinstance(item, str) else item
            for key, item in value.items()
        }
    return value


def apply_tool_overrides(
    actions: Sequence[Mapping[str, Any]], overrides: Mapping[str, ToolOverride]
) -> list[dict[str, Any]]:
    """The actions as the model is told them, after an Agent's overrides.

    Returns:
        New action entries: hidden ones left out, overridden descriptions replaced.

    Examples:
        >>> apply_tool_overrides(
        ...     [{"name": "a", "description": "old"}, {"name": "b"}],
        ...     {"a": ToolOverride(description="new"), "b": ToolOverride(hidden=True)},
        ... )
        [{'name': 'a', 'description': 'new'}]
    """
    told: list[dict[str, Any]] = []
    for action in actions:
        override = overrides.get(str(action.get("name")))
        if override is not None and override.hidden:
            continue
        entry = dict(action)
        if override is not None and override.description is not None:
            entry["description"] = override.description
        told.append(entry)
    return told


__all__ = ["ToolOverride", "apply_tool_overrides", "tool_override_map"]
