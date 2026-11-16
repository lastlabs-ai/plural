"""Where an evaluation of an Agent stands, step by step, read from a project.

``plural eval status`` prints this. It checks a project against the eight steps
of evaluating and improving an Agent and names the one command to run next.
Steps whose commands are not in Plural yet say so instead of suggesting one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from plural.common import FrozenModel
from plural.harness.probes import ProbeKind
from plural.integrity.checks import ProbeResult, TaskCheck
from plural.project import Project, ProjectError, Workspace
from plural.project.layout import (
    AGENT,
    BENCHMARK,
    ENVIRONMENT,
    TASK,
    ResourceRef,
    find_project_root,
)
from plural.project.runs import local_job, local_jobs

StepStatus = Literal["done", "attention", "todo", "coming_soon"]
"""``done``; ``attention``, when something needs fixing; ``todo``; or ``coming_soon``,
when Plural does not have the step's commands yet."""

STEPS = (
    "Set up",
    "Define good",
    "Build the eval set",
    "Check the graders",
    "Baseline",
    "Diagnose",
    "Improve",
    "Report",
)


_AVAILABLE = frozenset({1, 2, 3, 4, 5})


class EvalStep(FrozenModel):
    """One step of an evaluation and how far the project has got with it.

    Attributes:
        number: The step's place, from 1 to 8.
        title: The step's name, such as ``"Baseline"``.
        status: How far along it is.
        summary: The few facts that matter for this step, in a line.
        command: The command that does this step, or ``None`` when there is none yet.
    """

    number: int
    title: str
    status: StepStatus
    summary: str = ""
    command: str | None = None


class EvalStatus(FrozenModel):
    """Every step of an evaluation, and the one command to run next.

    Attributes:
        project: The project's name, or ``None`` outside a project.
        benchmark: The Benchmark being evaluated, or ``None`` when there isn't one
            to pick yet.
        steps: The eight steps, in order.
        next_command: The command to run next.
    """

    project: str | None
    benchmark: str | None = None
    steps: tuple[EvalStep, ...]
    next_command: str


def eval_status(path: str | Path = ".", *, benchmark: str | None = None) -> EvalStatus:
    """Check the project at ``path`` against the steps of an evaluation.

    It reads the project's resources and its local Jobs only: it calls no model and
    nothing hosted. With one Benchmark in the project, that Benchmark is evaluated;
    with several, name one.

    Args:
        path: A directory in the project.
        benchmark: The Benchmark to evaluate, when the project has several.

    Returns:
        Each step's status, and the command to run next.

    Examples:
        >>> import tempfile
        >>> status = eval_status(tempfile.mkdtemp())
        >>> status.steps[0].status, status.next_command
        ('todo', 'plural project init <name>')
    """
    root = find_project_root(Path(path))
    if root is None:
        setup = EvalStep(
            number=1,
            title=STEPS[0],
            status="todo",
            summary="No project here.",
            command="plural project init <name>",
        )
        return _status(None, None, [setup])
    workspace = Workspace(Project.find(root))
    project = workspace.project
    environments = project.names(ENVIRONMENT)
    agents = project.names(AGENT)
    benchmarks = project.names(BENCHMARK)

    steps = [_setup(environments, agents)]
    chosen, problem = _pick(benchmarks, benchmark)
    if chosen is None:
        steps.append(problem)
        return _status(project.name, None, steps)
    try:
        loaded = workspace.get("benchmark", chosen)
    except ProjectError as exc:
        steps.append(
            EvalStep(
                number=3,
                title=STEPS[2],
                status="attention",
                summary=f"Benchmark {chosen} is not valid: {exc.message}",
                command=f"plural benchmark validate {chosen}",
            )
        )
        return _status(project.name, chosen, steps)
    verifiers = {item.name for task in loaded.tasks for item in task.verifiers}
    steps.append(_define_good(workspace, chosen, loaded.scorecard, len(verifiers)))
    steps.append(_eval_set(workspace, chosen, loaded))
    steps.append(_graders(workspace, chosen, [task.name for task in loaded.tasks]))
    steps.append(_baseline(workspace, chosen, agents))
    return _status(project.name, chosen, steps)


