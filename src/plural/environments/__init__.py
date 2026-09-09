"""Environments: RL-style harnesses that generate scored traces.

Subclass :class:`Environment` for a versioned simulator (tools, observations,
scorers). Its output is the same :class:`~plural.tracing.schema.Trace` used
for production traffic.

Examples:
    >>> from plural.environments import Environment, TaskData
    >>> env = Environment(name="demo", version="0.1.0")
    >>> env.name
    'demo'
"""

from __future__ import annotations

from plural.environments.action import (
    TEXT_ACTION,
    ActionResult,
    is_text_action,
    is_tool_action,
    normalize_action,
)
from plural.environments.dataset import Dataset, TaskDataset, TraceDataset, TraceFilter
from plural.environments.env import Environment
from plural.environments.policy import PluralPolicy, Policy, ScriptedPolicy
from plural.environments.replay import (
    ReplayMismatch,
    ReplayResult,
    replay_actions,
    verify_replay,
)
from plural.environments.rollout import Rollout
from plural.environments.runtime import LocalRuntime, Runtime
from plural.environments.step import StepResult
from plural.environments.stop import EpisodeError, EpisodeState, StopReason, is_stopped
from plural.environments.task import TaskData
from plural.environments.tool import tool
from plural.environments.types import Observation, State, hidden

__all__ = [
    "ActionResult",
    "Dataset",
    "PluralPolicy",
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
    "hidden",
    "is_text_action",
    "is_stopped",
    "is_tool_action",
    "normalize_action",
    "replay_actions",
    "tool",
    "verify_replay",
]
