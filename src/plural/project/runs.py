"""Plan and record runs of a project's Tasks and Benchmarks.

Every run creates a new Job. A run names exactly one Task or Benchmark and
either a model (with an optional Harness) or a saved Agent. It records the
exact version and content hash of every resource it used.

Local runs snapshot the Environment, Verifier, and Harness sources they
execute into the Job directory, so a rerun uses the original files even after
the project has changed. Hosted runs use pushed revisions only.

A local run can also be recorded in the hosted project. With tracking, the
hosted Job is created before the run starts and each execution is reported as
it happens; ``push_local_job`` records a finished local Job afterwards. Either
way the hosted Job has executor ``client``: this machine ran it, in whatever
Runtime each Environment declares, and hosted workers never pick it up.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from plural.agents import Agent
from plural.agents.models import AgentDefinition
from plural.common import HarnessPackage, PackageSource
from plural.environments.definition import EnvironmentDefinition
from plural.execution.capacity import recommend_concurrency
from plural.harness.retrieval import tree_digest
from plural.jobs import (
    BenchmarkJobSource,
    Job,
    JobResult,
    JobSpec,
    TaskJobSource,
    TrialResult,
)
from plural.project.layout import (
    AGENT,
    BENCHMARK,
    ENVIRONMENT,
    HARNESS,
    TASK,
    VERIFIER,
    ProjectError,
    ResourceRef,
)
from plural.project.resources import Workspace
from plural.project.sync import HostedRevision, resolve_hosted, resolve_pinned
from plural.studio import Studio, slugify
from plural.tasks import TaskDefinition
from plural.verifiers import DeterministicVerifier, WeightedVerifier

DEFAULT_HARNESS = "native"
"""The Harness a run uses when none is named: Plural's built-in action loop.

It calls the model through the Plural gateway and exposes the Environment's
actions as tools. An Environment whose ``harness_policy`` is an allowlist must
list ``native`` for runs that omit ``--harness``.
"""

RUN_RECORD = "run.json"


@dataclass(frozen=True)
class RunRequest:
    """What ``plural run`` was asked to do."""

    task: str | None = None
    benchmark: str | None = None
    model: str | None = None
    harness: str | None = None
    agent: str | None = None
    attempts: int | None = None
    concurrency: int | Literal["auto"] = 1
    hosted: bool = False


@dataclass
class RunPlan:
    """A validated run: the Job to execute and every input it pins."""

    source: ResourceRef
    agent: Agent
    agent_ref: ResourceRef | None
    inputs: list[ResourceRef]
    job: Job
    pins: dict[str, dict[str, str]] = field(default_factory=dict)
    concurrency_reason: str | None = None
    """Why ``auto`` chose the Job's concurrency; ``None`` when a number was given."""

    @property
    def spec(self) -> JobSpec:
        """The Job specification."""
        return self.job.spec

    @property
    def harness(self) -> str:
        """The Harness the Agent runs with; ``native`` when none is named."""
        return _harness_name(self.agent)


@dataclass(frozen=True)
class RunRecord:
    """Metadata written beside a local Job: what ran and where it came from."""

    job_id: str
    created_at: str
    source: str
    agent: str
    model: str
    harness: str
    location: Literal["local", "hosted"] = "local"
    inputs: dict[str, dict[str, str]] = field(default_factory=dict)
    rerun_of_job_id: str | None = None
    rerun_of_trial_id: str | None = None
    hosted_job_id: str | None = None
    """The hosted client Job this local Job is recorded as, once tracked or pushed."""
    hosted_project_id: str | None = None

    def dump(self) -> dict[str, Any]:
        """JSON form.

        Returns:
            A JSON-compatible mapping.
        """
        return dict(self.__dict__)


@dataclass
class Tracking:
    """Record a local run in the hosted project while it executes.

    Pass one to ``run_local`` or a rerun. Afterwards ``hosted_job_id`` names
    the hosted Job, and ``errors`` lists what could not be reported; ``plural
    job push`` uploads the rest.
    """

    studio: Studio
    hosted_job_id: str | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClientJob:
    """A hosted Job that records a local one."""

    record: dict[str, Any]
    agents: dict[str, tuple[str, str]]
    """Each local Agent binding's hosted Agent name and definition hash."""

    @property
    def job_id(self) -> str:
        """The hosted Job id."""
        return str(self.record["id"])


