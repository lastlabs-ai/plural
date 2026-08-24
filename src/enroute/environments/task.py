"""Seed data for one environment episode.

Examples:
    >>> from enroute.environments.task import TaskData
    >>> TaskData(task_id="t1", input="play").task_id
    't1'
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, Field


class TaskData(BaseModel):
    """Seed data for a single task instance.

    Attributes:
        task_id: Stable task identifier.
        input: Primary input payload (often a user message or structured case).
        expected: Optional evaluator-only output or label used by scorers. It
            may be sensitive and is never included in episode trace metadata.
        metadata: Arbitrary task metadata (include ``seed`` for determinism).
    """

    task_id: str
    input: Any
    expected: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def trace_payload(self) -> dict[str, Any]:
        """Return task fields safe for episode trace metadata.

        Returns:
            Task id, input, and metadata. The scorer-only ``expected`` value
            is intentionally excluded.
        """
        return {
            "task_id": self.task_id,
            "input": self.input,
            "metadata": self.metadata,
        }


TaskFn = Callable[[], Iterable[TaskData]]
