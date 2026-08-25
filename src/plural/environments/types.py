"""Observation and State models for environments.

Subclass these on each environment. Reward and termination stay on
:class:`~plural.environments.step.StepResult`, not on the observation.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """What the agent is allowed to see.

    Authors subclass this and implement :meth:`render` when the prompt
    should not be a raw dump of the fields. :meth:`~plural.environments.env.Environment.reset`
    and :meth:`~plural.environments.env.Environment.step` call
    :meth:`~plural.environments.env.Environment.observe` internally —
    do not call ``observe`` to drive an agent.

    Attributes:
        text: Default rendered view. Structured subclasses may ignore this.
        metadata: Extra visible fields that do not need a typed attribute.
    """

    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

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
    """Internal episode state. May include hidden fields (secrets, labels).

    Attributes:
        seed: Optional RNG seed from the task.
        metadata: Extra internal fields that do not need a typed attribute.
    """

    seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
        A JSON-ready value for ``Decision.observation``.
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
