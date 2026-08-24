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
        expected: Optional expected output / label used by scorers.
        metadata: Arbitrary task metadata (include ``seed`` for determinism).
    """

    task_id: str
    input: Any
    expected: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)


TaskFn = Callable[[], Iterable[TaskData]]
