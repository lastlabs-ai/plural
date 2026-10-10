"""``plural rewards``: label stored Trials with hindsight rewarders and export training data.

Rewards live in each Trial's ``rewards.jsonl`` ledger, beside the trajectory.
``apply`` appends to it without rerunning anything; ``export`` joins it with
the trajectory and any TITO records.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from plural.cli.common import (
    JSON_OPTION,
    emit,
    handled,
    note,
    project_studio,
    session,
    signed_in,
    workspace,
)
from plural.errors import PluralError
from plural.jobs import TrialResult
from plural.project import ProjectError, Workspace
from plural.project.runs import RUN_RECORD, find_local_trial, finished_local_job
from plural.rewards import (
    LEDGER_FILE,
    RewardRecord,
    append_ledger,
    load_rewarder,
    read_ledger,
    training_export,
    trial_from_artifacts,
)

rewards_app = typer.Typer(
    help="Label stored Trials with hindsight rewarders and export training data.",
    no_args_is_help=True,
)


def _latest_artifacts(trial_dir: Path) -> Path:
    executions = sorted(
        (item for item in (trial_dir / "executions").glob("*") if item.is_dir()),
        key=lambda item: int(item.name) if item.name.isdigit() else -1,
    )
    if not executions:
        raise ProjectError(f"Trial {trial_dir.name} has no recorded execution.")
    return executions[-1] / "artifacts"


def _score(trial_dir: Path) -> float | None:
    path = trial_dir / "result.json"
    if not path.is_file():
        return None
    return TrialResult.model_validate_json(path.read_text("utf-8")).score


def _trial_dirs(space: Workspace, trials: list[str], job: str | None) -> list[Path]:
    if bool(trials) == bool(job):
        raise ProjectError("Pass --trial (any number of times) or --job, not both.")
    if job:
        root = space.project.jobs_dir / job / "trials"
        if not root.is_dir():
            raise ProjectError(f"No local Job {job!r} in {space.project.jobs_dir}.")
        return sorted(item for item in root.iterdir() if item.is_dir())
    return [find_local_trial(space, trial_id)[1] for trial_id in trials]


def _publish(space: Workspace, trial_dirs: list[Path]) -> tuple[int, str | None]:
    """Add new ledger records to the hosted Trials of Jobs that were pushed.

    Returns:
        How many records were new to the hosted ledgers, and why some could
        not be recorded, if any.
    """
    from plural.execution.report import publish_rewards
    from plural.execution.store import JobStore

    by_job: dict[str, set[str]] = {}
    for trial_dir in trial_dirs:
        by_job.setdefault(trial_dir.parent.parent.name, set()).add(trial_dir.name)
    try:
        pushed = {
            job_id: record.hosted_job_id
            for job_id in by_job
            if (space.project.jobs_dir / job_id / RUN_RECORD).is_file()
            and (record := finished_local_job(space, job_id)).hosted_job_id
        }
        if not pushed:
            return 0, None
        studio, _ = project_studio(space, signed_in(session()))
        store = JobStore(space.project.jobs_dir)
        return (
            sum(
                publish_rewards(studio, store, job_id, hosted_id, trial_ids=by_job[job_id])
                for job_id, hosted_id in pushed.items()
            ),
            None,
        )
    except (PluralError, ProjectError) as exc:
        return 0, f"The hosted project was not updated: {exc} Run this again to retry."


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


@rewards_app.command("apply")
@handled
def rewards_apply(
    rewarder: str = typer.Argument(help="The hindsight rewarder, as path.py:name."),
    trial: list[str] = typer.Option([], "--trial", help="A local Trial id. Repeatable."),
    job: str | None = typer.Option(None, "--job", help="Every Trial of this local Job."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run a hindsight rewarder on stored Trials and append its rewards to their ledgers."""
    space = workspace()
    function = load_rewarder(rewarder, space.project.root)
    applied: list[dict[str, Any]] = []
    for trial_dir in _trial_dirs(space, trial, job):
        artifacts = _latest_artifacts(trial_dir)
        view = trial_from_artifacts(artifacts, score=_score(trial_dir))
        view.trial_id = trial_dir.name
        records = function.apply(view)
        added = append_ledger(artifacts / LEDGER_FILE, records)
        applied.append({"trial_id": trial_dir.name, "records": len(records), "new_records": added})
    hosted, problem = _publish(space, _trial_dirs(space, trial, job))
    payload = {
        "rewarder": function.name,
        "version": function.version,
        "trials": applied,
        "hosted_records": hosted,
    }

    def text() -> None:
        for item in applied:
            known = item["records"] - item["new_records"]
            typer.echo(
                f"{item['trial_id']}: {item['records']} reward(s) from {function.name}"
                + (f", {known} already in its ledger" if known else "")
            )
        if hosted:
            typer.echo(f"Recorded {hosted} new reward(s) in the hosted project.")
        if problem:
            note(problem)

    emit(payload, as_json=as_json, text=text)