@dataclass(frozen=True)
class PushedJob:
    """The outcome of ``push_local_job``."""

    job: ClientJob
    executions: int
    """Local executions the hosted Job now records."""


def plan_run(
    workspace: Workspace, request: RunRequest, *, environ: Mapping[str, str] | None = None
) -> RunPlan:
    """Resolve a run request against the project.

    ``environ`` is the environment the run will use; ``auto`` concurrency reads
    the model endpoint and sandbox quota from it.

    Returns:
        The validated plan.

    Raises:
        ProjectError: When the request is ambiguous or an input is invalid.
    """
    if bool(request.task) == bool(request.benchmark):
        raise ProjectError("Name exactly one of --task or --benchmark.")
    if request.agent and (request.model or request.harness):
        raise ProjectError(
            "--agent already names a model and Harness. Use --agent alone, or --model with an "
            "optional --harness."
        )
    if not request.agent and not request.model:
        raise ProjectError("Name a model with --model, or a saved Agent with --agent.")
    source = (
        ResourceRef(TASK.name, str(request.task))
        if request.task
        else ResourceRef(BENCHMARK.name, str(request.benchmark))
    )
    loaded = workspace.load(source)
    agent, agent_ref, harness_ref = _agent(workspace, request)
    tasks = [loaded.value] if source.kind == TASK.name else list(loaded.value.tasks)
    for task in tasks:
        policy = task._environment_definition().harness_policy
        harness_name = _harness_name(agent)
        if policy.mode == "allowlist" and harness_name not in policy.allowed_harnesses:
            allowed = ", ".join(policy.allowed_harnesses) or "none"
            raise ProjectError(
                f"Environment {task._environment_definition().name!r} does not allow Harness "
                f"{harness_name!r}. Allowed: {allowed}. Pass --harness <name>."
            )
    attempts = request.attempts or 1
    auto = request.concurrency == "auto"
    job = Job(
        loaded.value,
        agents=[agent],
        attempts=attempts,
        concurrency=1 if auto else request.concurrency,
        catalog=workspace.catalog,
    )
    update: dict[str, Any] = {"run_id": uuid.uuid4().hex}
    reason = None
    if auto:
        advice = recommend_concurrency(
            job.spec,
            trial_count=job.plan.trial_count,
            environ=environ,
            hosted=request.hosted,
        )
        update["concurrency"] = update["per_runtime_concurrency"] = advice.trials
        reason = advice.reason
    job.spec = job.spec.model_copy(update=update)
    job.plan = job.spec.plan(workspace.catalog)
    inputs = workspace.dependency_order(
        [source, *([agent_ref] if agent_ref else []), *([harness_ref] if harness_ref else [])]
    )
    pins = {
        str(item): {
            "version": workspace.load(item).version,
            "content_hash": workspace.load(item).content_hash,
        }
        for item in inputs
    }
    return RunPlan(
        source=source,
        agent=agent,
        agent_ref=agent_ref,
        inputs=inputs,
        job=job,
        pins=pins,
        concurrency_reason=reason,
    )


def run_local(
    workspace: Workspace,
    plan: RunPlan,
    *,
    environ: Mapping[str, str],
    progress: Any = None,
    tracking: Tracking | None = None,
) -> tuple[str, JobResult]:
    """Execute a plan on this machine and record it under ``.plural/jobs``.

    With ``tracking``, the Job is also recorded in the hosted project as it runs.

    Returns:
        The Job id and its result.
    """
    spec = _snapshot_sources(workspace, plan.spec)
    record = RunRecord(
        job_id=spec.job_id,
        created_at=_now(),
        source=str(plan.source),
        agent=str(plan.agent_ref) if plan.agent_ref else plan.agent.name,
        model=plan.agent.model,
        harness=plan.harness,
        inputs=plan.pins,
    )
    return _execute(workspace, spec, record, environ=environ, progress=progress, tracking=tracking)


