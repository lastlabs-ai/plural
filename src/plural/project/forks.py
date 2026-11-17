"""Checkpoints of local Trials, and the fork Jobs that continue them.

``plural trial checkpoint`` names the moment after one step of a finished
Trial. ``plural trial fork`` continues a Trial from such a moment with other
Agents, beside controls that rerun the original Agent from the same point.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plural.agents import AgentBinding
from plural.apps.workspace import BUNDLE_FILE
from plural.checkpoints import (
    Checkpoint,
    build_checkpoint,
    checkpoint_path,
    load_checkpoint,
    save_checkpoint,
)
from plural.jobs import (
    BenchmarkJobSource,
    ForkChange,
    ForkSpec,
    JobResult,
    JobSpec,
    TaskJobSource,
    TrialResult,
    TrialSpec,
)
from plural.project.layout import ProjectError, ResourceRef
from plural.project.resources import Workspace
from plural.project.runs import (
    RUN_RECORD,
    RunRecord,
    RunRequest,
    Tracking,
    _agent,
    _execute,
    _load_local,
    _now,
    find_local_trial,
    pinned_inputs,
)
from plural.stats import ForkComparison, compare_fork, seed_for
from plural.studio import Studio
from plural.tasks import TaskDefinition


@dataclass(frozen=True)
class TrialSource:
    """A local Trial a checkpoint is taken from."""

    job_id: str
    directory: Path
    spec: JobSpec
    trial: TrialSpec
    task: TaskDefinition
    agent: AgentBinding
    result: TrialResult | None

    @property
    def artifacts(self) -> Path:
        """The artifacts of the Trial's latest execution."""
        executions = sorted(
            (item for item in (self.directory / "executions").glob("*") if item.name.isdigit()),
            key=lambda item: int(item.name),
        )
        if not executions:
            raise ProjectError(f"Trial {self.trial.trial_id} has not finished an execution.")
        return executions[-1] / "artifacts"

    @property
    def heldout(self) -> bool:
        """Whether the Trial ran one of its Benchmark's held-out Tasks."""
        source = self.spec.source
        return isinstance(source, BenchmarkJobSource) and self.task.task_id in set(
            source.benchmark.heldout
        )


def local_trial_id(
    workspace: Workspace, trial_id: str, studio: Callable[[], Studio] | None = None
) -> str:
    """The local Trial ``trial_id`` names: itself, or the run a hosted Trial recorded.

    A hosted Trial is found among the local Jobs recorded as its Job, by its
    Task's name, its Agent's definition hash, and its attempt, the same match
    ``--record`` publishes by. ``studio`` is called only when no local Trial
    has the id.

    Returns:
        The local Trial id.

    Raises:
        ProjectError: When neither a local Trial nor a recorded hosted Trial matches.
    """
    try:
        find_local_trial(workspace, trial_id)
        return trial_id
    except ProjectError:
        if studio is None or trial_id.startswith("trl_"):
            raise
    hosted = studio().trials.get(trial_id)
    given = hosted.get("pins")
    pins: dict[str, Any] = given if isinstance(given, dict) else {}
    named = pins.get("task")
    task: dict[str, Any] = named if isinstance(named, dict) else {}
    task_name = str(task.get("name") or hosted.get("task_name") or "")
    agent_hash = str(pins.get("agent") or "")
    attempt = int(hosted.get("attempt") or 0)
    root = workspace.project.jobs_dir
    for directory in sorted(root.iterdir()) if root.is_dir() else ():
        record_path = directory / RUN_RECORD
        if not record_path.is_file():
            continue
        record = json.loads(record_path.read_text("utf-8"))
        if record.get("hosted_job_id") != hosted.get("job_id"):
            continue
        spec, _ = _load_local(workspace, directory.name)
        names = {item.content_hash: item.task_id for item in spec.tasks}
        bindings = {item.agent_id: item for item in spec.agents}
        for trial in spec.plan().trials:
            binding = bindings.get(trial.agent_id)
            if (
                binding is not None
                and trial.attempt == attempt
                and names.get(trial.task_digest) == task_name
                and binding.agent.content_hash == agent_hash
            ):
                return trial.trial_id
    raise ProjectError(
        f"Trial {trial_id} was not recorded from this project folder. Run the "
        "command in the folder whose Job recorded it, or name a local Trial."
    )


