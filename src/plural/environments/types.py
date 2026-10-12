"""Typed agent-visible Observation and internal State models."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, Field

# JSON Schema flag: a Task may supply this State field as initial_state.
INITIAL_STATE_KEY = "x-plural-initial"


class Observation(BaseModel):
    """What the agent can observe after an action.

    This is the only Environment surface sent to the Agent. Internal State is
    never copied here automatically.

    Subclass this with typed fields. The JSON Schema of the subclass is the
    observation contract hosted with the environment. Implement :meth:`render`
    when the prompt should not be a raw dump of the fields.

    Attributes:
        text: Default rendered view. Structured subclasses may ignore this.
        metadata: Extra visible fields that do not need a typed attribute.
    """

    text: str = Field(
        default="",
        description="Default rendered view. Structured subclasses may ignore this.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra visible fields that do not need a typed attribute.",
    )

    def render(self) -> str:
        """Return the string the policy sees in the conversation.

        Returns:
            ``text``, or a subclass-specific prompt string.
        """
        return self.text

    def __str__(self) -> str:
        """Return :meth:`render` so tests and logs can print an observation."""
        return self.render()


# Author-facing names for limits a Task must meet. These are stored on the
# JSON Schema and checked when initial state is saved. They do not reject the
# Environment's own default, which may be blank until a Task supplies a value.
_INITIAL_CONSTRAINTS = {
    "min_length": "minLength",
    "max_length": "maxLength",
    "pattern": "pattern",
    "minimum": "minimum",
    "maximum": "maximum",
    "exclusive_minimum": "exclusiveMinimum",
    "exclusive_maximum": "exclusiveMaximum",
    "multiple_of": "multipleOf",
    "min_items": "minItems",
    "max_items": "maxItems",
    "enum": "enum",
}


def initial(
    default: Any = ...,
    *,
    default_factory: Any = None,
    description: str | None = None,
    **constraints: Any,
) -> Any:
    """Mark a State field as a value a Task may set before the episode starts.

    Episode progress, such as whether the case is solved or which guesses have
    been made, stays a normal field. The Environment owns those values.
    ``State.seed`` is settable. ``State.metadata`` is not.

    Constraints are requirements on the value a Task saves. For example,
    ``min_length=5``, ``max_length=5``, and ``pattern=r"^[a-z]{5}$"`` require
    a five-letter word. They are stored on the field's JSON Schema.

    Args:
        default: Value used when the Task leaves the field blank.
        default_factory: Factory used when the default is mutable.
        description: Shown next to the field when a Task sets initial state.
        **constraints: Limits such as ``min_length``, ``max_length``,
            ``pattern``, ``minimum``, ``maximum``, or ``enum``.

    Returns:
        A Pydantic field whose JSON Schema includes ``x-plural-initial``.
    """
    extra: dict[str, Any] = {INITIAL_STATE_KEY: True}
    for name, value in constraints.items():
        key = _INITIAL_CONSTRAINTS.get(name)
        if key is None:
            known = ", ".join(sorted(_INITIAL_CONSTRAINTS))
            raise TypeError(f"initial() has no constraint {name!r}. Use one of: {known}.")
        extra[key] = value
    kwargs: dict[str, Any] = {"json_schema_extra": extra}
    if description is not None:
        kwargs["description"] = description
    if default_factory is not None:
        return Field(default_factory=default_factory, **kwargs)
    if default is ...:
        return Field(**kwargs)
    return Field(default, **kwargs)


class State(BaseModel):
    """Persistent internal Environment state for the episode.

    State is never sent to the Agent. Only :class:`Observation` is visible.
    Verifiers receive the final State on :class:`~plural.verifiers.Episode`.

    Mark a field with :func:`initial` when a Task should supply it. Unmarked
    fields are episode progress and cannot be set as ``initial_state``.

    Attributes:
        seed: Optional deterministic seed a Task may set.
        metadata: Extra internal fields that do not need a typed attribute.
    """

    seed: int | None = initial(
        None,
        description="Optional RNG seed from the task.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra internal fields that do not need a typed attribute.",
    )


ObsT = TypeVar("ObsT", bound=Observation)
StateT = TypeVar("StateT", bound=State)


def is_empty_observation(value: Any) -> bool:
    """Return whether ``value`` has nothing for the policy to read.

    Args:
        value: Observation or fallback payload.

    Returns:
        ``True`` when there is no rendered text.
    """
    if value is None or value == "":
        return True
    if isinstance(value, Observation):
        return not value.render()
    return False


def serialize_observation(value: Any) -> Any:
    """Dump an observation onto a decision (dict if it is a model).

    Args:
        value: Observation or other payload.

    Returns:
        A JSON-ready value for ``Turn.observation``.
    """
    if isinstance(value, Observation):
        return value.model_dump()
    return value


def as_text(value: Any) -> str:
    """Render an observation or fallback value as conversation text.

    Args:
        value: Observation, string, or dumpable object.

    Returns:
        Text for a user message.
    """
    if isinstance(value, Observation):
        return value.render()
    if isinstance(value, str):
        return value
    render = getattr(value, "render", None)
    if callable(render):
        return str(render())
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump())
    return json.dumps(value)
