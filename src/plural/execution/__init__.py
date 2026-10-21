"""Durable local Job and Trial runtime APIs."""

from typing import Any

from plural._deprecation import module_getattr
from plural.execution.engine import ExecutionFailure, JobRunner, TrialRunner, VerifierOutput
from plural.execution.policy import (
    EffectivePolicy,
    PolicyDenial,
    ProjectPolicy,
    resolve_effective_policy,
)
from plural.execution.store import JobStore, redact_mapping

__all__ = [
    "EffectivePolicy",
    "ExecutionFailure",
    "JobRunner",
    "JobStore",
    "PolicyDenial",
    "ProjectPolicy",
    "TrialRunner",
    "VerifierOutput",
    "redact_mapping",
    "resolve_effective_policy",
]

_renamed = module_getattr("plural.execution", {"Trial": ("TrialRunner", lambda: TrialRunner)})


def __getattr__(name: str) -> Any:
    return _renamed(name)