@rewards_app.command("show")
@handled
def rewards_show(
    trial_id: str = typer.Argument(help="A local Trial id."),
    as_json: bool = JSON_OPTION,
) -> None:
    """List a Trial's reward ledger."""
    _, trial_dir = find_local_trial(workspace(), trial_id)
    records = read_ledger(_latest_artifacts(trial_dir) / LEDGER_FILE)
    payload = [item.model_dump(mode="json") for item in records]

    def text() -> None:
        if not records:
            typer.echo("No rewards recorded.")
        for item in records:
            version = f"@{item.version}" if item.version else ""
            typer.echo(
                f"{item.target.kind:<5} {item.target.event_id:<6} {item.value:+.3f}  "
                f"{item.source}:{item.rewarder}{version}"
            )

    emit(payload, as_json=as_json, text=text)


def _rewarder_choice(values: list[str]) -> dict[str, str | None] | None:
    if not values:
        return None
    chosen: dict[str, str | None] = {}
    for value in values:
        name, _, version = value.partition("@")
        chosen[name] = version or None
    return chosen


@rewards_app.command("export")
@handled
def rewards_export(
    trial: list[str] = typer.Option([], "--trial", help="A local Trial id. Repeatable."),
    job: str | None = typer.Option(None, "--job", help="Every Trial of this local Job."),
    rewarder: list[str] = typer.Option(
        [], "--rewarder", help="Use only this rewarder, as name or name@version. Repeatable."
    ),
    aggregate: str = typer.Option("sum", help="Combine rewards on one target: sum, mean, last."),
    include_off_recording: bool = typer.Option(
        False, help="Keep rewards on steps a replayed App answered off its recording."
    ),
    out: Path = typer.Option(Path("training.jsonl"), "--out", help="Where to write JSONL."),
) -> None:
    """Write one training record per Trial: model turns with TITO tokens and their rewards."""
    if aggregate not in {"sum", "mean", "last"}:
        raise ProjectError("--aggregate must be sum, mean, or last.")
    space = workspace()
    lines = []
    for trial_dir in _trial_dirs(space, trial, job):
        artifacts = _latest_artifacts(trial_dir)
        ledger: list[RewardRecord] = read_ledger(artifacts / LEDGER_FILE)
        exported = training_export(
            _read_jsonl(artifacts / "episode.jsonl"),
            ledger,
            tito=_read_jsonl(artifacts / "tito.jsonl"),
            rewarders=_rewarder_choice(rewarder),
            aggregate=aggregate,  # type: ignore[arg-type]
            include_off_recording=include_off_recording,
        )
        lines.append(
            json.dumps(
                {"trial_id": trial_dir.name, "score": _score(trial_dir), **exported},
                sort_keys=True,
                default=str,
            )
        )
    out.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    typer.echo(f"Wrote {len(lines)} Trial(s) to {out}.")


__all__ = ["rewards_app"]
