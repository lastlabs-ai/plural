"""Scored result of one environment episode.

Examples:
    >>> from enroute.environments.rollout import Rollout
    >>> from enroute.environments.task import TaskData
    >>> from enroute.tracing.schema import Trace
    >>> r = Rollout(task=TaskData(task_id="t", input="go"), trace=Trace())
    >>> r.task.task_id
    't'
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from enroute.environments.task import TaskData
from enroute.tracing.schema import Trace
from enroute.types import ChatResponse, Message


class Rollout(BaseModel):
    """Result of running one task through an environment.

    Attributes:
        task: The task that was run.
        trace: Scored episode trace produced by the rollout.
        messages: Final conversation messages.
        response: Final model response, if any.
        env: Environment instance after the episode.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task: TaskData
    trace: Trace
    messages: list[Message] = Field(default_factory=list)
    response: ChatResponse | None = None
    env: Any = None


ScorerFn = Callable[[Rollout], float]
