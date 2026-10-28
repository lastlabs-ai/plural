"""``plural run`` and the Job, Trial, and review commands that follow it.

Every Job runs from this machine, in the Runtime each Environment declares;
the selected scope never moves a run. Local records live in ``.plural/jobs``.
``--record`` also records a run in the hosted project as it happens, and
``plural job record`` records a finished one. Show commands look locally first
and label the result.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import ValidationError

from plural.agents import AgentBinding
from plural.apps.mcp import use_credential_source
from plural.auth import Session
from plural.cli.common import (
    JSON_OPTION,
    REF_HELP,
    alias,
    counted,
    deprecated,
    emit,
    handled,
    project_studio,
    relative,
    rows,
    session,
    signed_in,
    workspace,
)
from plural.cli.credential_commands import account_credential_source, stored_credentials
from plural.cli.credits import CreditWatch
from plural.cli.runtime_commands import _project_studio
from plural.errors import PluralError
from plural.execution.bootstrap import RUNTIME_VERSION_VARIABLE
from plural.execution.episode_server import EpisodeServerOptions
from plural.jobs import JobResult, JobSpec, TrialResult, TrialSpec
from plural.local_models import LocalModelError, LocalModelIdentity, review_local_models
from plural.project import ProjectError, Workspace
from plural.project.layout import (
    AGENT,
    BENCHMARK,
    HARNESS,
    TASK,
    Project,
    ResourceRef,
    split_version,
)
from plural.project.runs import (
    DEFAULT_HARNESS,
    CredentialSource,
    RunPlan,
    RunRequest,
    Tracking,
    find_local_trial,
    finished_local_job,
    local_job,
    local_job_spec,
    local_jobs,
    local_trial,
    plan_run,
    push_local_job,
    push_run_inputs,
    rerun_local_job,
    rerun_local_trial,
    run_local,
    run_roots,
)
from plural.project.sync import REBUILT_NOTE, PullStep, PushStep, pull_missing
from plural.project.versions import holds_version, version_workspace, versioned
from plural.sandbox import DaytonaProvider, default_registry
from plural.sandbox.catalog import runtime_provider
from plural.sandbox.hosted_daytona import HostedDaytonaAdapter
from plural.studio import Studio

job_app = typer.Typer(help="List, inspect, and rerun Jobs.", no_args_is_help=True)
trial_app = typer.Typer(help="Inspect and rerun Trials.", no_args_is_help=True)
review_app = typer.Typer(help="List and submit human reviews.", no_args_is_help=True)

HOSTED_RUNS = (
    "Plural runs every Job from your machine; it does not run Jobs on its servers. Add "
    "--record to record the Job in your hosted project as it runs, and set an "
    "Environment's runtime to a cloud provider such as daytona to run its Trials in "
    "remote sandboxes."
)


def _not_here(kind: str, item_id: str) -> str:
    return (
        f"{kind} {item_id} did not run from this checkout, so it cannot be rerun here. "
        "Rerun it from the checkout that ran it, or start a new Job with "
        "`plural run ... --record`; NAME@REF pins the exact pushed revisions."
    )


TRACK_OPTION = typer.Option(False, "--track", hidden=True)


@handled
def run(
    task: str | None = typer.Option(None, "--task", "-t", help=f"Task to run: {REF_HELP}."),
    benchmark: str | None = typer.Option(
        None,
        "--benchmark",
        "-b",
        help=f"Benchmark to run: {REF_HELP}.",
    ),
    models: list[str] | None = typer.Option(None, "--model", "-m", help="Catalog model id."),
    harness: str | None = typer.Option(
        None,
        "--harness",
        help=f"Harness for --model. Default: {DEFAULT_HARNESS} (Plural's built-in tool loop).",
    ),
    agents: list[str] | None = typer.Option(
        None, "--agent", "-a", help=f"Saved Agent to run: {REF_HELP}."
    ),
    hosted: bool = typer.Option(False, "--hosted", hidden=True),
    record: bool = typer.Option(
        False,
        "--record",
        help=(
            "Run here, and record the Job in the hosted project as it runs. Inputs the "
            "hosted project lacks are pushed first."
        ),
    ),
    track: bool = TRACK_OPTION,
    evaluation_track: str | None = typer.Option(
        None,
        "--evaluation-track",
        help=(
            "Run a Benchmark under one of its evaluation tracks, by id, so the results "
            "can be published. Implies --record, and uses the track's attempts."
        ),
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
    follow: bool = typer.Option(False, "--follow", hidden=True),
    listen: str = typer.Option(
        "127.0.0.1:0",
        "--listen",
        help="For an external Agent: HOST:PORT where this run serves its episodes.",
    ),
    public_url: str | None = typer.Option(
        None,
        "--public-url",
        help="For an external Agent: the https base URL it reaches this run at, when that "
        "differs from --listen, such as behind a proxy.",
    ),
    tls_cert: Path | None = typer.Option(
        None, "--tls-cert", help="For an external Agent: the certificate to serve https with."
    ),
    tls_key: Path | None = typer.Option(
        None, "--tls-key", help="For an external Agent: the key of --tls-cert."
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Use an endpoint Agent's model without asking, even one you have not accepted.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run one Task or Benchmark with a model or a saved Agent. Every run is a new Job.

    The Job runs from this machine. Its Trials execute in the Runtime each
    Environment declares: local, docker, or a cloud sandbox such as daytona.
    It stays local unless you pass --record.

    NAME@REF runs that exact pushed revision even after your files have
    moved on. It is restored under .plural/versions without touching them.

    For an Agent with its own endpoint, the run first asks the server what
    model it is running and shows it with a fingerprint. Accept it once and
    later runs of the same model go ahead; if the fingerprint changes, you
    are asked again.
    """
    if hosted or follow:
        raise ProjectError(HOSTED_RUNS)
    model, agent = _one(models, "--model"), _one(agents, "--agent")
    try:
        episode_server = EpisodeServerOptions(
            listen=listen, public_url=public_url, tls_cert=tls_cert, tls_key=tls_key
        )
    except ValidationError as exc:
        raise ProjectError(exc.errors()[0]["msg"].removeprefix("Value error, ")) from None
    record = _recording(record, track) or bool(evaluation_track and not dry_run)
    space = workspace()
    current = session()
    environ = _run_environ(current)
    if plural_version:
        environ[RUNTIME_VERSION_VARIABLE] = plural_version
    task, task_version = _split(task, TASK.label)
    benchmark, benchmark_version = _split(benchmark, BENCHMARK.label)
    agent, agent_version = _split(agent, AGENT.label)
    request = RunRequest(
        task=task,
        benchmark=benchmark,
        model=model,
        harness=harness,
        agent=agent,
        attempts=attempts,
        concurrency=_concurrency(concurrency),
        evaluation_track=evaluation_track,
    )
    requested = {
        ResourceRef(kind.name, name): version
        for kind, name, version in (
            (TASK, task, task_version),
            (BENCHMARK, benchmark, benchmark_version),
            (AGENT, agent, agent_version),
        )
        if name and version
    }
    retained = {
        ref: version for ref, version in requested.items() if not holds_version(space, ref, version)
    }
    if retained:
        studio, binding = project_studio(space, current)
        space = version_workspace(
            space, studio, binding, retained, carry=_carried(space, request, retained)
        )
        _print_retained(retained, space, err=as_json)
    root = space.project.root
    if not dry_run:
        pulled = _pull_run_sources(space, request)
        if pulled:
            _print_pulled(pulled, err=as_json)
            space = Workspace(Project.at(root))
    use_credential_source(account_credential_source())
    plan = plan_run(space, request, environ=environ)
    unfinished = space.unfinished(run_roots(plan))
    if unfinished and record:
        raise ProjectError(
            "--record records this run in the hosted project, and these files are unfinished. "
            "Finish them and delete each PLURAL-TODO line, or run without --record to try it.",
            unfinished,
        )
    for marker in unfinished:
        typer.echo(f"Unfinished: {marker}", err=True)
    if dry_run:
        payload = _plan_payload(plan)
        emit(payload, as_json=as_json, text=lambda: _print_plan(payload))
        return
    tracking = None
    if record:
        studio, binding = project_studio(space, current)
        pushed = push_run_inputs(space, studio, binding, plan)
        if pushed:
            _print_pushed(pushed, err=as_json)
            space = Workspace(Project.at(root))
            plan = plan_run(space, request, environ=environ)
        tracking = Tracking(studio)
    total = len(plan.job.plan.trials)
    revision = plan.pins[str(plan.source)]["revision"]
    typer.echo(
        f"Running {plan.source}{'' if revision == 'local' else f' {revision}'} "
        f"with {plan.agent.name} ({plan.agent.model}) locally: "
        f"{counted(total, 'Trial')}, {_pace(plan)}."
        + (" Recording it in the hosted project as it runs." if tracking else ""),
        err=as_json,
    )
    _runtime_credentials(space, plan, err=as_json)
    _project_secrets(space, plan.spec, environ, err=as_json)
    identities = _review_local_models(plan.spec.agents, environ, yes=yes, err=as_json)
    with _credit_watch(current, environ, err=as_json):
        job_id, result = run_local(
            space,
            plan,
            environ=environ,
            progress=_progress(as_json, total),
            tracking=tracking,
            credential_source=_stored_credentials(as_json),
            episode_server=episode_server,
            model_identities=identities,
        )
    _finish_local(space, job_id, result, tracking, as_json=as_json)


