"""``plural job inspect``, ``plural trial ask``, ``plural job report``, and ``plural agent revise``.

Each is a verb in an existing command group. The Inspector itself is an Agent
built on Plural (``plural.inspector``); these commands run it, read what it
concluded, and turn a confirmed Finding into a new Agent version.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Literal

import httpx
import typer

from plural.auth import AuthHTTPError
from plural.cli.common import JSON_OPTION, counted, emit, handled, note, project_studio, session
from plural.cli.common import workspace as current_workspace
from plural.cli.run_commands import _progress, _run_environ
from plural.errors import PluralError
from plural.inspector.findings import InspectionRecord, breakdown
from plural.inspector.hosted import hosted_job_id, upload_inspection, upload_report
from plural.inspector.report import SUMMARY_MODEL, build_report, save_report, write_summary
from plural.inspector.revise import revise_agent
from plural.inspector.run import DEFAULT_BUDGET_USD, ask_trial, inspect_job
from plural.project import ProjectError, Workspace
from plural.project.runs import finished_local_job
from plural.studio import Studio

DEPTH_HELP = "quick: no forks. standard: a fork or two per Agent cause. deep: fork every cause."


@handled
def job_inspect(
    job_id: str = typer.Argument(help="A finished local Job."),
    depth: str = typer.Option("standard", "--depth", help=DEPTH_HELP),
    budget_usd: float = typer.Option(
        DEFAULT_BUDGET_USD, "--budget-usd", min=0, help="What forks may spend in all, in USD."
    ),
    model: str | None = typer.Option(None, "--model", help="The Inspector's model."),
    trial: list[str] = typer.Option(
        [], "--trial", help="Inspect only this failed Trial. Repeatable."
    ),
    concurrency: int = typer.Option(4, "--concurrency", min=1, help="Trials inspected at once."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Find out why a Job's Trials failed: one Finding per failed dev Trial.

    The Inspector reads each failed Trial's evidence, names its critical step and
    a cause (model, context, tools, instructions, Harness, environment, grader,
    task, integrity), and tests an Agent cause by forking the Trial with the
    cause removed. Held-out Trials are never looked at. Findings are saved beside
    the Job, and on the hosted Job when it was recorded.
    """
    if depth not in ("quick", "standard", "deep"):
        raise ProjectError("--depth is quick, standard, or deep.")
    space = current_workspace()
    finished_local_job(space, job_id)
    environ = _run_environ(session())
    studio = _fork_studio(space) if depth != "quick" else None
    if depth != "quick" and studio is None:
        note(
            "Forks are off: they run with a key minted for this inspection alone, which "
            "needs you signed in with a project selected (plural auth scope --project)."
        )
    record = inspect_job(
        space,
        job_id,
        depth=_depth(depth),
        budget_usd=budget_usd,
        environ=environ,
        model=model,
        trial_ids=trial,
        concurrency=concurrency,
        progress=_progress(as_json),
        studio=studio,
    )
    hosted = _upload(space, lambda studio: upload_inspection(space, studio, record), job_id)
    payload = _inspection_view(record) | {"hosted_job_id": hosted}
    emit(payload, as_json=as_json, text=lambda: _print_inspection(record))


