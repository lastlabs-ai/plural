"""Running the Inspector: ``plural job inspect`` and ``plural trial ask``.

The Inspector is an ordinary Plural project (``plural/inspector/project``).
Inspecting a Job copies it into the inspected project's ``.plural/inspector``
folder, adds one Task per failed dev Trial, and runs the Inspector Agent on
them as a Job. Each Task's App State names the Job and the Trial; the Finding
the Inspector records is read back from the App's final State, numbered, and
saved beside the inspected Job.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from plural.inspector.app import ATTEMPTS, CREDENTIAL, FORK_LEDGER, FORKS_PER_TRIAL, fork_seconds
from plural.inspector.causes import load_causes
from plural.inspector.evidence import JobEvidence, TrialEvidence, failed_trials
from plural.inspector.findings import (
    InspectionRecord,
    load_findings,
    now,
    number_findings,
    restatus,
    save_findings,
)
from plural.inspector.hosted import hosted_job_id
from plural.jobs import JobResult
from plural.project.layout import Project, ProjectError
from plural.project.resources import Workspace
from plural.project.runs import (
    RunRequest,
    find_local_trial,
    local_job_spec,
    plan_run,
    run_local,
)
from plural.studio import Studio

Depth = Literal["quick", "standard", "deep"]

INSPECTOR_FOLDER = "inspector"
"""Under a project's ``.plural``: the Inspector's own project, and its Jobs."""

TEMPLATE = Path(__file__).with_name("project")

DEFAULT_BUDGET_USD = 2.0
"""What forks may spend per inspected Job, by default."""


@dataclass(frozen=True)
class InspectorRun:
    """One run of the Inspector Agent.

    Attributes:
        job_id: The Inspector's Job, in its own folder.
        result: Its result.
        states: The Inspector App's final State, by the Inspector's Trial id.
        tasks: The inspected Trial each Inspector Trial looked at.
    """

    job_id: str
    result: JobResult
    states: dict[str, dict[str, Any]]
    tasks: dict[str, str]


def inspector_workspace(project: Workspace, *, model: str | None = None) -> Workspace:
    """The Inspector's project folder inside ``project``, refreshed from Plural's copy.

    Its Tasks are replaced on each run; its Jobs are kept.

    Returns:
        The Inspector's workspace.
    """
    root = project.project.state_dir / INSPECTOR_FOLDER
    for kind in ("environments", "verifiers", "agents", "tasks", "benchmarks"):
        shutil.rmtree(root / kind, ignore_errors=True)
    for path in TEMPLATE.rglob("*"):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        target = root / path.relative_to(TEMPLATE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    if model is not None:
        manifest = root / "agents" / "inspector" / "agent.yaml"
        payload = yaml.safe_load(manifest.read_text("utf-8"))
        payload["model"] = model
        manifest.write_text(yaml.safe_dump(payload, sort_keys=False), "utf-8")
    return Workspace(Project.at(root), catalog=project.catalog)


FORK_KEY_SECONDS = 3 * 3600
"""How long an inspection's fork key lasts by default if the inspection never ends."""

MAX_FORK_KEY_SECONDS = 12 * 3600
"""The longest an inspection's fork key may last; the platform caps it there too."""

INSPECTOR_SECONDS = 3600
"""The Inspector's own time for reading evidence and recording, beside its forks."""


def inspection_seconds(trials: Sequence[TrialEvidence], depth: Depth) -> int:
    """How long the Inspector may take on one Trial: its own time plus its forks'.

    Each fork's deadline follows the forked Trial's Environment limits, so an
    inspection of a long run waits for forks as long as that run.

    Returns:
        Seconds.
    """
    forks = FORKS_PER_TRIAL[depth]
    longest = max(
        (
            fork_seconds(trial.task.environment.limits.max_seconds, ATTEMPTS[depth])
            for trial in trials
        ),
        default=0.0,
    )
    return int(INSPECTOR_SECONDS + forks * longest)


def fork_ledger(job_dir: Path) -> float:
    """What an inspection's fork Trials spent, from the ledger they write as they finish.

    Returns:
        USD.
    """
    path = job_dir / FORK_LEDGER
    if not path.is_file():
        return 0.0
    total = 0.0
    for line in path.read_text("utf-8").splitlines():
        with suppress(ValueError):
            total += float(json.loads(line).get("cost_usd") or 0.0)
    return total


