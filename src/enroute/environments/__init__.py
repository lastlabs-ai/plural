"""Environments: RL-style harnesses that generate scored traces.

Subclass :class:`Environment` for a versioned simulator (tools, observations,
scorers). Its output is the same :class:`~enroute.tracing.schema.Trace` used
for production traffic.

Examples:
    >>> from enroute.environments import Environment, TaskData
    >>> env = Environment(name="demo", version="0.1.0")
    >>> env.name
    'demo'
"""

from __future__ import annotations

from enroute.environments.action import (
    TEXT_ACTION,
    ActionResult,
    is_text_action,
    is_tool_action,
    normalize_action,
)
from enroute.environments.dataset import Dataset, TaskDataset, TraceDataset, TraceFilter
from enroute.environments.env import Environment
from enroute.environments.policy import EnroutePolicy, Policy, ScriptedPolicy
from enroute.environments.replay import (
    ReplayMismatch,
    ReplayResult,
    replay_actions,
    verify_replay,
)
from enroute.environments.rollout import Rollout
from enroute.environments.runtime import LocalRuntime, Runtime
from enroute.environments.step import StepResult
from enroute.environments.stop import EpisodeError, EpisodeState, StopReason, is_stopped
from enroute.environments.task import TaskData
from enroute.environments.tool import tool
from enroute.environments.types import Observation, State

__all__ = [
    "ActionResult",
    "Dataset",
    "EnroutePolicy",
    "Environment",
    "EpisodeError",
    "EpisodeState",
    "LocalRuntime",
    "Observation",
    "Policy",
    "ReplayMismatch",
    "ReplayResult",
    "Rollout",
    "Runtime",
    "ScriptedPolicy",
    "State",
    "StepResult",
    "StopReason",
    "TEXT_ACTION",
    "TaskData",
    "TaskDataset",
    "TraceDataset",
    "TraceFilter",
    "is_text_action",
    "is_stopped",
    "is_tool_action",
    "normalize_action",
    "replay_actions",
    "tool",
    "verify_replay",
]
