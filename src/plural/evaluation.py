"""Where an evaluation of an Agent stands, step by step, read from a project.

``plural eval status`` prints this. It checks a project against the eight steps
of evaluating and improving an Agent and names the one command to run next.
Steps whose commands are not in Plural yet say so instead of suggesting one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from plural.common import FrozenModel
from plural.project import Project, ProjectError, Workspace
from plural.project.layout import AGENT, BENCHMARK, ENVIRONMENT, find_project_root
from plural.project.runs import local_jobs

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


_AVAILABLE = frozenset({1, 3, 5})


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
    steps.append(
        _coming_soon(2, f"Graded by {_counted(len(verifiers), 'Verifier')} today. Scorecards")
    )
    summary = _counted(len(loaded.tasks), "Task")
    if loaded.categories:
        summary += f" in {_counted(len(loaded.categories), 'category', 'categories')}"
    steps.append(
        EvalStep(
            number=3,
            title=STEPS[2],
            status="done",
            summary=f"{summary}. Held-out split coming soon.",
            command=f"plural benchmark show {chosen}",
        )
    )
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
        score = latest.get("score")
        shown = f"{score:.2f}" if isinstance(score, (int, float)) else "no score"
        return EvalStep(
            number=5,
            title=STEPS[4],
            status="done",
            summary=f"{job_id}: {agent} scored {shown}",
            command=f"plural job show {job_id}",
        )
    return EvalStep(
        number=5,
        title=STEPS[4],
        status="attention",
        summary=f"{job_id} is {str(latest['status']).replace('_', ' ')}",
        command=f"plural job show {job_id}",
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


__all__ = ["STEPS", "EvalStatus", "EvalStep", "StepStatus", "eval_status"]