@contextmanager
def fork_key(
    studio: Studio | None, job_id: str, *, ttl_seconds: int = FORK_KEY_SECONDS
) -> Iterator[str | None]:
    """A gateway key for one inspection's forks of a Job, revoked on the way out.

    ``job_id`` is the hosted Job, or the local Job id when it was never
    recorded. Without hosted access there is no key, and forks are off.

    Yields:
        The key, or ``None``.
    """
    if studio is None:
        yield None
        return
    minted = studio.jobs.inspection_key(job_id, ttl_seconds=ttl_seconds)
    try:
        yield str(minted["key"])
    finally:
        with suppress(Exception):
            studio.jobs.end_inspection_key(job_id)


INSPECTING_FILE = "inspecting.json"


@contextmanager
def one_inspection(job_directory: Path) -> Iterator[None]:
    """Hold a Job's inspection lock while inspecting it.

    Starting an inspection revokes any other fork key for the same Job, and ending
    one revokes them all, so two at once would cut off each other's forks.

    Raises:
        ProjectError: When a live process is already inspecting the Job.
    """
    lock = job_directory / INSPECTING_FILE
    if lock.is_file():
        try:
            holder = int(json.loads(lock.read_text("utf-8"))["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            holder = 0
        if holder and holder != os.getpid() and _alive(holder):
            raise ProjectError(
                f"Job {job_directory.name} is already being inspected, by process {holder}. "
                "Wait for it to finish: two inspections of one Job cut off each other's forks."
            )
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": now().isoformat()}), "utf-8")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def fork_environ(environ: Mapping[str, str], key: str | None) -> dict[str, str]:
    """The run's environment, with this inspection's fork key as the only fork credential.

    Returns:
        A copy of ``environ``; any fork credential already in it is dropped.
    """
    copy = {name: value for name, value in environ.items() if name != CREDENTIAL}
    if key:
        copy[CREDENTIAL] = key
    return copy


def write_task(
    root: Path,
    name: str,
    *,
    state: Mapping[str, Any],
    instructions: str,
    expected: Any = None,
) -> None:
    """Add one Task to the Inspector's folder.

    ``state`` is the Inspector App's initial State: the project, Job, and Trial.
    """
    folder = root / "tasks" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "instruction.md").write_text(instructions.strip() + "\n", "utf-8")
    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "instructions": "instruction.md",
        "environment": "inspector",
        "verifiers": ["finding-check"],
        "initial_state": dict(state),
    }
    if expected is not None:
        manifest["expected"] = expected
    (folder / "task.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), "utf-8")


def write_benchmark(root: Path, name: str, tasks: Sequence[str], description: str) -> None:
    """Add a Benchmark of the Inspector's Tasks, so they run as one Job."""
    folder = root / "benchmarks" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "README.md").write_text(f"# {name}\n\n{description}\n", "utf-8")
    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": description,
        "purpose": "Explains why each of these Trials failed, a Finding for each cause.",
        "tasks": list(tasks),
        "scoring": {
            "description": "Share of Trials the Inspector recorded a Finding for, or, "
            "with an answer key, recorded the right one."
        },
    }
    (folder / "benchmark.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), "utf-8")


def task_name(trial_id: str) -> str:
    """The Inspector Task that looks at a Trial.

    Returns:
        A Task name.

    Examples:
        >>> task_name("trl_006008b12177e365fcf966b5")
        'trial-006008b12177e365fcf966b5'
    """
    return "trial-" + trial_id.removeprefix("trl_").lower().replace("_", "-")


def instructions_for(trial: TrialEvidence, depth: Depth, mode: str, question: str = "") -> str:
    """What one Inspector Task asks.

    Returns:
        The Task's instructions.
    """
    if mode == "ask":
        return (
            f"Answer one question about Trial {trial.trial_id} of Job {trial.job.job_id} "
            f"(Task {trial.task.task_id}), from its evidence, then call answer.\n\n"
            f"Question: {question}"
        )
    forks = {
        "quick": "This is a quick inspection: run no forks.",
        "standard": "Test an Agent cause with one or two forks.",
        "deep": "Test each plausible Agent cause with forks before you conclude.",
    }[depth]
    return (
        f"Trial {trial.trial_id} of Job {trial.job.job_id} failed Task {trial.task.task_id}. "
        f"Find its critical step and its cause, then call record_finding. {forks}"
    )


def run_inspector(
    project: Workspace,
    trials: Sequence[TrialEvidence],
    *,
    mode: Literal["inspect", "ask"],
    depth: Depth,
    budget_usd: float,
    environ: Mapping[str, str],
    model: str | None = None,
    fork_models: Sequence[str] = (),
    question: str = "",
    concurrency: int = 4,
    progress: Any = None,
) -> InspectorRun:
    """Run the Inspector Agent on some of a Job's Trials, one Task each.

    Returns:
        The Inspector's Job and each Trial's final App State.

    Raises:
        ProjectError: When there are no Trials to look at.
    """
    if not trials:
        raise ProjectError("There are no failed dev Trials to inspect.")
    space = inspector_workspace(project, model=model)
    root = space.project.root
    manifest = root / "environments" / "inspector" / "environment.yaml"
    payload = yaml.safe_load(manifest.read_text("utf-8"))
    payload.setdefault("limits", {})["max_seconds"] = inspection_seconds(trials, depth)
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), "utf-8")
    each = budget_usd / len(trials)
    names: dict[str, str] = {}
    for trial in trials:
        name = task_name(trial.trial_id)
        names[name] = trial.trial_id
        write_task(
            root,
            name,
            state={
                "mode": mode,
                "project": str(project.project.root),
                "job_id": trial.job.job_id,
                "trial_id": trial.trial_id,
                "question": question,
                "depth": depth,
                "budget_usd": round(each, 6),
                "gateway_url": environ.get("PLURAL_GATEWAY_URL", ""),
                "api_url": environ.get("PLURAL_API_URL", ""),
                "fork_models": list(fork_models),
            },
            instructions=instructions_for(trial, depth, mode, question),
        )
    bench = "inspect"
    write_benchmark(root, bench, sorted(names), "The failed Trials of one Job.")
    plan = plan_run(
        space,
        RunRequest(benchmark=bench, agent="inspector", concurrency=max(1, concurrency)),
        environ=environ,
    )
    job_id, result = run_local(space, plan, environ=environ, progress=progress)
    return InspectorRun(
        job_id=job_id,
        result=result,
        states=final_states(space, job_id),
        tasks=_inspected(space, job_id, names),
    )


