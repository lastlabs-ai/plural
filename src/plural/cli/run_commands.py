"""``plural run`` and the Job, Trial, and review commands that follow it.

Runs are local unless ``--hosted`` is given; the selected scope never moves
a run. Local records live in ``.plural/jobs``; hosted ones in the bound
project. Show and rerun commands look locally first and label the result.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Literal

import typer

from plural.auth import Session
from plural.cli.common import (
    JSON_OPTION,
    emit,
    handled,
    project_studio,
    rows,
    session,
    signed_in,
    workspace,
)
from plural.execution.bootstrap import RUNTIME_VERSION_VARIABLE
from plural.jobs import JobResult, TrialResult, TrialSpec
from plural.project import ProjectError, Workspace
from plural.project.runs import (
    DEFAULT_HARNESS,
    RunPlan,
    RunRequest,
    find_local_trial,
    local_job,
    local_jobs,
    local_trial,
    plan_run,
    rerun_local_job,
    rerun_local_trial,
    run_local,
    submit_hosted,
)
from plural.studio import Studio

job_app = typer.Typer(help="List, inspect, and rerun Jobs.", no_args_is_help=True)
trial_app = typer.Typer(help="Inspect and rerun Trials.", no_args_is_help=True)
review_app = typer.Typer(help="List and submit human reviews.", no_args_is_help=True)


@handled
def run(
    task: str | None = typer.Option(None, "--task", "-t", help="Task to run."),
    benchmark: str | None = typer.Option(None, "--benchmark", "-b", help="Benchmark to run."),
    model: str | None = typer.Option(None, "--model", "-m", help="Catalog model id."),
    harness: str | None = typer.Option(
        None,
        "--harness",
        "-h",
        help=f"Harness for --model. Default: {DEFAULT_HARNESS} (Plural's built-in tool loop).",
    ),
    agent: str | None = typer.Option(None, "--agent", "-a", help="Saved Agent to run."),
    hosted: bool = typer.Option(
        False, "--hosted", help="Run on hosted infrastructure using pushed revisions."
    ),
    attempts: int | None = typer.Option(
        None, "--attempts", min=1, help="Advanced: Trials per Task (default 1)."
    ),
    concurrency: str = typer.Option(
        "auto",
        "--concurrency",
        "-n",
        help=(
            "Trials to run at once: a number, or auto to size it from this machine, "
            "the runtime, and where the model runs."
        ),
    ),
    plural_version: str | None = typer.Option(
        None,
        "--plural-version",
        help=(
            "Plural to install in Docker and remote sandboxes: a version, or latest. "
            "Default: this CLI's own code."
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Advanced: validate and show the plan without running."
    ),
    follow: bool = typer.Option(False, "--follow", help="With --hosted, stream progress."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run one Task or Benchmark with a model or a saved Agent. Every run is a new Job."""
    space = workspace()
    current = session()
    environ = _run_environ(current)
    if plural_version:
        environ[RUNTIME_VERSION_VARIABLE] = plural_version
    plan = plan_run(
        space,
        RunRequest(
            task=task,
            benchmark=benchmark,
            model=model,
            harness=harness,
            agent=agent,
            attempts=attempts,
            concurrency=_concurrency(concurrency),
            hosted=hosted,
        ),
        environ=environ,
    )
    if dry_run:
        payload = _plan_payload(plan, hosted=hosted)
        emit(payload, as_json=as_json, text=lambda: _print_plan(payload))
        return
    if hosted:
        studio, binding = project_studio(space, session())
        record = submit_hosted(space, studio, plan)
        job_id = str(record.get("id"))
        emit(
            {"location": "hosted", "project": binding.project_slug, **record},
            as_json=as_json,
            text=lambda: typer.echo(
                f"Submitted hosted Job {job_id} to project {binding.project_slug}. "
                f"Follow it with `plural job show {job_id} --follow`."
            ),
        )
        if follow:
            _follow_hosted(studio, job_id)
        return
    total = len(plan.job.plan.trials)
    typer.echo(
        f"Running {plan.source} with {plan.agent.name} ({plan.agent.model}) locally: "
        f"{total} trial(s), {_pace(plan)}.",
        err=as_json,
    )
    job_id, result = run_local(space, plan, environ=environ, progress=_progress(as_json, total))
    payload = {"location": "local", **local_job(space, job_id)}
    emit(payload, as_json=as_json, text=lambda: _print_result(job_id, result))