def trial_source(workspace: Workspace, trial_id: str) -> TrialSource:
    """Find a local Trial and what it ran.

    Returns:
        The Trial, its Job's specification, Task, Agent, and result.

    Raises:
        ProjectError: When there is no such local Trial.
    """
    job_id, directory = find_local_trial(workspace, trial_id)
    spec, _ = _load_local(workspace, job_id)
    trial = next((item for item in spec.plan().trials if item.trial_id == trial_id), None)
    if trial is None:
        raise ProjectError(f"Job {job_id} no longer plans Trial {trial_id}.")
    task = next(item for item in spec.tasks if item.content_hash == trial.task_digest)
    agent = next(item for item in spec.agents if item.agent_id == trial.agent_id)
    result_path = directory / "result.json"
    result = (
        TrialResult.model_validate_json(result_path.read_text("utf-8"))
        if result_path.is_file()
        else None
    )
    return TrialSource(job_id, directory, spec, trial, task, agent, result)


def trial_checkpoint(
    workspace: Workspace,
    trial_id: str,
    *,
    step: int | None = None,
    name: str | None = None,
) -> tuple[Checkpoint, Path | None]:
    """The checkpoint after ``step`` of a local Trial, or the one saved as ``name``.

    Returns:
        The checkpoint, and where its workspace snapshots are, if it has any.

    Raises:
        ProjectError: When neither or both of ``step`` and ``name`` are given, or
            the Trial has no such step or checkpoint.
    """
    if (step is None) == (name is None):
        raise ProjectError("Name exactly one of --step or --checkpoint.")
    source = trial_source(workspace, trial_id)
    if name is not None:
        try:
            path = checkpoint_path(source.directory, name)
        except ValueError as exc:
            raise ProjectError(str(exc)) from None
        if not path.is_file():
            raise ProjectError(
                f"Trial {trial_id} has no checkpoint {name!r}.\nNext: plural trial checkpoint "
                f"{trial_id} --step N --name {name}"
            )
        bundle = path.with_suffix(".bundle")
        return load_checkpoint(path), bundle if bundle.is_file() else None
    assert step is not None
    artifacts = source.artifacts
    try:
        checkpoint = build_checkpoint(
            artifacts,
            step,
            trial_id=trial_id,
            job_id=source.job_id,
            instructions=source.agent.agent.instructions,
            seats=tuple(item.seat for item in source.trial.seats),
            task_digest=source.task.content_hash,
            agent_digest=source.agent.content_hash,
            heldout=source.heldout,
        )
    except ValueError as exc:
        raise ProjectError(str(exc)) from None
    bundle = artifacts / BUNDLE_FILE
    return checkpoint, bundle if bundle.is_file() else None


def save_trial_checkpoint(workspace: Workspace, trial_id: str, *, step: int, name: str) -> Path:
    """Name the moment after ``step`` of a local Trial, so forks and Tasks can start there.

    The checkpoint is stored with the Trial, beside a copy of its workspace
    snapshots, so it outlives a change to the Trial's other files.

    Returns:
        The checkpoint's file.

    Raises:
        ProjectError: When the Trial has no such step, or the name is taken.
    """
    checkpoint, bundle = trial_checkpoint(workspace, trial_id, step=step)
    source = trial_source(workspace, trial_id)
    try:
        path = save_checkpoint(source.directory, checkpoint.model_copy(update={"name": name}))
    except ValueError as exc:
        raise ProjectError(str(exc)) from None
    if bundle is not None:
        shutil.copyfile(bundle, path.with_suffix(".bundle"))
    return path


def resolve_from_checkpoint(workspace: Workspace, reference: str) -> tuple[Checkpoint, Path | None]:
    """The saved checkpoint a Task's ``from_checkpoint: TRIAL/NAME`` names.

    Returns:
        The checkpoint, and where its workspace snapshots are.

    Raises:
        ProjectError: When the reference isn't ``TRIAL/NAME``, or names nothing.
    """
    trial_id, _, name = reference.partition("/")
    if not trial_id or not name:
        raise ProjectError(
            f"from_checkpoint {reference!r} must be TRIAL/NAME, a checkpoint saved with "
            "plural trial checkpoint TRIAL --step N --name NAME."
        )
    return trial_checkpoint(workspace, trial_id, name=name)


@dataclass(frozen=True)
class ForkRequest:
    """What ``plural trial fork`` asks for."""

    trial_id: str
    step: int | None = None
    checkpoint: str | None = None
    agents: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    harness: str | None = None
    attempts: int = 3
    seat: str | None = None
    change: str | None = None
    payload: Any = None
    hosted_trial_id: str | None = None
    """The original Trial's hosted id, so a recorded fork links to it."""


