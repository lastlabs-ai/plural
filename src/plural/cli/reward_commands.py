"""Rewards on stored Trials: ``plural verifier try|apply`` and ``plural rewards show|export``.

Rewards live in each Trial's ``rewards.jsonl`` ledger, beside the trajectory.
``plural verifier try`` runs a Verifier's hooks on stored Trials and prints what
it would give; ``plural verifier apply`` appends those rewards to the ledgers.
Neither runs the Agent. ``export`` joins a ledger with the trajectory and any
TITO records.
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
from plural.execution.replay import Replay, replay_verifier
from plural.execution.store import JobStore
from plural.jobs import TrialResult
from plural.project import ProjectError, Workspace
from plural.project.runs import RUN_RECORD, find_local_trial, finished_local_job
from plural.rewards import (
    LEDGER_FILE,
    RewardRecord,
    append_ledger,
    read_ledger,
    training_export,
)
from plural.verifiers import DeterministicVerifier, StepTask

rewards_app = typer.Typer(
    help=(
        "Show a Trial's rewards and export training data. Add rewards with `plural verifier apply`."
    ),
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


def _step_task(space: Workspace, trial_dir: Path) -> StepTask:
    """The Task a stored Trial worked on, as a replayed ``reward`` sees it."""
    name = ""
    try:
        name = TrialResult.model_validate_json(
            (trial_dir / "result.json").read_text("utf-8")
        ).receipt.task_pin.name
        spec = JobStore(space.project.jobs_dir).load_spec(trial_dir.parent.parent.name)
    except (OSError, ValueError):
        return StepTask(name=name)
    task = next((item for item in spec.tasks if item.task_id == name), None)
    if task is None:
        return StepTask(name=name)
    return StepTask(name=task.task_id, info=task.info, metadata=dict(task.metadata))


def _replays(
    name: str, trial: list[str], job: str | None
) -> tuple[Workspace, DeterministicVerifier, list[tuple[Path, Path, Replay]]]:
    space = workspace()
    verifier = space.get("verifier", name)
    if not isinstance(verifier, DeterministicVerifier):
        raise ProjectError(
            f"Verifier {name!r} is a {verifier.kind} Verifier. Only code Verifiers "
            "(kind: deterministic) run on stored Trials."
        )
    replays = []
    for trial_dir in _trial_dirs(space, trial, job):
        artifacts = _latest_artifacts(trial_dir)
        replay = replay_verifier(
            verifier,
            artifacts,
            task=_step_task(space, trial_dir),
            trial_id=trial_dir.name,
            score=_score(trial_dir),
        )
        replays.append((trial_dir, artifacts, replay))
    return space, verifier, replays


def _summary(replay: Replay) -> dict[str, Any]:
    step = [item.value for item in replay.rewards if item.source == "step"]
    hindsight = [item.value for item in replay.rewards if item.source == "hindsight"]
    return {
        "score": replay.output.score if replay.output else None,
        "step_rewards": len(step),
        "step_total": sum(step),
        "hindsight_rewards": len(hindsight),
        "hindsight_total": sum(hindsight),
        "problems": replay.problems,
    }


@handled
def verifier_try(
    name: str = typer.Argument(help="The Verifier, by name."),
    trial: list[str] = typer.Option([], "--trial", help="A local Trial id. Repeatable."),
    job: str | None = typer.Option(None, "--job", help="Every Trial of this local Job."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run a Verifier on stored Trials and print what it gives, without saving anything.

    Its reward runs again on each recorded step, its hindsight on the finished
    trajectory, and a Python check on the stored episode. Edit the Verifier and
    run this again to see the difference; the Agent is not run.
    """
    _, verifier, replays = _replays(name, trial, job)
    payload = {
        "verifier": verifier.name,
        "version": verifier.version,
        "trials": [
            {
                "trial_id": trial_dir.name,
                **_summary(replay),
                "rewards": [item.model_dump(mode="json") for item in replay.rewards],
            }
            for trial_dir, _, replay in replays
        ],
    }

    def text() -> None:
        for trial_dir, _, replay in replays:
            summary = _summary(replay)
            score = "" if summary["score"] is None else f"score {summary['score']:g}, "
            typer.echo(
                f"{trial_dir.name}: {score}{summary['step_rewards']} step reward(s) "
                f"totalling {summary['step_total']:+g}"
                + (
                    f", {summary['hindsight_rewards']} hindsight totalling "
                    f"{summary['hindsight_total']:+g}"
                    if replay.rewards and summary["hindsight_rewards"]
                    else ""
                )
            )
            for item in replay.rewards:
                typer.echo(
                    f"  {item.target.kind:<5} {item.target.event_id:<6} {item.value:+.3f}  "
                    f"{item.source}"
                )
            for problem in replay.problems:
                note(problem)

    emit(payload, as_json=as_json, text=text)


@handled
def verifier_apply(
    name: str = typer.Argument(help="The Verifier, by name."),
    trial: list[str] = typer.Option([], "--trial", help="A local Trial id. Repeatable."),
    job: str | None = typer.Option(None, "--job", help="Every Trial of this local Job."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run a Verifier on stored Trials and add its rewards to their ledgers.

    Records are kept under the Verifier's name and version. A Trial that already
    has rewards from this version is left as it is: bump the Verifier's version
    when its logic changes, so an export can choose which labels to use. Pushed
    Jobs get the new records in the hosted project too.
    """
    space, verifier, replays = _replays(name, trial, job)
    applied: list[dict[str, Any]] = []
    for trial_dir, artifacts, replay in replays:
        existing = {
            item.source
            for item in read_ledger(artifacts / LEDGER_FILE)
            if item.verifier == verifier.name and item.version == verifier.version
        }
        records = [item for item in replay.rewards if item.source not in existing]
        added = append_ledger(artifacts / LEDGER_FILE, records)
        applied.append(
            {
                "trial_id": trial_dir.name,
                "records": len(records),
                "new_records": added,
                "skipped": sorted(existing & {item.source for item in replay.rewards}),
                "problems": replay.problems,
            }
        )
    hosted, problem = _publish(space, [trial_dir for trial_dir, _, _ in replays])
    payload = {
        "verifier": verifier.name,
        "version": verifier.version,
        "trials": applied,
        "hosted_records": hosted,
    }

    def text() -> None:
        for item in applied:
            skipped = (
                f"; {', '.join(item['skipped'])} rewards from version "
                f"{verifier.version!r} were already there"
                if item["skipped"]
                else ""
            )
            typer.echo(f"{item['trial_id']}: added {item['new_records']} reward(s){skipped}")
            for message in item["problems"]:
                note(message)
        if any(item["skipped"] for item in applied):
            note("Bump the Verifier's version to record new labels beside the old ones.")
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
                f"{item.source}:{item.verifier}{version}"
            )

    emit(payload, as_json=as_json, text=text)


def _verifier_choice(values: list[str]) -> dict[str, str | None] | None:
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
    verifier: list[str] = typer.Option(
        [], "--verifier", help="Use only this verifier, as name or name@version. Repeatable."
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
            verifiers=_verifier_choice(verifier),
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