def _interactive() -> bool:
    return sys.stdin.isatty()


def _review_local_models(
    agents: Sequence[AgentBinding], environ: Mapping[str, str], *, yes: bool, err: bool
) -> dict[str, LocalModelIdentity]:
    """Show each endpoint Agent's model and ask, once per fingerprint, to use it.

    Returns:
        The identities by Agent name.

    Raises:
        ProjectError: When a model is unreachable or not accepted.
    """

    def show(line: str) -> None:
        typer.echo(line, err=err)

    def decide(
        name: str,
        identity: LocalModelIdentity,
        status: Literal["new", "known", "changed"],
        record: dict[str, Any] | None,
    ) -> Literal["confirmed", "known", "allowed"]:
        accepted = str((record or {}).get("accepted_at", ""))[:10]
        if status == "known":
            show(
                f"{name}: {identity.weights or identity.requested}, {identity.fingerprint}, "
                f"as you accepted on {accepted}."
            )
            for warning in identity.warnings:
                show(f"  warning: {warning}")
            return "known"
        if status == "changed" and record is not None:
            show(f"WARNING: THE MODEL BEHIND AGENT {name.upper()} HAS CHANGED.")
            show(
                f"When you accepted it on {accepted} it was "
                f"{record.get('weights') or 'unknown weights'}, {record.get('fingerprint')}. "
                "It is now:"
            )
        else:
            show(f"Agent {name} runs a local model you have not accepted yet:")
        for line in identity.describe():
            show(f"  {line}")
        if yes:
            return "allowed"
        if not _interactive():
            raise ProjectError(
                "Check that this is the model you mean, then pass --yes to run without a prompt."
            )
        if not typer.confirm("Is this the model you mean to evaluate?", default=False):
            raise ProjectError(
                "Nothing ran. Point the Agent at the model you mean, or load it on the server."
            )
        return "confirmed"

    try:
        return review_local_models(agents, environ, decide)
    except LocalModelError as exc:
        raise ProjectError(str(exc)) from None


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
                "hosted_job_id": item.get("hosted_job_id"),
            }
            for item in local_jobs(space)
        )
    recorded = {item["hosted_job_id"] for item in items if item.get("hosted_job_id")}
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
                    "executor": item.get("executor") or "hosted",
                    "client_job_id": item.get("client_job_id"),
                }
                for item in studio.jobs.list()
                if item.get("id") not in recorded
            )

    def text() -> None:
        if items:
            rows(
                (
                    (
                        item["job_id"],
                        _where(item),
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
    studio = _hosted_or_missing(space, "Job", job_id)
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


@job_app.command("record")
@handled
def job_record(
    job_id: str = typer.Argument(help="Finished local Job to record in the hosted project."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Record a finished local Job in the hosted project, with every Trial execution.

    The hosted Job pins the pushed revisions the local Job ran, so push those
    first. Recording again, or recording a Job that ran with --record, uploads
    only what the hosted Job does not hold yet.
    """
    space = workspace()
    finished_local_job(space, job_id)
    studio, binding = project_studio(space, session())
    pushed = push_local_job(space, studio, job_id)
    hosted = studio.jobs.get(pushed.job.job_id)
    payload = {
        "job_id": job_id,
        "hosted_job_id": pushed.job.job_id,
        "project": binding.project_slug,
        "executions": pushed.executions,
        "status": hosted.get("status"),
    }
    emit(
        payload,
        as_json=as_json,
        text=lambda: typer.echo(
            f"Recorded local Job {job_id} as hosted Job {pushed.job.job_id} in project "
            f"{binding.project_slug}: {counted(pushed.executions, 'execution')}, "
            f"{hosted.get('status')}."
        ),
    )


job_app.command("push", hidden=True)(alias(job_record, "plural job push", "plural job record"))


@job_app.command("rerun")
@handled
def job_rerun(
    job_id: str = typer.Argument(help="Job to run again with its original pinned inputs."),
    record: bool = typer.Option(
        False, "--record", help="Record the rerun in the hosted project as it runs."
    ),
    track: bool = TRACK_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Run a Job again with the exact inputs it used. Creates a new, linked Job."""
    space = workspace()
    if (space.project.jobs_dir / job_id).is_dir():
        tracking = _tracking(space, session()) if _recording(record, track) else None
        environ = _project_secrets(
            space, local_job_spec(space, job_id), _run_environ(session()), err=as_json
        )
        with _credit_watch(session(), environ, err=as_json):
            new_id, result = rerun_local_job(
                space,
                job_id,
                environ=environ,
                progress=_progress(as_json),
                tracking=tracking,
                credential_source=_stored_credentials(as_json),
            )
        _finish_local(space, new_id, result, tracking, as_json=as_json)
        return
    raise ProjectError(_not_here("Job", job_id))


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
    studio = _hosted_or_missing(space, "Trial", trial_id)
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
    record: bool = typer.Option(
        False, "--record", help="Record the rerun in the hosted project as it runs."
    ),
    track: bool = TRACK_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Run one Trial again with its pinned inputs, as a new one-Trial Job."""
    space = workspace()
    try:
        owner, _ = find_local_trial(space, trial_id)
    except ProjectError:
        owner = None
    if owner is not None:
        tracking = _tracking(space, session()) if _recording(record, track) else None
        environ = _project_secrets(
            space, local_job_spec(space, owner), _run_environ(session()), err=as_json
        )
        with _credit_watch(session(), environ, err=as_json):
            new_id, result = rerun_local_trial(
                space,
                trial_id,
                environ=environ,
                progress=_progress(as_json),
                tracking=tracking,
                credential_source=_stored_credentials(as_json),
            )
        _finish_local(space, new_id, result, tracking, as_json=as_json)
        return
    raise ProjectError(_not_here("Trial", trial_id))


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


def _where(item: dict[str, Any]) -> str:
    if item.get("hosted_job_id"):
        return f"local, recorded as {item['hosted_job_id']}"
    if item.get("executor") == "client":
        return "hosted, run by a client"
    return str(item["location"])


def _exclusive(local: bool, hosted: bool) -> None:
    if local and hosted:
        raise ProjectError("Choose --local or --hosted, not both.")


def _pull_run_sources(space: Workspace, request: RunRequest) -> list[PullStep]:
    """Pull the named Task, Benchmark, or Agent when only the hosted project has it."""
    refs = [
        ResourceRef(TASK.name, request.task)
        if request.task
        else ResourceRef(BENCHMARK.name, str(request.benchmark))
    ]
    if request.agent:
        refs.append(ResourceRef(AGENT.name, request.agent))
    if all(space.project.manifest_path(ref).is_file() for ref in refs):
        return []
    studio = _hosted_studio(space, required=False)
    binding = space.project.read_binding()
    if studio is None or binding is None:
        return []
    return pull_missing(space, studio, refs, project_id=binding.project_id)


def _split(reference: str | None, what: str) -> tuple[str | None, str | None]:
    if reference is None:
        return None, None
    return split_version(reference, what)


def _carried(
    space: Workspace, request: RunRequest, retained: dict[ResourceRef, str]
) -> list[ResourceRef]:
    """Working-copy resources a run against retained versions still uses."""
    refs = []
    if request.agent:
        refs.append(ResourceRef(AGENT.name, request.agent))
    if request.harness:
        refs.append(ResourceRef(HARNESS.name, request.harness))
    return [ref for ref in refs if ref not in retained and space.project.has(ref)]


def _print_retained(retained: dict[ResourceRef, str], space: Workspace, *, err: bool) -> None:
    typer.echo("Using retained revisions from the hosted project:", err=err)
    for ref, version in sorted(retained.items()):
        typer.echo(f"  {versioned(ref, version)}", err=err)
    where = relative(space.project.root, space.project.root.parents[2])
    typer.echo(f"Restored under {where}; your working copy is unchanged.", err=err)


def _print_pulled(steps: list[PullStep], *, err: bool) -> None:
    typer.echo("Pulled from the hosted project, since this project did not have them:", err=err)
    for step in steps:
        typer.echo(f"  {step.ref} {step.label}", err=err)
    if any(step.rebuilt for step in steps):
        typer.echo(REBUILT_NOTE, err=err)


def _hosted_studio(space: Workspace, *, required: bool) -> Studio | None:
    current = session()
    if space.project.read_binding() is None or current.token is None:
        if required:
            signed_in(current)
            project_studio(space, current)
        return None
    return project_studio(space, current)[0]


def _hosted_or_missing(space: Workspace, kind: str, item_id: str) -> Studio:
    """The hosted project to look in once a local lookup found nothing."""
    studio = _hosted_studio(space, required=False)
    if studio is not None:
        return studio
    reason = (
        "you are not signed in"
        if session().token is None
        else "this directory is not registered with a hosted project"
    )
    jobs = relative(space.project.jobs_dir, space.project.root)
    raise ProjectError(
        f"No local {kind} {item_id!r} under {jobs}, and hosted {kind}s were not "
        f"searched because {reason}."
    )


def _runtime_credentials(space: Workspace, plan: RunPlan, *, err: bool) -> None:
    """Load provider credentials for Environments that use a project Runtime.

    Sandbox providers read credentials from this process's environment, so
    missing ones are set there, never in the Job's environment. Variables you
    already exported always win, and nothing is fetched when they cover the
    provider or when the Runtime's owner does not allow local runs to use its
    credentials. A Runtime on Plural's own account gets no credentials at all:
    its sandboxes start through Plural, which bills them as compute usage.
    """
    refs = {
        task.environment.runtime.ref: task.environment.runtime.provider
        for task in plan.spec.tasks
        if task.environment.runtime.ref
    }
    if not refs:
        return
    studio = _hosted_studio(space, required=False)
    if studio is None:
        return
    hosted: dict[str, str] = {}
    own: dict[str, str] = {}
    for ref, provider in sorted(refs.items()):
        spec = runtime_provider(provider)
        if spec is None or not any(
            item.required and not os.environ.get(item.key) for item in spec.credentials
        ):
            continue
        try:
            grant = studio.runtimes.credentials(ref)
        except PluralError as exc:
            typer.echo(f"! Runtime {ref}: {exc} Using credentials from your environment.", err=True)
            continue
        if grant.get("credentials") == "plural":
            hosted.setdefault(provider, ref)
            continue
        own.setdefault(provider, ref)
        for key, value in (grant.get("environ") or {}).items():
            os.environ.setdefault(str(key), str(value))
        typer.echo(f"Using credentials from project Runtime {ref}.", err=err)
    for provider, ref in sorted(hosted.items()):
        if provider in own:
            raise ProjectError(
                f"Runtime {ref} starts {provider} sandboxes on Plural's account and "
                f"Runtime {own[provider]} on your own. Run their Environments separately."
            )
        if provider != "daytona":
            continue
        default_registry.register(
            DaytonaProvider(adapter=HostedDaytonaAdapter(studio, runtime=ref)), replace=True
        )
        typer.echo(
            f"Starting Daytona sandboxes on Plural's account for Runtime {ref}. "
            "They are billed to your credits as compute usage.",
            err=err,
        )


def _stored_credentials(err: bool) -> CredentialSource:
    """Look up your saved credentials when the run starts."""
    return lambda spec, agent: stored_credentials(spec, agent, err=err)


def _needed_secrets(spec: JobSpec) -> list[str]:
    """Secret names the Job's Apps, Verifiers, and endpoint and external Agents need."""
    names: set[str] = set()
    for task in spec.tasks:
        names.update(item.name for item in task.environment.secrets)
        for binding in task.verifiers:
            names.update(item.name for item in binding.verifier.secrets)
    for agent in spec.agents:
        if agent.agent.endpoint_key:
            names.add(agent.agent.endpoint_key)
        if agent.external is not None:
            names.add(agent.external.signing_key)
    return sorted(names)


def _project_secrets(
    space: Workspace, spec: JobSpec, environ: dict[str, str], *, err: bool
) -> dict[str, str]:
    """Fill secrets the run needs, and you have not exported, from the hosted project.

    Values go into the Job's environment, which passes each to the App host,
    Verifier, or endpoint that declared it, and never into this process's own.
    Variables you already exported always win. Without a hosted project, or
    when you may not read its secrets, the run uses what you exported, and
    its preflight names anything still missing.
    """
    wanted = [name for name in _needed_secrets(spec) if not environ.get(name)]
    if not wanted:
        return environ
    try:
        studio, _ = _project_studio()
    except ProjectError:
        return environ
    try:
        grant = studio.secrets.resolve(wanted)
    except PluralError as exc:
        typer.echo(f"! Project secrets: {exc} Using secrets from your environment.", err=True)
        return environ
    found = {str(key): str(value) for key, value in (grant.get("environ") or {}).items()}
    for key, value in found.items():
        environ.setdefault(key, value)
    if found:
        typer.echo(f"Using project secrets: {', '.join(sorted(found))}.", err=err)
    return environ


def _run_environ(current: Session) -> dict[str, str]:
    """Process environment for a local run, with the gateway credential added.

    Every model call goes through the gateway, which accepts API keys, not the
    session a browser login from an older CLI stored.
    """
    environ = dict(os.environ)
    if current.api_key and not environ.get("PLURAL_API_KEY"):
        environ["PLURAL_API_KEY"] = current.api_key
    if environ.get("PLURAL_API_KEY"):
        environ.setdefault("PLURAL_GATEWAY_URL", current.api_url.rstrip("/") + "/v1")
    return environ


def _recording(record: bool, track: bool) -> bool:
    if track:
        deprecated("--track", "--record")
    return record or track


def _credit_watch(
    current: Session, environ: Mapping[str, str], *, err: bool
) -> AbstractContextManager[object]:
    """Warn about the balance while a run draws on the account's credits."""
    if current.token is None or not environ.get("PLURAL_GATEWAY_URL"):
        return nullcontext()
    return CreditWatch(current.studio(project=False), err=err)


def _print_pushed(steps: list[PushStep], *, err: bool) -> None:
    typer.echo("Pushed to the hosted project first, so the Job can pin them:", err=err)
    for step in steps:
        note = f" ({step.note})" if step.note else ""
        typer.echo(f"  {step.ref} {step.label}{note}", err=err)


def _tracking(space: Workspace, current: Session) -> Tracking:
    return Tracking(project_studio(space, current)[0])


def _one(values: list[str] | None, flag: str) -> str | None:
    """The one value a repeatable flag was given, refusing several."""
    if values and len(values) > 1:
        raise ProjectError(
            f"Pass {flag} once: a run is one Job with one Agent. To compare, run once per "
            f"{flag.removeprefix('--')}; `plural job list` shows the Jobs side by side."
        )
    return values[0] if values else None


def _finish_local(
    space: Workspace,
    job_id: str,
    result: JobResult,
    tracking: Tracking | None,
    *,
    as_json: bool,
) -> None:
    payload = {"location": "local", **local_job(space, job_id)}
    if tracking is not None:
        payload["hosted_job_id"] = tracking.hosted_job_id
        payload["recording_errors"] = tracking.errors

    def text() -> None:
        _print_result(job_id, result)
        if tracking is None:
            return
        typer.echo(f"Recorded in the hosted project as Job {tracking.hosted_job_id}.")
        if tracking.errors:
            typer.echo("Some of it could not be reported:", err=True)
            for error in tracking.errors:
                typer.echo(f"  {error}", err=True)
            typer.echo(f"Upload the rest with `plural job record {job_id}`.", err=True)

    emit(payload, as_json=as_json, text=text)
    if result.status in {"failed", "cancelled"}:
        raise typer.Exit(1)


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


def _plan_payload(plan: RunPlan) -> dict[str, Any]:
    return {
        "location": "local",
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
        f"{payload['location']}ly: {counted(len(payload['trials']), 'Trial')}, "
        f"{payload['concurrency']} at a time"
        + (f" (auto: {payload['concurrency_reason']})." if payload["concurrency_reason"] else ".")
    )
    rows(
        (
            (name, pin.get("revision") or pin.get("version", ""), pin["content_hash"][:19])
            for name, pin in payload["inputs"].items()
        ),
        ("input", "revision", "content hash"),
    )


def _print_result(job_id: str, result: JobResult) -> None:
    typer.echo(f"Job {job_id} {result.status}.")
    for aggregate in result.aggregates:
        mean = "-" if aggregate.mean_score is None else f"{aggregate.mean_score:.3f}"
        typer.echo(
            f"  {aggregate.agent_name}: mean score {mean} over "
            f"{counted(aggregate.count, 'Trial')}, "
            f"{aggregate.successes} succeeded, coverage {aggregate.coverage:.0%}"
        )
    for line in _reward_warnings(result.trials):
        typer.echo(f"! {line}", err=True)
    typer.echo(f"Details: plural job show {job_id}")


def _reward_warnings(trials: Iterable[TrialResult]) -> list[str]:
    """One line per Verifier whose ``reward`` raised, across every Trial.

    Returns:
        The lines, in the order the Verifiers first failed.
    """
    steps: dict[str, int] = {}
    failed_trials: dict[str, int] = {}
    first: dict[str, str] = {}
    for trial in trials:
        for failure in trial.reward_failures:
            steps[failure.verifier] = steps.get(failure.verifier, 0) + failure.steps
            failed_trials[failure.verifier] = failed_trials.get(failure.verifier, 0) + 1
            first.setdefault(failure.verifier, failure.error)
    return [
        f"Verifier {name}'s reward raised on {counted(count, 'step')} in "
        f"{counted(failed_trials[name], 'Trial')}, which earned it no reward there: "
        f"{first[name]}"
        for name, count in steps.items()
    ]


def _print_job(payload: dict[str, Any]) -> None:
    job_id = payload.get("job_id") or payload.get("id")
    typer.echo(f"Job {job_id} ({payload['location']}) {payload.get('status')}")
    if payload.get("source"):
        typer.echo(f"  Source: {payload['source']}")
    if payload.get("model"):
        typer.echo(f"  Model:  {payload['model']} via {payload.get('harness')}")
    if payload.get("rerun_of_job_id"):
        typer.echo(f"  Rerun of job {payload['rerun_of_job_id']}")
    if payload.get("hosted_job_id"):
        typer.echo(f"  Recorded as hosted Job {payload['hosted_job_id']}")
    if payload.get("executor") == "client":
        client = payload.get("client_job_id")
        typer.echo("  Run by a client" + (f", as local Job {client}" if client else ""))
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
            f"{'-' if mean is None else f'{mean:.3f}'} over "
            f"{counted(aggregate['count'], 'Trial')}, "
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
    failed = [item for item in trials if item.get("error")]
    for item in failed:
        reason = str(item["error"]).strip().splitlines()[0][:200]
        typer.echo(f"  {item['trial_id']} failed: {reason}")
    if failed:
        typer.echo(f"Details: plural trial show {failed[0]['trial_id']}")


def _print_trial(payload: dict[str, Any]) -> None:
    typer.echo(f"Trial {payload['trial_id']} ({payload['location']}) {payload.get('status')}")
    for label, key in (
        ("Job", "job_id"),
        ("Task", "task"),
        ("Score", "score"),
        ("Stopped", "stop_reason"),
        ("Seed", "seed"),
        ("Turns", "turns"),
        ("Cost (USD)", "cost_usd"),
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
    for failure in payload.get("reward_failures") or []:
        typer.echo(
            f"  Verifier {failure['verifier']}: reward raised on "
            f"{counted(failure['steps'], 'step')}: {failure['error']}"
        )
    for finding in payload.get("integrity") or []:
        typer.echo(f"  Integrity ({finding.get('code')}, not scored): {finding.get('message')}")
    for credential in payload.get("credentials") or []:
        scopes = ", ".join(credential.get("scopes") or []) or "no scopes listed"
        typer.echo(
            f"  Credential {credential.get('name')} for App {credential.get('app')}: "
            f"Agent {credential.get('agent')} {credential.get('agent_revision')} ({scopes}), "
            f"from {credential.get('source')}, {credential.get('fingerprint')}"
        )


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