def hosted_trial_id(workspace: Workspace, studio: Studio, trial_id: str) -> str | None:
    """The hosted id of a local Trial its Job was recorded as, or ``None``.

    Returns:
        The hosted Trial id, matched on Task name, Agent definition hash, and attempt.
    """
    source = trial_source(workspace, trial_id)
    record = json.loads((source.directory.parent.parent / RUN_RECORD).read_text("utf-8"))
    hosted_job = record.get("hosted_job_id")
    if not hosted_job:
        return None
    for item in studio.jobs.trials(str(hosted_job)):
        given = item.get("pins")
        pins: dict[str, Any] = given if isinstance(given, dict) else {}
        named = pins.get("task")
        task: dict[str, Any] = named if isinstance(named, dict) else {}
        if (
            task.get("name") == source.task.task_id
            and pins.get("agent") == source.agent.agent.content_hash
            and int(item.get("attempt") or 0) == source.trial.attempt
        ):
            return str(item["id"])
    return None


def plan_fork(workspace: Workspace, request: ForkRequest) -> tuple[JobSpec, RunRecord]:
    """The fork Job for a request: each candidate's forks, then the controls.

    Returns:
        The Job's specification and its local run record.

    Raises:
        ProjectError: When the Trial can't be forked as asked.
    """
    source = trial_source(workspace, request.trial_id)
    checkpoint, bundle = trial_checkpoint(
        workspace, request.trial_id, step=request.step, name=request.checkpoint
    )
    if checkpoint.heldout:
        raise ProjectError(
            f"Trial {request.trial_id} ran a held-out Task, so it can't be forked: held-out "
            "Tasks are kept for confirming a fix."
        )
    problem = source.task.environment.fork_problem
    if problem:
        raise ProjectError(f"Trial {request.trial_id} can't be forked: {problem}.")
    candidates: list[AgentBinding] = []
    refs: list[ResourceRef] = []
    for name in request.agents:
        agent, agent_ref, harness_ref = _agent(workspace, RunRequest(agent=name))
        candidates.append(AgentBinding(agent=agent._definition()))
        refs += [ref for ref in (agent_ref, harness_ref) if ref is not None]
    for model in request.models:
        agent, agent_ref, harness_ref = _agent(
            workspace, RunRequest(model=model, harness=request.harness)
        )
        candidates.append(AgentBinding(agent=agent._definition()))
        refs += [ref for ref in (agent_ref, harness_ref) if ref is not None]
    change = (
        ForkChange(name=request.change, payload=request.payload)
        if request.change is not None
        else None
    )
    if not candidates:
        if change is None:
            raise ProjectError(
                "Name the Agent to fork into with --agent or --model, or change one thing "
                "at the fork point with --change."
            )
        candidates.append(source.agent)
    party = source.task.party is not None
    if party and request.seat is None:
        raise ProjectError(
            f"Trial {request.trial_id} is played by several Agents. Name the seat whose Agent "
            "the fork replaces with --seat."
        )
    if party:
        seats = [item.seat for item in source.trial.seats]
        if request.seat not in seats:
            raise ProjectError(
                f"Trial {request.trial_id} has seats {', '.join(seats)}; there is no "
                f"{request.seat!r}."
            )
        assignment = next(item for item in source.trial.seats if item.seat == request.seat)
        control = next(item for item in source.spec.agents if item.agent_id == assignment.agent_id)
    else:
        control = source.agent
    agents = {item.agent_id: item for item in (*source.spec.party_agents, control, *candidates)}
    fork = ForkSpec(
        trial_id=request.trial_id,
        job_id=source.job_id,
        checkpoint=checkpoint,
        control_agent_id=control.agent_id,
        candidate_agent_ids=tuple(dict.fromkeys(item.agent_id for item in candidates)),
        seat=request.seat,
        change=change,
        bundle=str(bundle) if bundle is not None else None,
        hosted_trial_id=request.hosted_trial_id,
    )
    try:
        spec = source.spec.model_copy(
            update={
                "source": TaskJobSource(task=source.task),
                "agents": tuple(agents.values()),
                "attempts": request.attempts,
                "run_id": uuid.uuid4().hex,
                "purpose": "fork",
                "fork": fork,
            }
        )
        # From the field values, so the Tasks keep the Verifier code they were loaded with.
        spec = JobSpec.model_validate({name: getattr(spec, name) for name in JobSpec.model_fields})
    except ValueError as exc:
        raise ProjectError(str(exc)) from None
    # The original Job's pins hold the Task and the control as they ran, so a
    # recorded fork Job is built from the same revisions.
    original = json.loads((source.directory.parent.parent / RUN_RECORD).read_text("utf-8"))
    inputs = {
        **{
            key: value
            for key, value in dict(original.get("inputs") or {}).items()
            if not key.startswith("benchmark/")
        },
        **pinned_inputs(workspace, workspace.dependency_order(refs)),
    }
    record = RunRecord(
        job_id=spec.job_id,
        created_at=_now(),
        source=f"task/{source.task.task_id}",
        inputs=inputs,
        agent=", ".join(item.name for item in candidates),
        model=candidates[0].model,
        harness=str(candidates[0].harness.name if candidates[0].harness else "native"),
        rerun_of_job_id=source.job_id,
        rerun_of_trial_id=request.trial_id,
    )
    return spec, record