def _setup(environments: list[str], agents: list[str]) -> EvalStep:
    summary = f"{_counted(len(environments), 'Environment')}, {_counted(len(agents), 'Agent')}"
    if not environments:
        command = "plural env init <name>"
    elif not agents:
        command = "plural agent init <name> --model <model>"
    else:
        return EvalStep(number=1, title=STEPS[0], status="done", summary=summary)
    return EvalStep(number=1, title=STEPS[0], status="todo", summary=summary, command=command)


def _pick(benchmarks: list[str], wanted: str | None) -> tuple[str | None, EvalStep]:
    if wanted is not None:
        if wanted in benchmarks:
            return wanted, EvalStep(number=3, title=STEPS[2], status="done")
        return None, EvalStep(
            number=3,
            title=STEPS[2],
            status="attention",
            summary=f"No Benchmark {wanted!r} in this project.",
            command=f"plural eval status --benchmark {benchmarks[0]}"
            if benchmarks
            else f"plural benchmark init {wanted}",
        )
    if len(benchmarks) == 1:
        return benchmarks[0], EvalStep(number=3, title=STEPS[2], status="done")
    if not benchmarks:
        return None, EvalStep(
            number=3,
            title=STEPS[2],
            status="todo",
            summary="No Benchmark yet.",
            command="plural benchmark init <name>",
        )
    return None, EvalStep(
        number=3,
        title=STEPS[2],
        status="attention",
        summary=f"{len(benchmarks)} Benchmarks: {', '.join(benchmarks)}. Pick one.",
        command=f"plural eval status --benchmark {benchmarks[0]}",
    )


def _baseline(workspace: Workspace, benchmark: str, agents: list[str]) -> EvalStep:
    jobs = [job for job in local_jobs(workspace) if job.get("source") == f"benchmark/{benchmark}"]
    run = f"plural run -b {benchmark} -a {agents[0] if agents else '<agent>'}"
    if not jobs:
        return EvalStep(number=5, title=STEPS[4], status="todo", summary="No run yet.", command=run)
    latest = jobs[0]
    job_id = latest["job_id"]
    agent = str(latest.get("agent") or "").removeprefix("agent/") or "an Agent"
    if latest["status"] == "succeeded":
        try:
            summaries = local_job(workspace, job_id).get("summaries") or []
        except ProjectError:
            summaries = []
        if summaries:
            shown = str(summaries[0]["text"])
        else:
            score = latest.get("score")
            shown = f"score {score:.2f}" if isinstance(score, (int, float)) else "no score"
        return EvalStep(
            number=5,
            title=STEPS[4],
            status="done",
            summary=f"{job_id}: {agent}, {shown}",
            command=f"plural job show {job_id}",
        )
    return EvalStep(
        number=5,
        title=STEPS[4],
        status="attention",
        summary=f"{job_id} is {str(latest['status']).replace('_', ' ')}",
        command=f"plural job show {job_id}",
    )


def _graders(workspace: Workspace, benchmark: str, tasks: list[str]) -> EvalStep:
    from plural.project.checks import load_check

    checks = {name: load_check(workspace, name) for name in tasks}
    unchecked = [name for name, check in checks.items() if check is None]
    failing = [name for name, check in checks.items() if check is not None and not check.passed]
    command = f"plural eval check -b {benchmark}"
    if failing:
        problems = sum(len(check.problems) for check in checks.values() if check is not None)
        return EvalStep(
            number=4,
            title=STEPS[3],
            status="attention",
            summary=f"{_counted(problems, 'problem')} in {_counted(len(failing), 'Task')}",
            command=command,
        )
    if unchecked:
        return EvalStep(
            number=4,
            title=STEPS[3],
            status="todo",
            summary=f"{len(tasks) - len(unchecked)} of {_counted(len(tasks), 'Task')} checked",
            command=command,
        )
    return EvalStep(
        number=4,
        title=STEPS[3],
        status="done",
        summary=f"{_counted(len(tasks), 'Task')} checked: references pass, probes fail, no leaks",
        command=command,
    )


