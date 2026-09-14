"""Typed agent-visible Observation and internal State models."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, Field


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


class State(BaseModel):
    """Persistent internal Environment state for the episode.

    State is never sent to the Agent. Only :class:`Observation` is visible.
    Verifiers receive the final State on :class:`~plural.verifiers.Episode`.

    Attributes:
        seed: Optional deterministic seed.
        metadata: Extra internal fields that do not need a typed attribute.
    """

    seed: int | None = Field(
        default=None,
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