@job_app.command("list")
@handled
def job_list(
    local: bool = typer.Option(False, "--local", help="Only local Jobs."),
    hosted: bool = typer.Option(False, "--hosted", help="Only hosted Jobs."),
    as_json: bool = JSON_OPTION,
) -> None:
    """List Jobs, newest first, labeled local or hosted."""
    _exclusive(local, hosted)
    space = workspace()
    items: list[dict[str, Any]] = []
    if not hosted:
        items.extend(
            {
                "location": "local",
                "job_id": item["job_id"],
                "source": item["source"],
                "agent": item["agent"],
                "status": item["status"],
                "created_at": item["created_at"],
                "rerun_of": item.get("rerun_of_job_id"),
            }
            for item in local_jobs(space)
        )
    note = None
    if not local:
        studio = _hosted_studio(space, required=hosted)
        if studio is None:
            note = "Hosted Jobs not shown: this directory is not registered or you are signed out."
        else:
            items.extend(
                {
                    "location": "hosted",
                    "job_id": item.get("id"),
                    "source": item.get("name"),
                    "agent": "",
                    "status": item.get("status"),
                    "created_at": item.get("created_at"),
                    "rerun_of": item.get("rerun_of_job_id"),
                }
                for item in studio.jobs.list()
            )

    def text() -> None:
        if items:
            rows(
                (
                    (
                        item["job_id"],
                        item["location"],
                        item["status"],
                        item["source"],
                        item["created_at"] or "",
                    )
                    for item in items
                ),
                ("job", "where", "status", "source", "created"),
            )
        else:
            typer.echo("No Jobs yet. Start one with `plural run --task <name> --model <model>`.")
        if note:
            typer.echo(note)

    emit(items, as_json=as_json, text=text)