def _define_good(
    workspace: Workspace, benchmark: str, scorecard: str | None, verifiers: int
) -> EvalStep:
    """Step 2: a Scorecard on the Benchmark, labeled, with its graders calibrated.

    Returns:
        The step, naming the next Scorecard command.
    """
    from plural.project.layout import SCORECARD
    from plural.project.scorecards import labels, latest_calibration, load_scorecard

    graded = f"Graded by {_counted(verifiers, 'Verifier')}"
    if scorecard is None:
        written = workspace.project.names(SCORECARD)
        if written:
            return EvalStep(
                number=2,
                title=STEPS[1],
                status="todo",
                summary=f"{graded}. Scorecard {written[0]} is in the project but not on "
                f"the Benchmark: add `scorecard: {written[0]}` to its file.",
                command=f"plural scorecard calibrate {written[0]}",
            )
        return EvalStep(
            number=2,
            title=STEPS[1],
            status="todo",
            summary=f"{graded}. No Scorecard yet.",
            command="plural scorecard draft <workflow>",
        )
    scorecard = scorecard.partition("@")[0]
    try:
        card = load_scorecard(workspace, scorecard)
    except ProjectError as exc:
        return EvalStep(
            number=2,
            title=STEPS[1],
            status="attention",
            summary=f"Scorecard {scorecard} is not valid: {exc.message}",
            command=f"plural scorecard validate {scorecard}",
        )
    labeled = len({label.trial_id for label in labels(workspace, scorecard)})
    facts = f"{card.reference}: {_counted(len(card.metrics), 'metric')}, {labeled} Trials labeled"
    if labeled < card.calibration.min_labels:
        return EvalStep(
            number=2,
            title=STEPS[1],
            status="todo",
            summary=f"{facts}; calibration needs {card.calibration.min_labels}.",
            command=f"plural scorecard label {scorecard} --job <job>",
        )
    calibration = latest_calibration(workspace, scorecard)
    if calibration is None:
        return EvalStep(
            number=2,
            title=STEPS[1],
            status="todo",
            summary=f"{facts}. The graders are not checked yet.",
            command=f"plural scorecard calibrate {scorecard}",
        )
    unready = [item.metric for item in calibration.metrics if item.status != "trusted"]
    return EvalStep(
        number=2,
        title=STEPS[1],
        status="attention" if unready else "done",
        summary=f"{facts}. "
        + (f"Not calibrated: {', '.join(unready)}." if unready else "Every grader calibrated."),
        command=f"plural scorecard calibrate {scorecard}",
    )


def _eval_set(workspace: Workspace, benchmark: str, loaded: Any) -> EvalStep:
    """Step 3: the Benchmark's Tasks, with some held out to confirm fixes on.

    Returns:
        The step: a split to make, or the split and its peeks.
    """
    from plural.heldout import peeks

    summary = _counted(len(loaded.tasks), "Task")
    if loaded.categories:
        summary += f" in {_counted(len(loaded.categories), 'category', 'categories')}"
    if not loaded.heldout:
        return EvalStep(
            number=3,
            title=STEPS[2],
            status="todo",
            summary=f"{summary}, none held out to confirm fixes on.",
            command=f"plural benchmark split {benchmark}",
        )
    looked = len(peeks(workspace.project.state_dir, benchmark))
    return EvalStep(
        number=3,
        title=STEPS[2],
        status="done",
        summary=f"{summary}, {len(loaded.heldout)} held out; {_counted(looked, 'peek')}.",
        command=f"plural benchmark show {benchmark}",
    )