@handled
def trial_ask(
    trial_id: str = typer.Argument(help="A local Trial."),
    question: str = typer.Argument(help="What to ask about it."),
    model: str | None = typer.Option(None, "--model", help="The Inspector's model."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Ask the Inspector one question about a Trial, answered from its evidence."""
    space = current_workspace()
    answer = ask_trial(
        space,
        trial_id,
        question,
        environ=_run_environ(session()),
        model=model,
        progress=_progress(True),
    )
    emit(answer, as_json=as_json, text=lambda: typer.echo(answer["answer"]))


@handled
def job_report(
    job_id: str = typer.Argument(help="A finished local Job."),
    compare: str | None = typer.Option(
        None, "--compare", help="A Job to compare with: paired, on dev and held-out Tasks."
    ),
    findings: bool = typer.Option(
        False, "--findings", help="List each Finding, not only the breakdown by cause."
    ),
    summary: bool = typer.Option(
        False, "--summary", help="Have a model write a summary that cites the computed numbers."
    ),
    model: str = typer.Option(SUMMARY_MODEL, "--model", help="The summary's model."),
    as_json: bool = JSON_OPTION,
) -> None:
    """How an Agent performs, why it fails, what changed, and why to trust the numbers.

    Code computes every number, each with the Trials it came from. A summary,
    when asked for, may only cite those numbers; one that writes its own is
    rejected. Writes report.md and report.json beside the Job.
    """
    space = current_workspace()
    finished_local_job(space, job_id)
    if compare is not None:
        finished_local_job(space, compare)
    report = build_report(space, job_id, compare=compare, findings=findings)
    if summary:
        report = write_summary(report, _run_environ(session()), model=model)
    path = save_report(space.project.jobs_dir / job_id, report)
    hosted = _upload(space, lambda studio: upload_report(space, studio, report), job_id)
    payload = {
        **report.model_dump(mode="json"),
        "path": str(path),
        "hosted_job_id": hosted,
    }

    def text() -> None:
        typer.echo(path.read_text("utf-8"))
        for problem in report.summary_problems:
            note(f"No summary: {problem}.")
        typer.echo(f"Written to {path}.")

    emit(payload, as_json=as_json, text=text)


@handled
def agent_revise(
    name: str = typer.Argument(help="The Agent, by name."),
    from_finding: str = typer.Option(
        ..., "--from-finding", help="A confirmed Finding, such as F1."
    ),
    job: str | None = typer.Option(
        None, "--job", help="The inspected Job; the latest one with the Finding by default."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Apply a confirmed Finding's change to an Agent, as a new version.

    The minor version goes up and CHANGELOG.md beside agent.yaml records the
    Finding and the forks that confirmed it. For an External Agent, whose code
    Plural can't change, fixes/F1.md is written for its team instead. Prove it
    with a Job on the dev Tasks, then the held-out Tasks, and
    plural job report NEW --compare OLD.
    """
    space = current_workspace()
    revision = revise_agent(space, name, from_finding, job_id=job)

    def text() -> None:
        if revision.version is None:
            typer.echo(f"{name} is an External Agent. Wrote {revision.path} for its team.")
            return
        typer.echo(f"{name} {revision.previous} -> {revision.version}:")
        for item in revision.changed:
            typer.echo(f"  {item}")
        typer.echo(
            f"Next: plural run --benchmark BENCHMARK --agent {name}, then "
            "plural job report NEW_JOB --compare OLD_JOB."
        )

    emit(revision.as_dict(), as_json=as_json, text=text)


def _depth(value: str) -> Literal["quick", "standard", "deep"]:
    if value == "quick":
        return "quick"
    if value == "deep":
        return "deep"
    return "standard"


def _fork_studio(space: Workspace) -> Studio | None:
    """Hosted access to mint an inspection's fork key, or ``None`` when there is none."""
    current = session()
    if current.token is None and not current.api_key:
        return None
    if space.project.read_binding() is not None:
        with suppress(PluralError, ProjectError):
            return project_studio(space, current)[0]
        return None
    return current.studio() if current.project else None


def _upload(space: Workspace, send: Any, job_id: str) -> str | None:
    if hosted_job_id(space, job_id) is None:
        return None
    current = session()
    if current.token is None and not current.api_key:
        note("The Job is recorded, but you aren't signed in, so the hosted Job wasn't updated.")
        return None
    try:
        studio, _ = project_studio(space, current)
        return send(studio)  # type: ignore[no-any-return]
    except (PluralError, AuthHTTPError, httpx.HTTPError) as exc:
        note(f"Saved locally; the hosted Job wasn't updated: {exc}")
        return None


def _inspection_view(record: InspectionRecord) -> dict[str, Any]:
    return {
        **record.model_dump(mode="json"),
        "breakdown": [row.model_dump(mode="json") for row in breakdown(record)],
    }


def _print_inspection(record: InspectionRecord) -> None:
    looked = len({item.trial_id for item in record.findings}) + len(record.uninspected)
    typer.echo(
        f"Inspected {looked} of {counted(record.failed, 'failed Trial')} of Job "
        f"{record.job_id} ({record.depth}), ${record.cost_usd:.2f}:"
    )
    for row in breakdown(record):
        share = f"{row.share:.0%}" if row.share is not None else "n/a"
        typer.echo(
            f"  {row.cause:<13} {len(row.trial_ids):>3}  {share:>4}  {row.confirmed} confirmed"
        )
    for item in record.findings:
        step = "no critical step" if item.critical_step is None else f"step {item.critical_step}"
        gates = f", explains {', '.join(item.gates)}" if item.gates else ""
        typer.echo(
            f"{item.finding_id} {item.trial_id} {item.task}: {item.cause}, {item.status}, "
            f"{step}{gates}"
        )
        typer.echo(f"   {item.summary}")
        for test in item.forks:
            judged = f" on {', '.join(test.gates)}" if test.gates else ""
            typer.echo(
                f"   fork {test.test_id} ({test.job_id}){judged}: {test.verdict.replace('_', ' ')}"
            )
    if record.uninspected:
        note(f"No Finding for {', '.join(record.uninspected)}.")


__all__ = ["agent_revise", "job_inspect", "job_report", "trial_ask"]