@job_app.command("show")
@handled
def job_show(
    job_id: str = typer.Argument(help="Job id."),
    follow: bool = typer.Option(False, "--follow", help="Stream progress until it finishes."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show a Job and its Trials (local first, then hosted)."""
    space = workspace()
    if (space.project.jobs_dir / job_id).is_dir():
        if follow:
            _follow_local(space, job_id)
        payload = {"location": "local", **local_job(space, job_id)}
        emit(payload, as_json=as_json, text=lambda: _print_job(payload))
        return
    studio = _hosted_studio(space, required=True)
    assert studio is not None
    if follow:
        _follow_hosted(studio, job_id)
    record = studio.jobs.get(job_id)
    trials = studio.jobs.trials(job_id)
    payload = {
        "location": "hosted",
        **record,
        "trials": [
            {
                "trial_id": item.get("id"),
                "status": item.get("status"),
                "task": item.get("task_name") or item.get("task_revision_id"),
                "attempt": item.get("attempt"),
                "score": item.get("score"),
                "error": item.get("error_message"),
            }
            for item in trials
        ],
    }
    emit(payload, as_json=as_json, text=lambda: _print_job(payload))


@job_app.command("rerun")
@handled
def job_rerun(
    job_id: str = typer.Argument(help="Job to run again with its original pinned inputs."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run a Job again with the exact inputs it used. Creates a new, linked Job."""
    space = workspace()
    if (space.project.jobs_dir / job_id).is_dir():
        new_id, result = rerun_local_job(
            space, job_id, environ=_run_environ(session()), progress=_progress(as_json)
        )
        payload = {"location": "local", **local_job(space, new_id)}
        emit(payload, as_json=as_json, text=lambda: _print_result(new_id, result))
        return
    studio = _hosted_studio(space, required=True)
    assert studio is not None
    record = studio.jobs.rerun(job_id, idempotency_key=uuid.uuid4().hex)
    emit(
        {"location": "hosted", **record},
        as_json=as_json,
        text=lambda: typer.echo(f"Submitted hosted Job {record.get('id')} (rerun of {job_id})."),
    )


@trial_app.command("show")
@handled
def trial_show(
    trial_id: str = typer.Argument(help="Trial id."),
    follow: bool = typer.Option(False, "--follow", help="Stream progress until it finishes."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show a Trial's result, Verifier evidence, and artifacts (local first, then hosted)."""
    space = workspace()
    try:
        job_id, _ = find_local_trial(space, trial_id)
    except ProjectError:
        job_id = None
    if job_id is not None:
        if follow:
            _follow_local(space, job_id, trial_id=trial_id)
        payload = local_trial(space, trial_id)
        emit(payload, as_json=as_json, text=lambda: _print_trial(payload))
        return
    studio = _hosted_studio(space, required=True)
    assert studio is not None
    if follow:
        for event in studio.trials.watch(trial_id):
            _print_event(event)
    record = studio.trials.get(trial_id)
    payload = {"location": "hosted", **record, "trial_id": record.get("id")}
    emit(payload, as_json=as_json, text=lambda: _print_trial(payload))


@trial_app.command("rerun")
@handled
def trial_rerun(
    trial_id: str = typer.Argument(help="Trial to run again."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run one Trial again with its pinned inputs, as a new one-Trial Job."""
    space = workspace()
    try:
        find_local_trial(space, trial_id)
        is_local = True
    except ProjectError:
        is_local = False
    if is_local:
        new_id, result = rerun_local_trial(
            space, trial_id, environ=_run_environ(session()), progress=_progress(as_json)
        )
        payload = {"location": "local", **local_job(space, new_id)}
        emit(payload, as_json=as_json, text=lambda: _print_result(new_id, result))
        return
    studio = _hosted_studio(space, required=True)
    assert studio is not None
    record = studio.trials.rerun(trial_id, idempotency_key=uuid.uuid4().hex)
    emit(
        {"location": "hosted", **record},
        as_json=as_json,
        text=lambda: typer.echo(
            f"Submitted hosted Job {record.get('id')} (rerun of trial {trial_id})."
        ),
    )


@trial_app.command("rescore")
def trial_rescore(trial_id: str = typer.Argument(help="Trial id.")) -> None:
    """Reserved: score a finished Trial again (not available yet)."""
    typer.echo(
        "Error: `plural trial rescore` is not available yet. Use `plural trial rerun "
        f"{trial_id}` to run it again.",
        err=True,
    )
    raise typer.Exit(2)


@review_app.command("list")
@handled
def review_list(
    hosted: bool = typer.Option(False, "--hosted", help="Hosted review assignments."),
    as_json: bool = JSON_OPTION,
) -> None:
    """List Trials waiting for a human score."""
    space = workspace()
    if hosted:
        studio = _hosted_studio(space, required=True)
        assert studio is not None
        items = studio.reviews.list(status="awaiting_review")
        emit(items, as_json=as_json, text=lambda: _print_hosted_reviews(items))
        return
    pending = []
    for job in local_jobs(space):
        result = _local_result(space, job["job_id"])
        if result is None:
            continue
        for trial in result.trials:
            waiting = [
                item.verifier_name
                for item in trial.verifier_results
                if item.status == "awaiting_review"
            ]
            if waiting:
                pending.append(
                    {
                        "job_id": job["job_id"],
                        "trial_id": trial.receipt.trial_id,
                        "verifiers": waiting,
                    }
                )

    def text() -> None:
        if not pending:
            typer.echo("No local Trials are waiting for review.")
            return
        rows(
            ((item["trial_id"], item["job_id"], ", ".join(item["verifiers"])) for item in pending),
            ("trial", "job", "verifiers"),
        )

    emit(pending, as_json=as_json, text=text)


@review_app.command("submit")
@handled
def review_submit(
    target: str = typer.Argument(help="Trial id, or a review assignment id with --hosted."),
    score: list[str] = typer.Option(
        ..., "--score", help="`criterion=value`, or a bare value for a one-criterion rubric."
    ),
    verifier: str | None = typer.Option(None, "--verifier", help="Human Verifier (local)."),
    feedback: str = typer.Option("", "--feedback", help="Notes for the record."),
    hosted: bool = typer.Option(False, "--hosted", help="Submit a hosted assignment."),
) -> None:
    """Record a human score. Submissions are append-only."""
    space = workspace()
    if hosted:
        studio = _hosted_studio(space, required=True)
        assert studio is not None
        studio.reviews.submit(
            target,
            scores=_scores(score, None),
            idempotency_key=uuid.uuid4().hex,
            feedback=feedback,
        )
        typer.echo(f"Submitted review {target}.")
        return
    from plural.execution.engine import JobRunner
    from plural.execution.store import JobStore

    job_id, _ = find_local_trial(space, target)
    store = JobStore(space.project.jobs_dir)
    spec = store.load_spec(job_id)
    humans = [
        item.verifier
        for task in spec.tasks
        for item in task.verifiers
        if item.verifier.kind == "human" and (verifier is None or item.verifier.name == verifier)
    ]
    names = sorted({item.name for item in humans})
    if len(names) != 1:
        raise ProjectError(
            "Name the human Verifier with --verifier."
            if names
            else f"Trial {target} has no human Verifier"
            + (f" named {verifier!r}." if verifier else ".")
        )
    human = next(item for item in humans if item.name == names[0])
    criteria = [criterion.name for criterion in getattr(human, "rubric", ())]
    JobRunner(spec, store=store).submit_review(
        target, names[0], _scores(score, criteria), feedback=feedback
    )
    typer.echo(f"Recorded review of trial {target} for verifier {names[0]}.")


def _scores(values: list[str], criteria: list[str] | None) -> dict[str, float]:
    scores: dict[str, float] = {}
    for item in values:
        name, separator, raw = item.partition("=")
        if not separator:
            if not criteria or len(criteria) != 1 or len(values) != 1:
                raise ProjectError("Use --score criterion=value for each rubric criterion.")
            name, raw = criteria[0], item
        try:
            scores[name.strip()] = float(raw)
        except ValueError:
            raise ProjectError(f"--score {item!r}: expected a number.") from None
    return scores


def _exclusive(local: bool, hosted: bool) -> None:
    if local and hosted:
        raise ProjectError("Choose --local or --hosted, not both.")


def _hosted_studio(space: Workspace, *, required: bool) -> Studio | None:
    current = session()
    if space.project.read_binding() is None or current.token is None:
        if required:
            signed_in(current)
            project_studio(space, current)
        return None
    return project_studio(space, current)[0]


def _run_environ(current: Session) -> dict[str, str]:
    """Process environment for a local run, with the gateway credential added.

    The model gateway accepts API keys, not browser logins; a login-only
    session needs PLURAL_API_KEY or a provider key such as OPENAI_API_KEY.
    The gateway is selected only with a Plural key, so a provider key is
    never sent to it.
    """
    environ = dict(os.environ)
    if current.api_key and not environ.get("PLURAL_API_KEY"):
        environ["PLURAL_API_KEY"] = current.api_key
    if environ.get("PLURAL_API_KEY"):
        environ.setdefault("PLURAL_GATEWAY_URL", current.api_url.rstrip("/") + "/v1")
    return environ


def _concurrency(value: str) -> int | Literal["auto"]:
    if value.strip().lower() == "auto":
        return "auto"
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise ProjectError(f"--concurrency {value!r}: expected auto or a number of at least 1.")
    return number


def _pace(plan: RunPlan) -> str:
    at_once = f"{plan.spec.concurrency} at a time"
    return f"{at_once} (auto: {plan.concurrency_reason})" if plan.concurrency_reason else at_once


def _progress(quiet: bool, total: int | None = None) -> Any:
    """Print each finished Trial with the Job's running tally.

    Trials finish out of order under concurrency; the tally is what is known so
    far, and the final aggregate applies the Benchmark's own scoring.
    """
    done = succeeded = failed = 0
    scores: list[float] = []

    def report(trial: TrialSpec, result: TrialResult) -> None:
        nonlocal done, succeeded, failed
        done += 1
        succeeded += result.status == "succeeded"
        failed += result.status == "failed"
        if result.score is not None:
            scores.append(result.score)
        if quiet:
            return
        score = "-" if result.score is None else f"{result.score:.3f}"
        mean = f"{sum(scores) / len(scores):.3f}" if scores else "-"
        count = f"{done}/{total}" if total else str(done)
        typer.echo(
            f"  [{count}] {trial.trial_id}  {trial.task_id}  {result.status}  score={score}"
            f"  | {succeeded} succeeded, {failed} failed, mean {mean}"
        )

    return report


def _plan_payload(plan: RunPlan, *, hosted: bool) -> dict[str, Any]:
    return {
        "location": "hosted" if hosted else "local",
        "source": str(plan.source),
        "agent": str(plan.agent_ref) if plan.agent_ref else plan.agent.name,
        "model": plan.agent.model,
        "harness": plan.harness,
        "concurrency": plan.spec.concurrency,
        "concurrency_reason": plan.concurrency_reason,
        "trials": [
            {"trial_id": item.trial_id, "task": item.task_id, "attempt": item.attempt}
            for item in plan.job.plan.trials
        ],
        "inputs": plan.pins,
    }


def _print_plan(payload: dict[str, Any]) -> None:
    typer.echo(
        f"Would run {payload['source']} with {payload['agent']} "
        f"({payload['model']}, harness {payload['harness']}) "
        f"{payload['location']}ly: {len(payload['trials'])} trial(s), "
        f"{payload['concurrency']} at a time"
        + (f" (auto: {payload['concurrency_reason']})." if payload["concurrency_reason"] else ".")
    )
    rows(
        (
            (name, pin["version"], pin["content_hash"][:19])
            for name, pin in payload["inputs"].items()
        ),
        ("input", "version", "content hash"),
    )


def _print_result(job_id: str, result: JobResult) -> None:
    typer.echo(f"Job {job_id} {result.status}.")
    for aggregate in result.aggregates:
        mean = "-" if aggregate.mean_score is None else f"{aggregate.mean_score:.3f}"
        typer.echo(
            f"  {aggregate.agent_name}: mean score {mean} over {aggregate.count} trial(s), "
            f"{aggregate.successes} succeeded"
        )
    typer.echo(f"Details: plural job show {job_id}")


def _print_job(payload: dict[str, Any]) -> None:
    job_id = payload.get("job_id") or payload.get("id")
    typer.echo(f"Job {job_id} ({payload['location']}) {payload.get('status')}")
    if payload.get("source"):
        typer.echo(f"  Source: {payload['source']}")
    if payload.get("model"):
        typer.echo(f"  Model:  {payload['model']} via {payload.get('harness')}")
    if payload.get("rerun_of_job_id"):
        typer.echo(f"  Rerun of job {payload['rerun_of_job_id']}")
    progress = payload.get("progress")
    if progress:
        typer.echo(
            f"  Progress: {progress['finished']}/{progress['planned']} finished, "
            f"{progress['running']} running, {progress['succeeded']} succeeded, "
            f"{progress['failed']} failed"
        )
    for aggregate in payload.get("aggregates") or []:
        if not isinstance(aggregate, dict) or "agent_name" not in aggregate:
            continue
        mean = aggregate.get("mean_score")
        typer.echo(
            f"  {aggregate['agent_name']}: mean score "
            f"{'-' if mean is None else f'{mean:.3f}'} over {aggregate['count']} trial(s), "
            f"coverage {aggregate.get('coverage', 0):.0%}"
        )
    trials = payload.get("trials") or []
    if trials:
        rows(
            (
                (
                    item["trial_id"],
                    item.get("task") or "",
                    item.get("status"),
                    "-" if item.get("score") is None else f"{item['score']:.3f}",
                )
                for item in trials
            ),
            ("trial", "task", "status", "score"),
        )


def _print_trial(payload: dict[str, Any]) -> None:
    typer.echo(f"Trial {payload['trial_id']} ({payload['location']}) {payload.get('status')}")
    for label, key in (
        ("Job", "job_id"),
        ("Task", "task"),
        ("Score", "score"),
        ("Error", "error"),
        ("Artifacts", "artifacts"),
        ("Logs", "logs"),
        ("Rerun of trial", "rerun_of_trial_id"),
    ):
        if payload.get(key) is not None:
            typer.echo(f"  {label + ':':<15} {payload[key]}")
    for verifier in payload.get("verifiers") or []:
        typer.echo(
            f"  Verifier {verifier.get('verifier_name')}: {verifier.get('status')} "
            f"score={verifier.get('score')}"
        )
        for line in verifier.get("evidence") or []:
            typer.echo(f"    - {line}")


def _print_hosted_reviews(items: list[dict[str, Any]]) -> None:
    if not items:
        typer.echo("No hosted reviews are waiting.")
        return
    rows(
        ((item.get("id"), item.get("trial_id"), item.get("verifier_name")) for item in items),
        ("assignment", "trial", "verifier"),
    )


def _print_event(event: Any) -> None:
    payload = event if isinstance(event, dict) else {}
    status = payload.get("status") or payload.get("kind") or ""
    trial = payload.get("trial_id") or ""
    typer.echo(
        f"{payload.get('sequence', ''):>5} {status:<16} {trial} {payload.get('message') or ''}"
    )


def _follow_local(space: Workspace, job_id: str, *, trial_id: str | None = None) -> None:
    from plural.execution.store import JobStore

    for event in JobStore(space.project.jobs_dir).events(job_id, follow=True):
        if trial_id is None or event.trial_id == trial_id:
            _print_event(event.model_dump(mode="json"))


def _follow_hosted(studio: Studio, job_id: str) -> None:
    for event in studio.jobs.watch(job_id):
        _print_event(event)


def _local_result(space: Workspace, job_id: str) -> JobResult | None:
    path = space.project.jobs_dir / job_id / "result.json"
    return JobResult.model_validate_json(path.read_text("utf-8")) if path.is_file() else None