def _coming_soon(number: int, what: str = "") -> EvalStep:
    summary = f"{what} are coming soon." if what else "Coming soon."
    return EvalStep(number=number, title=STEPS[number - 1], status="coming_soon", summary=summary)


def _status(project: str | None, benchmark: str | None, steps: list[EvalStep]) -> EvalStatus:
    numbered = {step.number: step for step in steps}
    ordered = tuple(
        numbered.get(number)
        or (
            EvalStep(number=number, title=STEPS[number - 1], status="todo")
            if number in _AVAILABLE
            else _coming_soon(number)
        )
        for number in range(1, len(STEPS) + 1)
    )
    pending = [step for step in ordered if step.status in {"todo", "attention"} and step.command]
    if pending:
        next_command = pending[0].command
    else:
        done = [step for step in ordered if step.status == "done" and step.command]
        next_command = done[-1].command if done else "plural --help"
    assert next_command is not None
    return EvalStatus(
        project=project, benchmark=benchmark, steps=ordered, next_command=next_command
    )


def _counted(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun if count == 1 else plural or noun + 's'}"


CheckMark = Literal["ok", "problem", "warning"]


class CheckLine(FrozenModel):
    """One line of ``plural eval check``.

    Attributes:
        mark: ``ok``, ``problem`` to fix before a baseline, or ``warning``.
        text: The line.
        detail: An indented second line, such as the Verifier's feedback.
        tasks: The Tasks it is about.
        command: The command that shows more or fixes it.
    """

    mark: CheckMark
    text: str
    detail: str = ""
    tasks: tuple[str, ...] = ()
    command: str | None = None


class CheckSection(FrozenModel):
    """A titled group of lines, such as ``Graders``."""

    title: str
    lines: tuple[CheckLine, ...]


class EvalCheck(FrozenModel):
    """What ``plural eval check`` found.

    Attributes:
        project: The project's name.
        benchmark: The Benchmark checked.
        tasks: Tasks checked.
        sections: Graders, Leaks, and Isolation.
        problems: Lines marked ``problem``.
        next_command: The command to run next.
    """

    project: str
    benchmark: str
    tasks: int
    sections: tuple[CheckSection, ...]
    problems: int
    next_command: str


def eval_check(
    path: str | Path = ".",
    *,
    benchmark: str | None = None,
    rerun: bool = False,
    random_steps: int = 0,
    progress: Callable[[str], None] | None = None,
    environ: Mapping[str, str] | None = None,
) -> EvalCheck:
    """Check a Benchmark's graders, leaks, and isolation before a baseline.

    Each Task's check is reused while the Task is unchanged; ``rerun`` runs
    every check again. The probes run locally in each Task's own Runtime.

    Args:
        path: A directory in the project.
        benchmark: The Benchmark, when the project has several.
        rerun: Run every Task's check again.
        random_steps: Also run the ``random`` probe for this many actions.
        progress: Called with a line as each probe starts.
        environ: Where to look up the conformance cache.

    Returns:
        The findings and the command to run next.

    Raises:
        ProjectError: Outside a project, or when the Benchmark can't be chosen.
    """
    from plural.project.checks import load_check, plan_checks, run_checks

    root = find_project_root(Path(path))
    if root is None:
        raise ProjectError("Not in a Plural project. Run plural project init <name>.")
    workspace = Workspace(Project.find(root))
    project = workspace.project
    chosen, problem = _pick(project.names(BENCHMARK), benchmark)
    if chosen is None:
        raise ProjectError(
            problem.summary + (f" Run {problem.command}." if problem.command else "")
        )
    plan = plan_checks(workspace, benchmark=chosen)
    stale = (
        plan.tasks
        if rerun
        else [name for name in plan.tasks if load_check(workspace, name) is None]
    )
    probes: tuple[Any, ...] = ("reference", "noop", "echo") + (("random",) if random_steps else ())
    if stale:
        subset = plan_checks(workspace, stale, benchmark=chosen)
        run_checks(
            workspace, subset, probes=probes, random_steps=random_steps or 20, progress=progress
        )
    checks = {name: load_check(workspace, name) for name in plan.tasks}
    present = {name: check for name, check in checks.items() if check is not None}
    sections = (
        CheckSection(title="Graders", lines=tuple(_grader_lines(present, plan.skipped))),
        CheckSection(title="Leaks", lines=tuple(_leak_lines(present))),
        CheckSection(
            title="Isolation", lines=tuple(_isolation_lines(workspace, plan.tasks, environ))
        ),
    )
    problems = [line for section in sections for line in section.lines if line.mark == "problem"]
    agents = project.names(AGENT)
    baseline = f"plural run -b {chosen} -a {agents[0] if agents else '<agent>'} --attempts 3"
    next_command = (problems[0].command or baseline) if problems else baseline
    return EvalCheck(
        project=project.name,
        benchmark=chosen,
        tasks=len(plan.tasks),
        sections=sections,
        problems=len(problems),
        next_command=next_command,
    )