def final_states(space: Workspace, job_id: str) -> dict[str, dict[str, Any]]:
    """The Inspector App's final State in each of a Job's Trials.

    Returns:
        The State, by Trial id.
    """
    states: dict[str, dict[str, Any]] = {}
    for trial_dir in sorted((space.project.jobs_dir / job_id / "trials").glob("*")):
        found = sorted(trial_dir.glob("executions/*/artifacts/apps.json"))
        if not found:
            continue
        apps = json.loads(found[-1].read_text("utf-8"))
        final = (apps.get("inspector") or {}).get("final")
        if isinstance(final, dict):
            states[trial_dir.name] = final
    return states


def _inspected(space: Workspace, job_id: str, names: Mapping[str, str]) -> dict[str, str]:
    """Which inspected Trial each of the Inspector's Trials looked at.

    Returns:
        Inspected Trial id, by the Inspector's Trial id.
    """
    spec = local_job_spec(space, job_id)
    tasks = {item.content_hash: item.task_id for item in spec.tasks}
    return {
        item.trial_id: names[tasks[item.task_digest]]
        for item in spec.plan().trials
        if tasks.get(item.task_digest) in names
    }


def inspect_job(
    project: Workspace,
    job_id: str,
    *,
    depth: Depth = "standard",
    budget_usd: float = DEFAULT_BUDGET_USD,
    environ: Mapping[str, str],
    model: str | None = None,
    fork_models: Sequence[str] = (),
    trial_ids: Sequence[str] = (),
    concurrency: int = 4,
    progress: Any = None,
    studio: Studio | None = None,
) -> InspectionRecord:
    """Run the Inspector on a local Job's failed dev Trials and save its Findings.

    With ``studio``, forks call models with a key minted for this inspection
    alone and revoked when it ends; without it, forks are off.

    Returns:
        The inspection: a Finding for each cause of each failed Trial it concluded on.
    """
    evidence = JobEvidence(project.project.root, job_id)
    trials = failed_trials(evidence, trial_ids)
    reference = hosted_job_id(project, job_id) or job_id
    waves = -(-len(trials) // max(1, concurrency))
    ttl = min(MAX_FORK_KEY_SECONDS, waves * inspection_seconds(trials, depth) + 600)
    (evidence.directory / FORK_LEDGER).unlink(missing_ok=True)
    with (
        one_inspection(evidence.directory),
        fork_key(studio if depth != "quick" else None, reference, ttl_seconds=ttl) as key,
    ):
        run = run_inspector(
            project,
            trials,
            mode="inspect",
            depth=depth,
            budget_usd=budget_usd,
            environ=fork_environ(environ, key),
            model=model,
            fork_models=fork_models,
            concurrency=concurrency,
            progress=progress,
        )
    drafts: list[dict[str, Any]] = []
    concluded: set[str] = set()
    spent = sum(float(item.metrics.get("cost_usd") or 0.0) for item in run.result.trials)
    by_trial = {run.tasks.get(key): value for key, value in run.states.items()}
    reported = sum(float(state.get("spent_usd") or 0.0) for state in by_trial.values())
    # Forks that timed out, or were still running when the Inspector stopped, spent
    # what the ledger says, beyond what the Inspector saw.
    spent += max(reported, fork_ledger(evidence.directory))
    for trial in trials:
        state = by_trial.get(trial.trial_id) or {}
        findings = [item for item in state.get("findings") or () if isinstance(item, dict)]
        if not findings:
            continue
        concluded.add(trial.trial_id)
        inspector_trial = next(
            (key for key, value in run.tasks.items() if value == trial.trial_id), None
        )
        drafts.extend({**item, "inspector_trial_id": inspector_trial} for item in findings)
    record = InspectionRecord(
        job_id=job_id,
        inspected_at=now(),
        inspector_job_id=run.job_id,
        depth=depth,
        failed=len(evidence.failed()),
        findings=restatus(
            number_findings(job_id, drafts),
            (item.name for item in load_causes(project.project.root) if item.agent),
        ),
        uninspected=tuple(item.trial_id for item in trials if item.trial_id not in concluded),
        cost_usd=round(spent, 6),
    )
    save_findings(evidence.directory, record)
    return record


def ask_trial(
    project: Workspace,
    trial_id: str,
    question: str,
    *,
    environ: Mapping[str, str],
    model: str | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    """Ask the Inspector one question about a local Trial.

    Returns:
        The answer, and the Inspector's Job and Trial.

    Raises:
        ProjectError: When the Inspector gave no answer.
    """
    job_id, _ = find_local_trial(project, trial_id)
    evidence = JobEvidence(project.project.root, job_id)
    run = run_inspector(
        project,
        [evidence.trial(trial_id)],
        mode="ask",
        depth="quick",
        budget_usd=0.0,
        environ=fork_environ(environ, None),
        model=model,
        question=question,
        concurrency=1,
        progress=progress,
    )
    inspector_trial, state = next(iter(run.states.items()), (None, {}))
    answer = state.get("answer")
    if not answer:
        raise ProjectError(
            f"The Inspector gave no answer. See its Trial with plural trial show "
            f"{inspector_trial} in {project.project.state_dir / INSPECTOR_FOLDER}."
        )
    return {
        "trial_id": trial_id,
        "question": question,
        "answer": answer,
        "inspector_job_id": run.job_id,
        "inspector_trial_id": inspector_trial,
    }


def findings_for(project: Workspace, job_id: str) -> InspectionRecord | None:
    """A local Job's saved inspection, if it has one.

    Returns:
        The record, or ``None``.
    """
    return load_findings(project.project.jobs_dir / job_id)


__all__ = [
    "DEFAULT_BUDGET_USD",
    "FORK_KEY_SECONDS",
    "INSPECTOR_FOLDER",
    "Depth",
    "InspectorRun",
    "ask_trial",
    "findings_for",
    "final_states",
    "fork_environ",
    "fork_key",
    "inspect_job",
    "inspector_workspace",
    "instructions_for",
    "run_inspector",
    "task_name",
    "write_benchmark",
    "write_task",
]
