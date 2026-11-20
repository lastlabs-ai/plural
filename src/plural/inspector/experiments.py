"""The Inspector's experiments: forks that test a cause.

A fork continues the failed Trial after a step with the Agent changed (the
remedy the Inspector would ship), beside controls that rerun the original
Agent from the same point. A diagnostic fork changes what the Agent sees
instead, with a registered change. Either way the verdict is the paired
comparison :func:`plural.stats.compare_fork` computes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from plural.agents import AgentBinding
from plural.inspector.evidence import trial_passed
from plural.inspector.findings import ForkTest, Remedy
from plural.jobs import TrialResult
from plural.project.forks import ForkRequest, fork_local_trial, fork_results, trial_source
from plural.project.layout import Project
from plural.project.resources import Workspace
from plural.stats import ForkComparison

FORK_CONCURRENCY = 4
"""How many forks of one test run at once."""


def remedy_agent(binding: AgentBinding, remedy: Remedy, label: str) -> AgentBinding:
    """The original Agent with a remedy applied, under a name that says so.

    Returns:
        The candidate Agent.
    """
    agent = binding.agent
    overrides = {**agent.tool_overrides, **remedy.tool_overrides}
    update: dict[str, Any] = {
        "name": f"{agent.name}-{label.lower()}",
        "tool_overrides": overrides,
    }
    if remedy.instructions is not None:
        update["instructions"] = remedy.instructions
    if remedy.model is not None:
        update["model"] = remedy.model
    if remedy.harness_config:
        update["harness_config"] = {**agent.harness_config, **remedy.harness_config}
    if remedy.context is not None:
        update["context"] = remedy.context
    changed = type(agent).model_validate({**agent.model_dump(), **update})
    return AgentBinding(agent=changed)


def run_fork(
    project_root: Path,
    *,
    trial_id: str,
    step: int,
    remedy: Remedy | None,
    change: str | None,
    payload: Mapping[str, Any] | None,
    attempts: int,
    test_id: str,
    environ: Mapping[str, str],
    gates: Sequence[str] = (),
) -> ForkTest:
    """Run one fork test of a local Trial and compare the candidates with the controls.

    With ``gates``, each side is judged on those gates alone.

    Returns:
        The test and its verdict.
    """
    workspace = Workspace(Project.at(project_root))
    source = trial_source(workspace, trial_id)
    candidates = (remedy_agent(source.agent, remedy, test_id),) if remedy is not None else ()
    request = ForkRequest(
        trial_id=trial_id,
        step=step,
        attempts=attempts,
        change=change,
        payload=dict(payload) if payload is not None else None,
        candidates=candidates,
        concurrency=FORK_CONCURRENCY,
    )
    job_id, result, spec = fork_local_trial(workspace, request, environ=environ, source=source)
    outcome = fork_results(spec, result, source.passed, gates)
    comparison = next(iter(outcome["candidates"].values()), {"verdict": "too_few"})
    cost = sum(float(item.metrics.get("cost_usd") or 0.0) for item in result.trials)
    return ForkTest(
        test_id=test_id,
        job_id=job_id,
        step=step,
        remedy=remedy,
        change=change,
        payload=dict(payload) if payload is not None else None,
        gates=tuple(gates),
        verdict=ForkComparison.model_validate(comparison).verdict,
        candidate=_number(comparison.get("candidate")),
        control=_number(comparison.get("control")),
        low=_number(comparison.get("low")),
        high=_number(comparison.get("high")),
        candidates=int(comparison.get("candidates") or 0),
        controls=int(comparison.get("controls") or 0),
        controls_reproduced=outcome["controls_reproduced"],
        outcomes=_outcomes(result.trials),
        cost_usd=round(cost, 6),
    )


def _outcomes(trials: Sequence[TrialResult]) -> dict[str, dict[str, int]]:
    sides: dict[str, dict[str, int]] = {}
    for trial in trials:
        if trial.fork is None or trial.fork.role is None or trial.status != "succeeded":
            continue
        counts = sides.setdefault(trial.fork.role, {"passed": 0})
        counts["passed"] += int(trial_passed(trial))
        for name, ok in trial.gates.items():
            if ok is False:
                counts[name] = counts.get(name, 0) + 1
    return sides


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


__all__ = ["FORK_CONCURRENCY", "remedy_agent", "run_fork"]