def rerun_local_job(
    workspace: Workspace,
    job_id: str,
    *,
    environ: Mapping[str, str],
    progress: Any = None,
    tracking: Tracking | None = None,
) -> tuple[str, JobResult]:
    """Run a recorded local Job again with its original pinned inputs.

    Returns:
        The new Job id and its result.
    """
    spec, record = _load_local(workspace, job_id)
    fresh = spec.model_copy(update={"run_id": uuid.uuid4().hex})
    new_record = RunRecord(
        **{
            **record.dump(),
            "job_id": fresh.job_id,
            "created_at": _now(),
            "rerun_of_job_id": job_id,
            "rerun_of_trial_id": None,
            "hosted_job_id": None,
            "hosted_project_id": None,
        }
    )
    return _execute(
        workspace, fresh, new_record, environ=environ, progress=progress, tracking=tracking
    )


def rerun_local_trial(
    workspace: Workspace,
    trial_id: str,
    *,
    environ: Mapping[str, str],
    progress: Any = None,
    tracking: Tracking | None = None,
) -> tuple[str, JobResult]:
    """Run one recorded local Trial again as a new one-Trial Job.

    Returns:
        The new Job id and its result.
    """
    job_id, _ = find_local_trial(workspace, trial_id)
    spec, record = _load_local(workspace, job_id)
    trial = next(item for item in spec.plan().trials if item.trial_id == trial_id)
    task = next(item for item in spec.tasks if item.content_hash == trial.task_digest)
    agent = next(item for item in spec.agents if item.agent_id == trial.agent_id)
    fresh = spec.model_copy(
        update={
            "source": TaskJobSource(task=task),
            "agents": (agent,),
            "attempts": 1,
            "run_id": uuid.uuid4().hex,
        }
    )
    new_record = RunRecord(
        **{
            **record.dump(),
            "job_id": fresh.job_id,
            "created_at": _now(),
            "source": f"task/{task.task_id}",
            "rerun_of_job_id": job_id,
            "rerun_of_trial_id": trial_id,
            "hosted_job_id": None,
            "hosted_project_id": None,
        }
    )
    return _execute(
        workspace, fresh, new_record, environ=environ, progress=progress, tracking=tracking
    )


