"""Gymnasium-shaped result of one environment step.

Examples:
    >>> from plural.environments.step import StepResult
    >>> obs, reward, terminated, truncated, info = StepResult(reward=0.0)
    >>> reward
    0.0
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StepResult(BaseModel):
    """Gymnasium-shaped result of :meth:`~plural.environments.env.Environment.step`.

    Unpack as ``obs, reward, terminated, truncated, info``.

    Attributes:
        observation: Next observation from the environment.
        reward: Sum of this decision's step rewards (0 if none).
        terminated: ``True`` when :meth:`~plural.environments.env.Environment.done`
            reports a natural end.
        truncated: ``True`` when ``max_turns`` was hit.
        info: Extra diagnostics (stop reason, tool errors, …).
    """

    observation: Any = None
    reward: float = 0.0
    terminated: bool = False
    truncated: bool = False
    info: dict[str, Any] = Field(default_factory=dict)

    def __iter__(self) -> Any:
        """Yield Gymnasium tuple fields in order."""
        yield self.observation
        yield self.reward
        yield self.terminated
        yield self.truncated
        yield self.info
