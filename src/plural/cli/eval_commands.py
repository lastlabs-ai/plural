"""``plural eval``: evaluate an Agent and improve it, one step at a time."""

from __future__ import annotations

from typing import Any

import typer

from plural.cli.common import (
    JSON_OPTION,
    counted,
    emit,
    handled,
    heading,
    muted,
    session,
    workspace,
)
from plural.evaluation import CheckLine, CheckMark, EvalCheck, EvalStatus, eval_check, eval_status
from plural.integrity.checks import TaskCheck

eval_app = typer.Typer(
    help="Evaluate an Agent and improve it, one step at a time.", no_args_is_help=True
)

_MARKS = {
    "done": typer.style("✓", fg="green", bold=True),
    "attention": typer.style("!", fg="yellow", bold=True),
    "todo": "•",
    "coming_soon": muted("–"),
}


@eval_app.command("status")
@handled
def status(
    benchmark: str | None = typer.Option(
        None, "--benchmark", "-b", help="The Benchmark to evaluate, when there are several."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show each step of evaluating an Agent and the command to run next.

    The steps are: set up, define good, build the eval set, check the graders,
    baseline, diagnose, improve, and report. This reads the project and its local
    Jobs only. Steps whose commands are not in Plural yet show as coming soon.
    """
    result = eval_status(benchmark=benchmark)
    emit(result, as_json=as_json, text=lambda: _print(result))


def _print(result: EvalStatus) -> None:
    if result.project is None:
        heading("Not in a Plural project")
    elif result.benchmark is None:
        heading(f"Evaluation in {result.project}")
    else:
        heading(f"Evaluation of {result.benchmark} in {result.project}")
    width = max(len(step.title) for step in result.steps)
    for step in result.steps:
        title = step.title.ljust(width)
        if step.status == "coming_soon":
            typer.echo(
                f"  {_MARKS[step.status]} {step.number}  {muted(title)}  {muted(step.summary)}"
            )
        else:
            typer.echo(f"  {_MARKS[step.status]} {step.number}  {title}  {step.summary}")
    typer.echo(f"Next: {result.next_command}")


_CHECK_MARKS = {
    "ok": typer.style("✓", fg="green", bold=True),
    "problem": typer.style("✗", fg="red", bold=True),
    "warning": typer.style("!", fg="yellow", bold=True),
}


@eval_app.command("check")
@handled
def check(
    benchmark: str | None = typer.Option(
        None, "--benchmark", "-b", help="The Benchmark to check, when there are several."
    ),
    rerun: bool = typer.Option(
        False, "--rerun", help="Check every Task again, even those unchanged since their check."
    ),
    random_steps: int = typer.Option(
        0,
        "--random",
        min=0,
        help="Also run an Agent that takes this many random actions. A pass is a warning.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Check the graders, leaks, and isolation before a baseline.

    Each Task runs its reference policy and two probes that should fail, a
    do-nothing Agent and one that repeats the instructions, in its own Runtime.
    Everything the Agent can read is scanned for the answer key, git history,
    solution files, Verifier code, and the Benchmark's canary. A Task's check is
    kept until the Task changes.
    """

    def progress(line: str) -> None:
        if not as_json:
            typer.echo(muted(line), err=True)

    result = eval_check(
        benchmark=benchmark, rerun=rerun, random_steps=random_steps, progress=progress
    )
    emit(result, as_json=as_json, text=lambda: _print_check(result))
    if result.problems:
        raise typer.Exit(1)


def _print_check(result: EvalCheck) -> None:
    heading(f"Checked {counted(result.tasks, 'Task')} in {result.benchmark}")
    for section in result.sections:
        typer.echo(section.title)
        for line in section.lines:
            _print_line(line)
    if result.problems:
        typer.echo(
            f"\n{counted(result.problems, 'problem')} to fix before you baseline. "
            f"Next: {result.next_command}"
        )
    else:
        typer.echo(f"\nNo problems. Next: {result.next_command}")


def _print_line(line: CheckLine) -> None:
    typer.echo(f"  {_CHECK_MARKS[line.mark]} {line.text}")
    if line.detail:
        typer.echo(f"      {muted(line.detail)}")


@handled
def task_check(
    names: list[str] | None = typer.Argument(
        None, help="Tasks to check. Leave out to check every Task, or the Benchmark's with -b."
    ),
    benchmark: str | None = typer.Option(
        None,
        "--benchmark",
        "-b",
        help="Check this Benchmark's Tasks, against its success threshold and canary.",
    ),
    random_steps: int = typer.Option(
        0,
        "--random",
        min=0,
        help="Also run an Agent that takes this many random actions. A pass is a warning.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Prove each Task can be solved and can't be passed by doing nothing.

    Runs the Task's reference policy, which must pass, and a do-nothing Agent and
    one that repeats the instructions, which must fail, through the normal engine
    in the Task's own Runtime. Then scans everything the Agent can read for the
    answer key and other leaks. Each result is saved to
    .plural/checks/<task>@<version>.json.
    """
    from plural.project.checks import plan_checks, run_checks

    space = workspace()
    plan = plan_checks(space, names or (), benchmark=benchmark)
    probes: tuple[Any, ...] = ("reference", "noop", "echo") + (("random",) if random_steps else ())

    def progress(line: str) -> None:
        if not as_json:
            typer.echo(muted(line), err=True)

    checks = run_checks(
        space, plan, probes=probes, random_steps=random_steps or 20, progress=progress
    )
    payload = {
        "checks": [item.model_dump(mode="json") for item in checks],
        "skipped": plan.skipped,
        "problems": sum(len(item.problems) for item in checks),
    }
    shared = _share_checks(checks)
    if shared and not as_json:
        typer.echo(muted(f"Recorded {counted(shared, 'check')} on the pushed Task revisions."))
    emit(payload, as_json=as_json, text=lambda: _print_task_checks(checks, plan.skipped))
    if payload["problems"]:
        raise typer.Exit(1)


def _share_checks(checks: list[TaskCheck]) -> int:
    """Record each check on its pushed Task revision, when signed in. Never fails the command.

    Returns:
        How many checks were recorded.
    """
    from plural.studio import slugify

    try:
        current = session()
        if current.token is None:
            return 0
        tasks = current.studio().tasks
    except Exception:  # noqa: BLE001 - recording is a convenience, never a failure
        return 0
    recorded = 0
    for check in checks:
        try:
            parent = tasks.find(slugify(check.task))
            if parent is None:
                continue
            revision = next(
                (
                    item
                    for item in tasks.revisions(str(parent["id"]))
                    if item.get("content_hash") == check.content_hash
                ),
                None,
            )
            if revision is None:
                continue
            payload = check.model_dump(mode="json")
            tasks.record_check(str(parent["id"]), str(revision["id"]), payload)
            recorded += 1
        except Exception:  # noqa: BLE001
            continue
    return recorded


def _print_task_checks(checks: list[TaskCheck], skipped: dict[str, str]) -> None:
    for item in checks:
        mark = _CHECK_MARKS["ok" if item.passed else "problem"]
        typer.echo(f"{mark} {item.task} {muted(item.version)}")
        for probe in item.probes:
            kind: CheckMark
            if probe.status == "skipped":
                kind = "warning"
            elif probe.status == "passed":
                kind = "ok"
            else:
                kind = "warning" if probe.probe == "random" else "problem"
            _print_line(
                CheckLine(
                    mark=kind, text=probe.detail, detail=probe.feedback if kind != "ok" else ""
                )
            )
        for leak in item.leaks:
            _print_line(
                CheckLine(
                    mark="warning" if leak.severity == "info" else "problem", text=leak.message
                )
            )
        if not any(leak.severity != "info" for leak in item.leaks):
            _print_line(
                CheckLine(mark="ok", text="nothing the Agent can read gives the answer away")
            )
    for name, reason in skipped.items():
        typer.echo(f"{_CHECK_MARKS['warning']} {name}: not checked, {reason}")
    failing = [item for item in checks if not item.passed]
    if failing:
        problems = sum(len(item.problems) for item in failing)
        typer.echo(
            f"\n{counted(problems, 'problem')} in {counted(len(failing), 'Task')}. Fix them, "
            f"then run plural task check {failing[0].task} again."
        )
    elif checks:
        typer.echo(f"\n{counted(len(checks), 'Task')} checked, no problems.")