def submit_hosted(
    workspace: Workspace,
    studio: Studio,
    plan: RunPlan,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Submit a plan to the hosted project using already-pushed revisions.

    A ``--model`` run has no saved Agent, so it records one named after the
    model (and Harness, when one is named) in the hosted project.

    Returns:
        The hosted Job record.

    Raises:
        ProjectError: When any input is not pushed with identical content.
    """
    roots = [plan.source, *([plan.agent_ref] if plan.agent_ref else [])]
    harness_ref = _harness_ref(plan.agent) if plan.agent_ref is None else None
    if harness_ref is not None:
        roots.append(harness_ref)
    resolved = resolve_hosted(workspace, studio, roots)
    return _submit(
        studio,
        plan.spec,
        agent=plan.agent,
        source=plan.source,
        agent_ref=plan.agent_ref,
        harness_ref=harness_ref,
        resolved=resolved,
        idempotency_key=idempotency_key or uuid.uuid4().hex,
    ).record


def submit_client_job(
    workspace: Workspace,
    studio: Studio,
    spec: JobSpec,
    record: RunRecord,
    *,
    idempotency_key: str | None = None,
) -> ClientJob:
    """Create the hosted Job that records a local one, from the revisions it pinned.

    The hosted Job has executor ``client``, so no hosted worker runs it; the
    local executions are reported to it. The same local Job always maps to
    the same hosted Job.

    Returns:
        The hosted Job and the hosted Agent each local binding ran as.

    Raises:
        ProjectError: When an input the Job pinned is not pushed with the same content.
    """
    resolved = resolve_pinned(studio, record.inputs)
    source = ResourceRef.parse(record.source)
    if source not in resolved:
        raise ProjectError(f"Job {record.job_id} does not pin its source {source}.")
    agent_ref = (
        ResourceRef(AGENT.name, record.agent.partition("/")[2])
        if (record.agent.startswith(f"{AGENT.name}/"))
        else None
    )
    harness_ref = (
        next((ref for ref in resolved if ref.kind == HARNESS.name), None)
        if agent_ref is None
        else None
    )
    return _submit(
        studio,
        spec,
        agent=None if agent_ref else _agent_value(workspace, spec.agents[0].agent),
        source=source,
        agent_ref=agent_ref,
        harness_ref=harness_ref,
        resolved=resolved,
        idempotency_key=idempotency_key or f"local:{record.job_id}",
        client_job_id=record.job_id,
    )


def push_local_job(workspace: Workspace, studio: Studio, job_id: str) -> PushedJob:
    """Record a finished local Job, and every execution it ran, in the hosted project.

    Pushing again, or pushing a Job that was tracked, reuses the same hosted
    Job and uploads only what it does not hold yet.

    Returns:
        The hosted Job and how many executions it records.

    Raises:
        ProjectError: When the Job is unknown, still running, or ran inputs
            that are not pushed.
    """
    from plural.execution.report import PublishError, publish_job
    from plural.execution.store import JobStore

    record = finished_local_job(workspace, job_id)
    directory = workspace.project.jobs_dir / job_id
    store = JobStore(workspace.project.jobs_dir)
    client = submit_client_job(workspace, studio, store.load_spec(job_id), record)
    try:
        published = publish_job(
            studio, store, job_id, client.job_id, worker_id="plural-cli", agents=client.agents
        )
    except PublishError as exc:
        raise ProjectError(f"Could not record Job {job_id}: {exc}") from None
    _write_record(
        directory,
        replace(record, hosted_job_id=client.job_id, hosted_project_id=studio.project),
    )
    return PushedJob(job=client, executions=len(published))


def finished_local_job(workspace: Workspace, job_id: str) -> RunRecord:
    """The record of a local Job that has finished running.

    Returns:
        Its run record.

    Raises:
        ProjectError: When no local Job has this id, or it has not finished.
    """
    directory = workspace.project.jobs_dir / job_id
    record_path = directory / RUN_RECORD
    if not record_path.is_file():
        raise ProjectError(f"No local Job {job_id!r} in {workspace.project.jobs_dir}.")
    if not (directory / "result.json").is_file():
        raise ProjectError(
            f"Job {job_id} has not finished, so it cannot be pushed yet. To record a run "
            "while it happens, start it with `plural run --track`."
        )
    return RunRecord(**json.loads(record_path.read_text("utf-8")))


def _harness_ref(agent: Agent) -> ResourceRef | None:
    """The project Harness a ``--model`` run names.

    Returns:
        Its reference, or ``None`` for no Harness or a built-in one.
    """
    if agent.harness is None or isinstance(agent.harness, str):
        return None
    return ResourceRef(HARNESS.name, _harness_name(agent))


def _agent_value(workspace: Workspace, definition: AgentDefinition) -> Agent:
    """The Agent a ``--model`` run compiled to ``definition``, to record it hosted.

    Returns:
        An Agent whose definition hashes exactly as ``definition``.

    Raises:
        ProjectError: When the run used a project Harness, or the Agent cannot
            be rebuilt exactly.
    """
    harness = None
    if definition.harness_package is not None:
        from plural.harness.builtins import BUILTIN_HARNESS_NAMES

        harness = definition.harness_package.definition.name
        if harness not in BUILTIN_HARNESS_NAMES:
            raise ProjectError(
                f"This Job ran Harness {harness!r} without a saved Agent. Save one under "
                "agents/ and run with --agent to record runs of it."
            )
    agent = Agent.model_validate(
        {
            "name": definition.name,
            "version": definition.revision,
            "model": definition.model,
            "instructions": definition.instructions,
            "routing": definition.routing,
            "harness": harness,
            "harness_kwargs": definition.harness_kwargs,
            "auth_mode": definition.auth_mode,
            "secret_names": definition.secret_names,
            "metadata": definition.metadata,
        },
        context={"catalog": workspace.catalog, "root": workspace.project.root},
    )
    if agent.content_hash != definition.content_hash:
        raise ProjectError(f"Agent {definition.name!r} cannot be recorded exactly as it ran.")
    return agent


def _submit(
    studio: Studio,
    spec: JobSpec,
    *,
    agent: Agent | None,
    source: ResourceRef,
    agent_ref: ResourceRef | None,
    harness_ref: ResourceRef | None,
    resolved: Mapping[ResourceRef, HostedRevision],
    idempotency_key: str,
    client_job_id: str | None = None,
) -> ClientJob:
    binding = spec.agents[0]
    if agent_ref is not None:
        hosted = (binding.name, binding.agent.content_hash)
        agent_revision_id = resolved[agent_ref].revision_id
    else:
        assert agent is not None, "a run without a saved Agent needs its Agent value"
        name = slugify(
            agent.model.replace("/", "-")
            + (f"-{_harness_name(agent)}" if agent.harness is not None else "")
        )
        renamed = agent.model_copy(update={"name": name})
        pushed = studio.agents.push(
            renamed,
            harness_revision_id=resolved[harness_ref].revision_id if harness_ref else None,
        )
        hosted = (renamed.name, renamed.content_hash)
        agent_revision_id = str(pushed["id"])
    _stamp_harness(studio, spec, resolved)
    record = studio.jobs.submit(
        spec,
        source_revision_id=resolved[source].revision_id,
        agent_revision_ids=[agent_revision_id],
        idempotency_key=idempotency_key,
        name=f"{source.name} · {binding.name}",
        executor="client" if client_job_id else "hosted",
        client_job_id=client_job_id,
    )
    return ClientJob(record=record, agents={binding.content_hash: hosted})


def local_jobs(workspace: Workspace) -> list[dict[str, Any]]:
    """Recorded local Jobs, newest first.

    Returns:
        One summary per Job.
    """
    root = workspace.project.jobs_dir
    if not root.is_dir():
        return []
    items = []
    for directory in root.iterdir():
        record_path = directory / RUN_RECORD
        if not record_path.is_file():
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        result_path = directory / "result.json"
        status = "running"
        if result_path.is_file():
            status = JobResult.model_validate_json(result_path.read_text("utf-8")).status
        items.append({**record, "status": status})
    return sorted(items, key=lambda item: str(item.get("created_at")), reverse=True)


def local_job(workspace: Workspace, job_id: str) -> dict[str, Any]:
    """One recorded local Job with its Trials.

    Returns:
        The Job summary with its Trials.

    Raises:
        ProjectError: When no local Job has this id.
    """
    directory = workspace.project.jobs_dir / job_id
    record_path = directory / RUN_RECORD
    if not record_path.is_file():
        raise ProjectError(f"No local Job {job_id!r} in {workspace.project.jobs_dir}.")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    result_path = directory / "result.json"
    result = (
        JobResult.model_validate_json(result_path.read_text("utf-8"))
        if result_path.is_file()
        else None
    )
    if result is not None:
        return {
            **record,
            "status": result.status,
            "trials": [_trial_summary(item) for item in result.trials],
            "aggregates": [item.model_dump(mode="json") for item in result.aggregates],
            "directory": str(directory),
        }
    from plural.execution.engine import job_progress
    from plural.execution.store import JobStore

    progress = job_progress(JobStore(workspace.project.jobs_dir), job_id)
    return {
        **record,
        "status": "running",
        "progress": {
            "planned": progress.planned,
            "finished": progress.finished,
            "running": progress.running,
            "succeeded": progress.succeeded,
            "failed": progress.failed,
        },
        "trials": [_trial_summary(item) for item in progress.trials],
        "aggregates": [item.model_dump(mode="json") for item in progress.aggregates],
        "directory": str(directory),
    }


def find_local_trial(workspace: Workspace, trial_id: str) -> tuple[str, Path]:
    """Locate a Trial among local Jobs.

    Returns:
        The owning Job id and the Trial directory.

    Raises:
        ProjectError: When no local Job has this Trial.
    """
    root = workspace.project.jobs_dir
    if root.is_dir():
        for directory in root.iterdir():
            candidate = directory / "trials" / trial_id
            if candidate.is_dir():
                return directory.name, candidate
    raise ProjectError(f"No local Trial {trial_id!r} in {root}.")


def local_trial(workspace: Workspace, trial_id: str) -> dict[str, Any]:
    """One local Trial: its result, Verifier evidence, and artifact paths.

    Returns:
        The Trial view.
    """
    job_id, directory = find_local_trial(workspace, trial_id)
    record = json.loads((directory.parent.parent / RUN_RECORD).read_text("utf-8"))
    result_path = directory / "result.json"
    result = (
        TrialResult.model_validate_json(result_path.read_text("utf-8"))
        if result_path.is_file()
        else None
    )
    executions = sorted(
        (item for item in (directory / "executions").glob("*") if item.is_dir()),
        key=lambda item: int(item.name) if item.name.isdigit() else -1,
    )
    latest = executions[-1] if executions else None
    return {
        "trial_id": trial_id,
        "job_id": job_id,
        "location": "local",
        "source": record.get("source"),
        "rerun_of_job_id": record.get("rerun_of_job_id"),
        "rerun_of_trial_id": record.get("rerun_of_trial_id"),
        **(_trial_summary(result) if result else {"status": "running"}),
        "verifiers": (
            [item.model_dump(mode="json") for item in result.verifier_results] if result else []
        ),
        "artifacts": str(latest / "artifacts") if latest else None,
        "logs": str(latest / "logs") if latest else None,
    }


def _agent(
    workspace: Workspace, request: RunRequest
) -> tuple[Agent, ResourceRef | None, ResourceRef | None]:
    if request.agent:
        ref = ResourceRef(AGENT.name, request.agent)
        return workspace.load(ref).value, ref, None
    model = str(request.model)
    harness_name = request.harness or DEFAULT_HARNESS
    fields: dict[str, Any] = {"model": model, "name": model.rsplit("/", 1)[-1]}
    harness_ref = None
    if harness_name != DEFAULT_HARNESS:
        from plural.harness.builtins import BUILTIN_HARNESS_NAMES

        if harness_name in BUILTIN_HARNESS_NAMES:
            fields["harness"] = harness_name
        else:
            harness_ref = ResourceRef(HARNESS.name, harness_name)
            fields["harness"] = workspace.load(harness_ref).value
    try:
        agent = Agent.model_validate(
            fields, context={"catalog": workspace.catalog, "root": workspace.project.root}
        )
    except ValueError as exc:
        raise ProjectError(str(exc).splitlines()[-1] if str(exc) else "invalid model") from None
    return agent, None, harness_ref


def _harness_name(agent: Agent) -> str:
    if agent.harness is None:
        return DEFAULT_HARNESS
    if isinstance(agent.harness, str):
        return agent.harness
    package = agent._resolved_package()
    return package.definition.name if package is not None else DEFAULT_HARNESS


def _stamp_harness(
    studio: Studio, spec: JobSpec, resolved: Mapping[ResourceRef, HostedRevision]
) -> None:
    """Record that each Environment admits the Agent's custom Harness.

    The server refuses to schedule a custom Harness in an Environment that has
    no compatibility stamp; the grant is computed from both definitions here.
    """
    from plural.harness.builtins import BUILTIN_HARNESS_NAMES
    from plural.jobs import resolve_trial_harness_grant

    binding = spec.agents[0]
    package = binding.harness_package
    if package is None or package.definition.name in BUILTIN_HARNESS_NAMES:
        return
    harness = next((value for ref, value in resolved.items() if ref.kind == HARNESS.name), None)
    if harness is None:
        return
    seen: set[str] = set()
    for task in spec.tasks:
        environment = ResourceRef(ENVIRONMENT.name, task.environment.name)
        revision = resolved.get(environment)
        if revision is None or revision.revision_id in seen:
            continue
        seen.add(revision.revision_id)
        grant = resolve_trial_harness_grant(task.environment, binding.agent)
        studio.environments.stamp_harness(
            environment_id=revision.resource_id,
            revision_id=revision.revision_id,
            harness_revision_id=harness.revision_id,
            compatible=True,
            evidence=grant.model_dump(mode="json") if grant is not None else {"kind": "native"},
        )


def _execute(
    workspace: Workspace,
    spec: JobSpec,
    record: RunRecord,
    *,
    environ: Mapping[str, str],
    progress: Any,
    tracking: Tracking | None = None,
) -> tuple[str, JobResult]:
    from plural.execution.engine import JobRunner
    from plural.execution.report import HostedTracker
    from plural.execution.store import JobStore

    needs_model = any(binding.auth_mode != "none" for binding in spec.agents)
    if needs_model and not (environ.get("PLURAL_API_KEY") or environ.get("OPENAI_API_KEY")):
        raise ProjectError(
            "This run calls a live model and no model credential is available. Run "
            "`plural auth login`, or export PLURAL_API_KEY or OPENAI_API_KEY."
        )
    tracker = None
    store = JobStore(workspace.project.jobs_dir)
    if tracking is not None:
        client = submit_client_job(workspace, tracking.studio, spec, record)
        tracking.hosted_job_id = client.job_id
        record = replace(
            record, hosted_job_id=client.job_id, hosted_project_id=tracking.studio.project
        )
        tracker = HostedTracker(
            tracking.studio,
            store,
            spec,
            spec.plan(workspace.catalog),
            client.job_id,
            agents=client.agents,
        )
        store.on_event = tracker.observe
    job_dir = store.job_path(spec.job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    _write_record(job_dir, record)
    options: dict[str, Any] = {"store": store, "catalog": workspace.catalog, "environ": environ}
    if progress is not None:
        options["progress"] = progress
    try:
        result = asyncio.run(JobRunner(spec, **options).run())
    except BaseException:
        if tracker is not None and tracking is not None:
            tracking.errors = tracker.close(cancelled=True)
        raise
    if tracker is not None and tracking is not None:
        tracking.errors = tracker.close()
    return spec.job_id, result


def _write_record(directory: Path, record: RunRecord) -> None:
    (directory / RUN_RECORD).write_text(
        json.dumps(record.dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _snapshot_path(workspace: Workspace, kind: str, name: str, digest: str) -> Path:
    hex_digest = digest.rpartition(":")[2]
    return workspace.project.state_dir / "packages" / f"{kind}-{name}-{hex_digest[:16]}"


def _snapshot_sources(workspace: Workspace, spec: JobSpec) -> JobSpec:
    """Copy executed sources into ``.plural/packages`` and point the spec at them.

    Snapshots are content-addressed by tree digest, so they are shared between
    Jobs and never change once written.

    Returns:
        The spec with every local source pointing at its snapshot.
    """

    def snapshot(kind: str, name: str, source: Path, digest: str | None) -> Path:
        expected = digest or tree_digest(source)
        target = _snapshot_path(workspace, kind, name, expected)
        if target.exists() and tree_digest(target) == expected:
            return target
        shutil.rmtree(target, ignore_errors=True)
        staging = target.with_name(f".{target.name}.{uuid.uuid4().hex}")
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns(*_SNAPSHOT_IGNORED))
        if tree_digest(staging) != expected:
            shutil.rmtree(staging, ignore_errors=True)
            raise ProjectError(
                f"{kind} {name!r} changed while the run was being prepared. Run again."
            )
        staging.replace(target)
        return target

    def environment(definition: EnvironmentDefinition) -> EnvironmentDefinition:
        source = definition.source
        if source is None or source.kind != "local":
            return definition
        target = snapshot("environment", definition.name, Path(source.uri), source.digest)
        return definition.model_copy(
            update={"source": source.model_copy(update={"uri": str(target)})}
        )

    def verifiers(task: TaskDefinition) -> tuple[WeightedVerifier, ...]:
        for item in task.verifiers:
            verifier = item.verifier
            if isinstance(verifier, DeterministicVerifier) and verifier.checker is not None:
                directory = workspace.project.resource_dir(
                    ResourceRef(VERIFIER.name, verifier.name)
                )
                snapshot("verifier", verifier.name, directory, verifier._source_digest)
        return task.verifiers

    def task(definition: TaskDefinition) -> TaskDefinition:
        return definition.model_copy(
            update={
                "environment": environment(definition.environment),
                "verifiers": verifiers(definition),
            }
        )

    if isinstance(spec.source, TaskJobSource):
        source: TaskJobSource | BenchmarkJobSource = TaskJobSource(task=task(spec.source.task))
    else:
        benchmark = spec.source.benchmark
        source = BenchmarkJobSource(
            benchmark=benchmark.model_copy(
                update={"tasks": tuple(task(item) for item in benchmark.tasks)}
            )
        )
    agents = []
    for binding in spec.agents:
        package = binding.harness_package
        if package is not None and package.source.kind == "local":
            target = snapshot(
                "harness", package.definition.name, Path(package.source.uri), package.source.digest
            )
            pinned = HarnessPackage(
                definition=package.definition,
                source=PackageSource(
                    kind="local", uri=str(target), digest=package.source.digest, trusted=True
                ),
            )
            binding = binding.model_copy(
                update={"agent": binding.agent.model_copy(update={"harness_package": pinned})}
            )
        agents.append(binding)
    return spec.model_copy(update={"source": source, "agents": tuple(agents)})


_SNAPSHOT_IGNORED = ("__pycache__", ".git", ".plural", ".DS_Store")


def _load_local(workspace: Workspace, job_id: str) -> tuple[JobSpec, RunRecord]:
    directory = workspace.project.jobs_dir / job_id
    config = directory / "config.json"
    record_path = directory / RUN_RECORD
    if not config.is_file() or not record_path.is_file():
        raise ProjectError(f"No local Job {job_id!r} in {workspace.project.jobs_dir}.")
    spec = JobSpec.model_validate_json(config.read_text("utf-8"))
    record = RunRecord(**json.loads(record_path.read_text("utf-8")))
    return _rebind_checks(workspace, spec), record


def _rebind_checks(workspace: Workspace, spec: JobSpec) -> JobSpec:
    """Re-import Python Verifier checks from the Job's snapshot.

    A saved spec names each check as ``file.py:function`` with a digest. The
    function is imported from the snapshot, and the resulting Verifier must
    hash exactly as it did when the Job first ran.

    Returns:
        The spec with callable checks restored.
    """

    def rebind(item: WeightedVerifier) -> WeightedVerifier:
        verifier = item.verifier
        if not isinstance(verifier, DeterministicVerifier) or not verifier.python_ref:
            return item
        digest = verifier.check.get("digest") if isinstance(verifier.check, dict) else None
        if not digest:
            raise ProjectError(
                f"Verifier {verifier.name!r} was recorded without a source digest and cannot "
                "be rerun."
            )
        directory = _snapshot_path(workspace, "verifier", verifier.name, str(digest))
        file_name, _, function_name = verifier.python_ref.rpartition(":")
        path = directory / file_name
        if not path.is_file():
            raise ProjectError(
                f"Verifier {verifier.name!r} source is missing from the Job snapshot ({path})."
            )
        module_name = f"_plural_rerun_{uuid.uuid4().hex}"
        spec_obj = importlib.util.spec_from_file_location(module_name, path)
        assert spec_obj is not None and spec_obj.loader is not None
        module = importlib.util.module_from_spec(spec_obj)
        sys.path.insert(0, str(directory))
        try:
            spec_obj.loader.exec_module(module)
        finally:
            sys.path.remove(str(directory))
        function: Any = module
        for part in function_name.split("."):
            function = getattr(function, part)
        rebound = verifier.model_copy(update={"check": function})
        rebound.bind_source_digest(str(digest))
        if rebound.content_hash != verifier.content_hash:
            raise ProjectError(
                f"Verifier {verifier.name!r} in the Job snapshot no longer matches the "
                "recorded revision."
            )
        return item.model_copy(update={"verifier": rebound})

    def task(definition: TaskDefinition) -> TaskDefinition:
        return definition.model_copy(
            update={"verifiers": tuple(rebind(item) for item in definition.verifiers)}
        )

    if isinstance(spec.source, TaskJobSource):
        return spec.model_copy(update={"source": TaskJobSource(task=task(spec.source.task))})
    benchmark = spec.source.benchmark
    return spec.model_copy(
        update={
            "source": BenchmarkJobSource(
                benchmark=benchmark.model_copy(
                    update={"tasks": tuple(task(item) for item in benchmark.tasks)}
                )
            )
        }
    )


def _trial_summary(result: TrialResult) -> dict[str, Any]:
    return {
        "trial_id": result.receipt.trial_id,
        "status": result.status,
        "task": result.receipt.task_pin.name,
        "attempt": result.receipt.attempt,
        "model": result.receipt.model.catalog_model_id,
        "score": result.score,
        "error": result.error_message,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "DEFAULT_HARNESS",
    "ClientJob",
    "PushedJob",
    "RunPlan",
    "RunRecord",
    "RunRequest",
    "Tracking",
    "find_local_trial",
    "finished_local_job",
    "local_job",
    "local_jobs",
    "local_trial",
    "plan_run",
    "push_local_job",
    "rerun_local_job",
    "rerun_local_trial",
    "run_local",
    "submit_client_job",
    "submit_hosted",
]
