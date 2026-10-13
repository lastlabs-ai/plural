"""Environments compose Apps; Trace datasets collect what happened in them."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from plural.apps.definition import AppAction, AppDefinition
from plural.environments.action_registry import action
from plural.environments.dataset import TraceDataset, TraceFilter
from plural.environments.definition import (
    EnvironmentDefinition,
    EnvironmentIdentity,
    EnvironmentResource,
    EnvironmentRuntime,
    ExecutionLimits,
    Guardrail,
    HarnessGrant,
    HarnessPolicy,
    Party,
    Resource,
    Runtime,
    RuntimePackages,
    RuntimeVariable,
    Secret,
    SecretReference,
)
from plural.environments.types import Observation, State, initial

if TYPE_CHECKING:
    from plural.environments.env import ActionCall, Environment

# Loaded on first use: Environment depends on App, whose module imports the
# helpers in this package.
_LAZY = {
    "ActionCall": "plural.environments.env",
    "Environment": "plural.environments.env",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'plural.environments' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)


__all__ = [
    "ActionCall",
    "AppAction",
    "AppDefinition",
    "Environment",
    "EnvironmentIdentity",
    "EnvironmentDefinition",
    "EnvironmentResource",
    "EnvironmentRuntime",
    "ExecutionLimits",
    "Party",
    "Guardrail",
    "HarnessPolicy",
    "HarnessGrant",
    "Observation",
    "Resource",
    "Runtime",
    "RuntimePackages",
    "RuntimeVariable",
    "Secret",
    "SecretReference",
    "State",
    "TraceDataset",
    "TraceFilter",
    "action",
    "initial",
]
