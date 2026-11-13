"""``plural eval``: evaluate an Agent and improve it, one step at a time."""

from __future__ import annotations

import typer

from plural.cli.common import JSON_OPTION, emit, handled, heading, muted
from plural.evaluation import EvalStatus, eval_status

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