_PROBE_LABELS: dict[ProbeKind, str] = {
    "noop": "do-nothing agent fails",
    "echo": "copy-the-instructions agent fails",
    "random": "random-actions agent fails",
}


def _grader_lines(checks: Mapping[str, TaskCheck], skipped: Mapping[str, str]) -> list[CheckLine]:
    lines: list[CheckLine] = []
    references = {
        name: item
        for name, check in checks.items()
        if (item := check.probe("reference")) is not None and item.status != "skipped"
    }
    if references:
        passing = sum(item.status == "passed" for item in references.values())
        lines.append(
            CheckLine(
                mark="ok",
                text=f"{'reference solution passes every gate':<44} {passing}/{len(references)}",
            )
        )
        lines.extend(_failures("reference", references))
    missing = tuple(name for name in checks if name not in references)
    if missing:
        lines.append(
            CheckLine(
                mark="warning",
                text=f"{_names(missing)}: no reference policy, so nothing shows the Task "
                "can be solved",
                detail="add reference: file.py:function to the Task or its Environment",
                tasks=missing,
            )
        )
    for kind, label in _PROBE_LABELS.items():
        results = {
            name: item for name, check in checks.items() if (item := check.probe(kind)) is not None
        }
        if not results:
            continue
        failing = sum(item.status == "passed" for item in results.values())
        lines.append(CheckLine(mark="ok", text=f"{label:<44} {failing}/{len(results)}"))
        lines.extend(_failures(kind, results))
    for name, reason in skipped.items():
        lines.append(
            CheckLine(mark="warning", text=f"{name}: not checked, {reason}", tasks=(name,))
        )
    return lines


def _failures(kind: str, results: Mapping[str, ProbeResult]) -> list[CheckLine]:
    groups: dict[tuple[str, ...], list[str]] = {}
    for name, item in results.items():
        if item.status == "error":
            groups.setdefault(("error",), []).append(name)
        elif item.status == "failed":
            key = item.failed_checks if kind == "reference" else ()
            groups.setdefault(key, []).append(name)
    lines = []
    for key, names in groups.items():
        first = results[names[0]]
        if key == ("error",):
            text = f"{_names(names)}: {first.detail}"
        elif kind == "reference":
            text = f"{_names(names)}: reference fails {', '.join(key) or 'the threshold'}"
        else:
            text = f"{_names(names)}: {first.detail}"
        lines.append(
            CheckLine(
                mark="warning" if kind == "random" else "problem",
                text=text,
                detail=first.feedback,
                tasks=tuple(names),
                command=f"plural task check {names[0]}",
            )
        )
    return lines