def fork_local_trial(
    workspace: Workspace,
    request: ForkRequest,
    *,
    environ: Mapping[str, str],
    progress: Any = None,
    tracking: Tracking | None = None,
    credential_source: Any = None,
) -> tuple[str, JobResult, JobSpec]:
    """Run a fork Job on this machine.

    Returns:
        The fork Job's id, its result, and its specification.
    """
    spec, record = plan_fork(workspace, request)
    job_id, result = _execute(
        workspace,
        spec,
        record,
        environ=environ,
        progress=progress,
        tracking=tracking,
        credential_source=credential_source,
    )
    return job_id, result, spec


def fork_results(spec: JobSpec, result: JobResult, original: TrialResult | None) -> dict[str, Any]:
    """Each candidate against the controls, and how often the controls repeated the original.

    A Trial passes when its gates pass, or, with no gates, when its score is 1.

    Returns:
        ``candidates``: one :class:`~plural.stats.ForkComparison` per candidate
        Agent, by name; ``controls_reproduced``: the share of controls whose
        pass or fail matched the original Trial's; and each Trial's history and
        warnings.
    """
    fork = spec.fork
    assert fork is not None
    names = {item.agent_id: item.name for item in spec.agents}
    passed: dict[str, list[float]] = {}
    controls: list[float] = []
    histories: dict[str, int] = {}
    warnings: list[str] = []
    for trial in result.trials:
        record = trial.fork
        if record is None or trial.status != "succeeded":
            continue
        histories[record.history] = histories.get(record.history, 0) + 1
        warnings.extend(item for item in record.warnings if item not in warnings)
        outcome = float(_passed(trial))
        if record.role == "control":
            controls.append(outcome)
        else:
            agent_id = _trial_agent(spec, trial, fork.seat)
            passed.setdefault(agent_id, []).append(outcome)
    comparisons: dict[str, ForkComparison] = {
        names.get(agent_id, agent_id): compare_fork(
            values, controls, seed=seed_for(result.job_id, agent_id)
        )
        for agent_id, values in passed.items()
    }
    reproduced = None
    if original is not None and controls:
        before = float(_passed(original))
        reproduced = sum(1 for item in controls if item == before) / len(controls)
    return {
        "step": fork.step,
        "diagnostic": fork.diagnostic,
        "candidates": {key: value.model_dump(mode="json") for key, value in comparisons.items()},
        "summaries": {key: value.summary for key, value in comparisons.items()},
        "controls": len(controls),
        "controls_reproduced": reproduced,
        "original_passed": _passed(original) if original is not None else None,
        "history": histories,
        "warnings": warnings,
    }


def _passed(trial: TrialResult) -> bool:
    if trial.passed is not None:
        return bool(trial.passed)
    return trial.score is not None and trial.score >= 1.0


def _trial_agent(spec: JobSpec, trial: TrialResult, seat: str | None) -> str:
    """The Agent a fork Trial put in the forked seat, or its only Agent.

    Returns:
        The Agent's id.
    """
    if seat is not None:
        for item in trial.seats:
            if item.seat == seat:
                return str(item.agent_id)
    by_digest = {item.content_hash: item.agent_id for item in spec.agents}
    return by_digest.get(trial.receipt.agent_digest, trial.receipt.agent_digest)


__all__ = [
    "ForkRequest",
    "TrialSource",
    "fork_local_trial",
    "fork_results",
    "plan_fork",
    "resolve_from_checkpoint",
    "save_trial_checkpoint",
    "trial_checkpoint",
    "trial_source",
]