def _leak_lines(checks: Mapping[str, TaskCheck]) -> list[CheckLine]:
    lines: list[CheckLine] = []
    groups: dict[tuple[str, str], list[str]] = {}
    messages: dict[tuple[str, str], tuple[str, str]] = {}
    unread: dict[str, list[str]] = {}
    for name, check in checks.items():
        for leak in check.leaks:
            if leak.severity == "info":
                unread.setdefault(leak.path, []).append(name)
                continue
            key: tuple[str, str] = (leak.kind, leak.path)
            groups.setdefault(key, []).append(name)
            messages[key] = (leak.message, leak.severity)
    for key, names in groups.items():
        message, _severity = messages[key]
        lines.append(
            CheckLine(
                mark="problem",
                text=f"{_names(tuple(names))}: {message}",
                detail=_LEAK_FIXES[key[0]],
                tasks=tuple(names),
                command=f"plural task check {names[0]}",
            )
        )
    if not groups:
        lines.append(
            CheckLine(
                mark="ok",
                text="no answer keys, git history, solution files or Verifier code in "
                "agent-visible files",
            )
        )
    if unread:
        paths = sorted(unread)
        lines.append(
            CheckLine(
                mark="warning",
                text=f"{_counted(len(paths), 'file')} not scanned: {', '.join(paths[:3])}"
                + (f" and {len(paths) - 3} more" if len(paths) > 3 else ""),
                detail="check these by hand; their format has no text the scan can read",
            )
        )
    return lines


_LEAK_FIXES = {
    "answer_key": "remove it from what the Agent sees; the answer key belongs in expected",
    "git_history": "ship the repository with one commit: no older commits, tags, or branches",
    "solution_file": "rename or remove the file, or move it out of the Agent's files",
    "verifier_copy": "keep Verifier code in its own folder, never in the Agent's files",
    "canary": "keep the Benchmark's canary out of every agent-visible file",
    "not_scanned": "",
}


def _isolation_lines(
    workspace: Workspace, tasks: Sequence[str], environ: Mapping[str, str] | None
) -> list[CheckLine]:
    from plural.sandbox import default_registry
    from plural.sandbox.conformance import conformance_status

    providers: dict[str, list[str]] = {}
    for name in tasks:
        environment = workspace.load(ResourceRef(TASK.name, name)).value._environment_definition()
        provider = environment.runtime.provider
        if environment.name not in providers.setdefault(provider, []):
            providers[provider].append(environment.name)
    lines = []
    for provider, environments in sorted(providers.items()):
        where = ", ".join(environments)
        if provider == "local":
            lines.append(
                CheckLine(
                    mark="warning",
                    text=f"{where} runs on the local Runtime, so Trials are unverified",
                    detail="use runtime: {provider: daytona} for verified results",
                )
            )
            continue
        try:
            status, failures = asyncio.run(
                conformance_status(default_registry.get(provider), environ)
            )
        except Exception:  # noqa: BLE001 - an unreachable provider has no report
            status, failures = "missing", ()
        if status == "passed":
            lines.append(
                CheckLine(
                    mark="ok", text=f"{where} runs on {provider}: verified, conformance passed"
                )
            )
        elif status == "failed":
            lines.append(
                CheckLine(
                    mark="warning",
                    text=f"{where} runs on {provider}: standard, conformance failed "
                    f"{', '.join(failures)}",
                    command=f"plural runtime doctor --provider {provider} --conformance",
                )
            )
        else:
            lines.append(
                CheckLine(
                    mark="warning",
                    text=f"{where} runs on {provider}: standard until its conformance suite runs",
                    command=f"plural runtime doctor --provider {provider} --conformance",
                )
            )
    return lines


def _names(names: Sequence[str]) -> str:
    shown = ", ".join(names[:3])
    return shown + (f" and {len(names) - 3} more" if len(names) > 3 else "")


__all__ = [
    "STEPS",
    "CheckLine",
    "CheckMark",
    "CheckSection",
    "EvalCheck",
    "EvalStatus",
    "EvalStep",
    "StepStatus",
    "eval_check",
    "eval_status",
]
