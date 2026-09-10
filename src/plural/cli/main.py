"""Plural command-line interface."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, NoReturn

import typer
import yaml
from pydantic import BaseModel, ValidationError

from plural.cli.auth import AuthClient, AuthHTTPError
from plural.cli.config import (
    CLIConfig,
    CLIProfile,
    Credential,
    default_credential_store,
    load_config,
    resolve_context,
    save_config,
)
from plural.cli.scaffold import (
    add_environment_action,
    add_environment_resource,
    add_task,
    allow_harness,
    allow_harness_package,
    load_agent,
    load_benchmark,
    load_environment,
    load_harness,
    load_harness_reference,
    load_job,
    remove_environment_action,
    scaffold_agent,
    scaffold_benchmark,
    scaffold_environment,
    scaffold_harness,
    scaffold_job,
    unstamp_harness,
)
from plural.domain import (
    AgentBinding,
    AgentTemplate,
    EnvironmentResource,
    ExecutionTarget,
    NativeAction,
    RetryPolicy,
    TaskDefinition,
    resolve_harness_stamp,
)
from plural.execution import Job as ExecutionJob
from plural.execution import JobStore
from plural.execution.policy import ProjectPolicy, resolve_effective_policy
from plural.harness import HarnessRunner, HarnessRunRequest
from plural.harness.retrieval import build_archive, materialize_package
from plural.sandbox import LocalProvider, NetworkMode, SandboxRequirements, default_registry

app = typer.Typer(
    name="plural",
    help="Build, validate, inspect, and run reproducible Plural packages.",
    no_args_is_help=True,
)
auth_app = typer.Typer(help="Authenticate without entering passwords.")
org_app = typer.Typer(help="Inspect and select organizations.")
project_app = typer.Typer(help="Inspect and select projects.")
env_app = typer.Typer(help="Manage environment packages.")
env_task_app = typer.Typer(help="Manage environment-owned tasks.")
env_action_app = typer.Typer(help="Manage environment-owned native actions.")
env_resource_app = typer.Typer(help="Manage environment resources.")
env_harness_app = typer.Typer(help="Stamp and inspect harness grants.")
harness_app = typer.Typer(help="Manage immutable agent harness packages.")
benchmark_app = typer.Typer(help="Manage ordered benchmark definitions.")
agent_app = typer.Typer(help="Inspect agents and local agent configs.")
agent_template_app = typer.Typer(help="Manage agent templates.")
agent_instance_app = typer.Typer(help="Inspect hosted agent instances.")
runtime_app = typer.Typer(help="Inspect execution-provider integration points.")
job_app = typer.Typer(help="Inspect and control jobs.")
trial_app = typer.Typer(help="Inspect immutable job trials.")

app.add_typer(auth_app, name="auth")
app.add_typer(org_app, name="org")
app.add_typer(project_app, name="project")
app.add_typer(env_app, name="env")
env_app.add_typer(env_task_app, name="task")
env_app.add_typer(env_action_app, name="action")
env_app.add_typer(env_resource_app, name="resource")
env_app.add_typer(env_harness_app, name="harness")
agent_app.add_typer(agent_template_app, name="template")
agent_app.add_typer(agent_instance_app, name="instance")
app.add_typer(harness_app, name="harness")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(agent_app, name="agent")
app.add_typer(runtime_app, name="runtime")
app.add_typer(job_app, name="job")
app.add_typer(trial_app, name="trial")


class CLIState:
    """Shared resolved CLI state."""

    def __init__(
        self,
        *,
        api_url: str | None,
        organization: str | None,
        project: str | None,
        profile: str | None,
    ) -> None:
        self.config = load_config()
        self.credentials = default_credential_store()
        self.context = resolve_context(
            api_url=api_url,
            organization=organization,
            project=project,
            profile=profile,
            config=self.config,
            credentials=self.credentials,
        )


@app.callback()
def root(
    ctx: typer.Context,
    api_url: str | None = typer.Option(None, "--api-url", help="Hosted API base URL."),
    organization: str | None = typer.Option(None, "--org", help="Organization override."),
    project: str | None = typer.Option(None, "--project", help="Project override."),
    profile: str | None = typer.Option(None, "--profile", help="Named CLI profile."),
) -> None:
    """Resolve global context using flags, environment, then config."""
    ctx.obj = CLIState(
        api_url=api_url,
        organization=organization,
        project=project,
        profile=profile,
    )


def _state(ctx: typer.Context) -> CLIState:
    value = ctx.find_root().obj
    if not isinstance(value, CLIState):
        raise RuntimeError("CLI context was not initialized")
    return value


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def _emit(value: Any, output_format: str = "json") -> None:
    payload = _dump(value)
    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif output_format == "yaml":
        typer.echo(yaml.safe_dump(payload, sort_keys=False).rstrip())
    elif isinstance(payload, dict):
        for key, item in payload.items():
            typer.echo(f"{key}: {item}")
    elif isinstance(payload, list):
        for item in payload:
            typer.echo(item if isinstance(item, str) else json.dumps(item, sort_keys=True))
    else:
        typer.echo(str(payload))


def _error(message: str, *, code: int = 2) -> NoReturn:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code)


def _unsupported(action: str) -> NoReturn:
    _error(
        f"{action} requires the package-execution/backend phase and is not configured; "
        "use local validation, inspection, or `plural run --dry-run` now"
    )


def _credential(state: CLIState) -> Credential | None:
    stored = state.credentials.get(state.context.profile)
    if state.context.api_key:
        return Credential(
            access_token=stored.access_token if stored else None,
            refresh_token=stored.refresh_token if stored else None,
            api_key=state.context.api_key,
        )
    return stored


def _updated_profile(
    config: CLIConfig,
    profile_name: str,
    *,
    organization: str | None = None,
    project: str | None = None,
) -> CLIConfig:
    current = config.profiles.get(profile_name, CLIProfile())
    updated = current.model_copy(
        update={
            "organization": organization if organization is not None else current.organization,
            "project": project if project is not None else current.project,
        }
    )
    profiles = dict(config.profiles)
    profiles[profile_name] = updated
    return config.model_copy(update={"active_profile": profile_name, "profiles": profiles})


def _hosted_client(state: CLIState) -> Any | None:
    credential = _credential(state)
    if credential is None:
        return None
    token = credential.api_key
    if token is None and credential.refresh_token is not None:
        with AuthClient(state.context.api_url) as auth:
            refreshed = auth.refresh(credential.refresh_token).credential()
        state.credentials.set(state.context.profile, refreshed)
        credential = refreshed
    token = token or credential.access_token
    if token is None:
        return None
    from plural import Client

    return Client(
        api_key=token,
        base_url=state.context.api_url,
        project=state.context.project,
    )


def _matching_digest(value: Any, expected: str) -> bool:
    actual = str(value or "")
    return actual == expected


def _register_sync(
    state: CLIState,
    spec: Any,
    store: JobStore,
) -> tuple[Any, dict[str, str], str] | None:
    client = _hosted_client(state)
    if client is None:
        return None
    from plural.studio import slugify

    environment = client.environments.get(slugify(spec.environment.name, fallback="environment"))
    revisions = client.studio.request("GET", f"/environments/{environment['id']}/revisions")
    environment_revision = next(
        (
            item
            for item in revisions
            if _matching_digest(
                item.get("package_content_hash"),
                spec.environment.identity.digest,
            )
        ),
        None,
    )
    if environment_revision is None:
        raise ValueError(
            "no hosted environment revision matches the local immutable digest; "
            "publish it with `plural env push <environment-path>`"
        )
    environment_revision_id = str(environment_revision["id"])
    benchmark = client.benchmarks.get(slugify(spec.benchmark.name, fallback="benchmark"))
    benchmark_revision_id = benchmark.get("current_revision_id")
    if not benchmark_revision_id:
        raise ValueError(
            "hosted benchmark has no immutable revision; publish its ordered task revision first"
        )
    benchmark_revision = client.benchmarks.get_revision(
        str(benchmark["id"]), str(benchmark_revision_id)
    )
    if (
        benchmark_revision.get("environment_revision_id") != environment_revision_id
        or benchmark_revision.get("package_content_hash") != spec.benchmark.content_hash
    ):
        raise ValueError(
            "hosted benchmark revision does not match the local environment and ordered tasks"
        )
    agent_revision_ids: list[str] = []
    local_agent_to_revision: dict[str, str] = {}
    for agent in spec.agents:
        hosted_agent = client.agents.get(slugify(agent.name, fallback="agent")).data
        revision_id = hosted_agent.get("current_revision_id")
        if not revision_id:
            raise ValueError(f"hosted agent {agent.name!r} has no immutable revision")
        harness = client.harnesses.resolve_revision(
            name=agent.harness.name,
            digest=agent.harness.digest,
        )
        if (
            hosted_agent.get("environment_revision_id") != environment_revision_id
            or hosted_agent.get("harness_revision_id") != harness.get("id")
            or hosted_agent.get("package_content_hash") != agent.content_hash
        ):
            raise ValueError(
                f"hosted agent {agent.name!r} is not bound to the exact local "
                "environment and harness revisions"
            )
        agent_revision_ids.append(str(revision_id))
        local_agent_to_revision[agent.agent_id] = str(revision_id)
    client.jobs.preflight(
        benchmark_revision_id=str(benchmark_revision_id),
        agent_revision_ids=agent_revision_ids,
        n_attempts=spec.n_attempts,
        idempotency_key=spec.job_id,
        job_spec=spec,
    )
    hosted_job = client.jobs.create(
        benchmark_revision_id=str(benchmark_revision_id),
        agent_revision_ids=agent_revision_ids,
        n_attempts=spec.n_attempts,
        idempotency_key=spec.job_id,
        spec_hash=spec.content_hash,
        job_spec=spec,
    )
    hosted_trials = client.jobs.trials(str(hosted_job["id"]))
    local_trials = spec.plan().trials
    if len(hosted_trials) != len(local_trials):
        raise ValueError("hosted job expansion does not match the local trial plan")
    trial_keys: dict[str, str] = {}
    for local, hosted in zip(local_trials, hosted_trials, strict=True):
        if (
            hosted.get("task_id") != local.task_id
            or int(hosted.get("attempt") or 0) != local.attempt
            or hosted.get("agent_revision_id") != local_agent_to_revision[local.agent_id]
            or hosted.get("trial_key") != local.trial_id
        ):
            raise ValueError("hosted job trial order does not match the local plan")
        trial_keys[local.trial_id] = str(hosted["trial_key"])
    state_payload = {
        "hosted_job_id": str(hosted_job["id"]),
        "trial_keys": trial_keys,
    }
    store.write_sync_state(spec.job_id, state_payload)
    return client, trial_keys, str(hosted_job["id"])


def _resume_sync(
    state: CLIState,
    store: JobStore,
    job_id: str,
) -> tuple[Any, dict[str, str], str]:
    spec = store.load_spec(job_id)
    client = _hosted_client(state)
    stored = store.read_sync_state(job_id)
    if client is not None and stored is not None:
        hosted_job_id = str(stored.get("hosted_job_id") or "")
        keys = stored.get("trial_keys")
        if hosted_job_id and isinstance(keys, dict):
            return (
                client,
                {str(key): str(value) for key, value in keys.items()},
                hosted_job_id,
            )
    registered = _register_sync(state, spec, store)
    if registered is None:
        raise ValueError(
            "hosted sync requires authentication; run `plural auth login` or set PLURAL_API_KEY"
        )
    return registered


@auth_app.command("login")
def auth_login(
    ctx: typer.Context,
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open a browser."),
) -> None:
    """Authenticate with a browser device flow."""
    state = _state(ctx)
    try:
        with AuthClient(state.context.api_url) as client:
            device, tokens = client.login(
                no_browser=no_browser,
                on_device=lambda value: _emit(
                    {
                        "verification_uri": value.verification_uri,
                        "user_code": value.user_code,
                        "browser_opened": not no_browser,
                    }
                ),
            )
    except (AuthHTTPError, OSError) as exc:
        _error(str(exc))
    state.credentials.set(state.context.profile, tokens.credential())
    _emit(
        {
            "authenticated": True,
            "profile": state.context.profile,
            "verification_uri": device.verification_uri,
        }
    )


@auth_app.command("logout")
def auth_logout(ctx: typer.Context) -> None:
    """Revoke stored tokens and remove local credentials."""
    state = _state(ctx)
    credential = state.credentials.get(state.context.profile)
    if credential is not None:
        try:
            with AuthClient(state.context.api_url) as client:
                client.revoke(credential)
        except (AuthHTTPError, OSError) as exc:
            _error(f"token revocation failed; credentials were retained: {exc}")
    state.credentials.delete(state.context.profile)
    _emit({"authenticated": False, "profile": state.context.profile})


@auth_app.command("status")
def auth_status(ctx: typer.Context) -> None:
    """Check whether the current profile is authenticated."""
    state = _state(ctx)
    credential = _credential(state)
    if credential is None:
        _emit({"authenticated": False, "profile": state.context.profile})
        return
    try:
        with AuthClient(state.context.api_url) as client:
            status = client.status(credential)
    except (AuthHTTPError, OSError) as exc:
        _error(str(exc))
    payload = status.model_dump(mode="json", exclude_none=True)
    payload["profile"] = state.context.profile
    _emit(payload)


@auth_app.command("whoami")
def auth_whoami(ctx: typer.Context) -> None:
    """Show the hosted identity for the current credential."""
    state = _state(ctx)
    credential = _credential(state)
    if credential is None:
        _error("not authenticated; run `plural auth login` or set PLURAL_API_KEY")
    try:
        with AuthClient(state.context.api_url) as client:
            _emit(client.whoami(credential))
    except (AuthHTTPError, OSError) as exc:
        _error(str(exc))


@org_app.command("use")
def org_use(ctx: typer.Context, organization: str) -> None:
    """Select an organization in the active profile."""
    state = _state(ctx)
    updated = _updated_profile(
        state.config,
        state.context.profile,
        organization=organization,
    )
    save_config(updated)
    _emit({"organization": organization, "profile": state.context.profile})


@org_app.command("list")
def org_list() -> None:
    """List hosted organizations."""
    _unsupported("organization listing")


@org_app.command("show")
def org_show(ctx: typer.Context) -> None:
    """Show the resolved organization context."""
    _emit({"organization": _state(ctx).context.organization})


@project_app.command("use")
def project_use(ctx: typer.Context, project: str) -> None:
    """Select a project in the active profile."""
    state = _state(ctx)
    updated = _updated_profile(state.config, state.context.profile, project=project)
    save_config(updated)
    _emit({"project": project, "profile": state.context.profile})


@project_app.command("list")
def project_list() -> None:
    """List hosted projects."""
    _unsupported("project listing")


@project_app.command("show")
def project_show(ctx: typer.Context) -> None:
    """Show the resolved project context."""
    _emit({"project": _state(ctx).context.project})


@env_app.command("init")
def env_init(
    path: Path = typer.Argument(Path("."), help="Package directory."),
    name: str = typer.Option("environment", "--name", help="Environment name."),
    force: bool = typer.Option(False, "--force", help="Replace scaffold files."),
) -> None:
    """Create environment.yaml, environment.py, tasks.jsonl, and Dockerfile."""
    try:
        files = scaffold_environment(path, name, force=force)
    except (FileExistsError, OSError, ValidationError, ValueError) as exc:
        _error(str(exc))
    _emit({"created": [str(item) for item in files]})


@env_app.command("validate")
def env_validate(path: Path = typer.Argument(Path("."))) -> None:
    """Strictly validate a local environment and owned tasks."""
    try:
        environment = load_environment(path)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        _error(str(exc))
    _emit(
        {
            "valid": True,
            "identity": environment.identity.model_dump(mode="json"),
            "tasks": len(environment.tasks),
            "stamped_harnesses": len(environment.harness_policy.allowed_harnesses),
            "actions": len(environment.actions),
            "network": environment.runtime.network.value,
        }
    )


@env_app.command("build")
def env_build(path: Path = typer.Argument(Path("."))) -> None:
    """Build a deterministic local environment manifest artifact."""
    try:
        environment = load_environment(path)
        root_path = path if path.is_dir() else path.parent
        output = root_path / ".plural" / "build" / "environment.manifest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(environment.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        _error(str(exc))
    _emit({"artifact": str(output), "digest": environment.content_hash})


@env_app.command("push")
def env_push(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("."), help="Environment package path."),
) -> None:
    """Publish the exact local environment revision used by job sync."""
    try:
        package = load_environment(path)
        client = _hosted_client(_state(ctx))
        if client is None:
            raise ValueError(
                "environment publication requires authentication; "
                "run `plural auth login` or set PLURAL_API_KEY"
            )
        revision = client.environments.publish_manifest(package)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        _error(f"environment publication failed: {exc}")
    _emit(
        {
            "environment": package.name,
            "revision_id": revision.get("id"),
            "content_hash": revision.get("package_content_hash"),
        }
    )


@env_task_app.command("add")
def env_task_add(
    path: Path = typer.Option(Path("."), "--environment", "-e"),
    task_id: str = typer.Option(..., "--id"),
    input_value: str = typer.Option(..., "--input"),
) -> None:
    """Append a task owned by an environment."""
    try:
        task_path = add_task(path, TaskDefinition(task_id=task_id, input=input_value))
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"task_id": task_id, "path": str(task_path)})


@env_task_app.command("list")
def env_task_list(path: Path = typer.Option(Path("."), "--environment", "-e")) -> None:
    """List environment-owned tasks in deterministic order."""
    try:
        environment = load_environment(path)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit([task.model_dump(mode="json", exclude={"expected"}) for task in environment.tasks])


@env_action_app.command("add")
def env_action_add(
    name: str,
    path: Path = typer.Option(Path("."), "--environment", "-e"),
    description: str = typer.Option(..., "--description"),
    command: list[str] | None = typer.Option(None, "--command"),
) -> None:
    """Add a native action owned by the environment."""
    try:
        destination = add_environment_action(
            path,
            NativeAction(
                name=name,
                description=description,
                command=tuple(command or ()),
            ),
        )
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"updated": str(destination), "action": name})


@env_action_app.command("list")
def env_action_list(path: Path = typer.Option(Path("."), "--environment", "-e")) -> None:
    """List native actions."""
    try:
        environment = load_environment(path)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit([item.model_dump(mode="json") for item in environment.actions])


@env_action_app.command("remove")
def env_action_remove(
    name: str,
    path: Path = typer.Option(Path("."), "--environment", "-e"),
) -> None:
    """Remove a native action."""
    try:
        destination = remove_environment_action(path, name)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"updated": str(destination), "removed": name})


@env_resource_app.command("add")
def env_resource_add(
    name: str,
    kind: str = typer.Option("file", "--kind"),
    path: Path = typer.Option(Path("."), "--environment", "-e"),
    resource_path: str | None = typer.Option(None, "--path"),
) -> None:
    """Add a resource the environment provides."""
    try:
        destination = add_environment_resource(
            path,
            EnvironmentResource(kind=kind, name=name, path=resource_path),  # type: ignore[arg-type]
        )
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"updated": str(destination), "resource": name})


@env_resource_app.command("list")
def env_resource_list(path: Path = typer.Option(Path("."), "--environment", "-e")) -> None:
    """List environment resources."""
    try:
        environment = load_environment(path)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit([item.model_dump(mode="json") for item in environment.resources])


@env_app.command("capabilities")
def env_capabilities(path: Path = typer.Argument(Path("."))) -> None:
    """Show required capabilities and per-target availability."""
    try:
        environment = load_environment(path)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    runtime = environment.runtime
    exclusions = {
        target.value: reason for target, reason in runtime.target_exclusions().items()
    }
    _emit(
        {
            "environment": environment.name,
            "network": runtime.network.value,
            "required_capabilities": sorted(item.value for item in runtime.required_capabilities()),
            "targets": {
                target.value: {
                    "declared": target in runtime.targets,
                    "available": target in runtime.available_targets(),
                    "excluded": exclusions.get(target.value),
                }
                for target in ExecutionTarget
            },
        }
    )


@env_harness_app.command("add")
def env_harness_add(
    harness: Path,
    path: Path = typer.Option(Path("."), "--environment", "-e"),
) -> None:
    """Allow one exact harness revision in an environment."""
    try:
        destination = allow_harness(path, harness)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"updated": str(destination)})


@env_harness_app.command("stamp")
def env_harness_stamp(
    harness: Path,
    path: Path = typer.Option(Path("."), "--environment", "-e"),
) -> None:
    """Stamp a harness onto an environment and show the grant matrix."""
    try:
        destination = allow_harness(path, harness)
        environment = load_environment(path)
        package = load_harness(harness)
        stamp = resolve_harness_stamp(environment, package)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit(
        {
            "updated": str(destination),
            "stamp": stamp.model_dump(mode="json"),
            "granted": sorted(item.value for item in stamp.granted),
            "denied": stamp.denial_reasons,
        }
    )


@env_harness_app.command("unstamp")
def env_harness_unstamp(
    name: str,
    path: Path = typer.Option(Path("."), "--environment", "-e"),
) -> None:
    """Remove a stamped harness from the environment allowlist."""
    try:
        destination = unstamp_harness(path, name)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"updated": str(destination), "removed": name})


@env_harness_app.command("list")
def env_harness_list(path: Path = typer.Option(Path("."), "--environment", "-e")) -> None:
    """List exact harness revisions allowed by an environment."""
    try:
        environment = load_environment(path)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit(
        [item.model_dump(mode="json") for item in environment.harness_policy.allowed_harnesses]
    )


@env_harness_app.command("capabilities")
def env_harness_capabilities(
    harness: Path,
    path: Path = typer.Option(Path("."), "--environment", "-e"),
) -> None:
    """Show granted vs denied capabilities for one stamp."""
    try:
        environment = load_environment(path)
        package = load_harness(harness)
        stamp = resolve_harness_stamp(environment, package)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit(stamp.model_dump(mode="json"))


@harness_app.command("init")
def harness_init(
    path: Path = typer.Argument(Path(".")),
    name: str = typer.Option("harness", "--name"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a harness manifest and local entry point."""
    try:
        files = scaffold_harness(path, name, force=force)
    except (FileExistsError, OSError, ValueError) as exc:
        _error(str(exc))
    _emit({"created": [str(item) for item in files]})


@harness_app.command("validate")
def harness_validate(path: Path = typer.Argument(Path("."))) -> None:
    """Strictly validate source trust and package metadata."""
    try:
        package = load_harness(path)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"valid": True, "package_id": package.package_id, "digest": package.content_hash})


@harness_app.command("build")
def harness_build(path: Path = typer.Argument(Path("."))) -> None:
    """Build a deterministic immutable local harness archive."""
    try:
        package = load_harness(path)
        root_path = path if path.is_dir() else path.parent
        output = (
            root_path
            / ".plural"
            / "build"
            / f"{package.manifest.name}-{package.manifest.version}.tar.gz"
        )
        digest = build_archive(Path(package.source.uri), output)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"artifact": str(output), "digest": digest})


@harness_app.command("test")
def harness_test(
    reference: str = typer.Argument("."),
    digest: str | None = typer.Option(None, "--digest"),
    unsafe_local: bool = typer.Option(False, "--unsafe-local"),
) -> None:
    """Run a local package through protocol conformance."""
    try:
        package = load_harness_reference(reference, digest=digest)
        if package.source.digest is None and not unsafe_local:
            raise ValueError("unsigned local harness test requires --unsafe-local")

        async def check() -> dict[str, Any]:
            provider = LocalProvider()
            requirements = SandboxRequirements(network=NetworkMode.FULL)
            source = materialize_package(package)
            if source is None:
                raise ValueError("OCI harness conformance requires Docker execution")
            handle = await provider.create(requirements)
            try:
                await provider.upload_bundle(handle, source)
                execution = await HarnessRunner(provider).run(
                    handle,
                    package.manifest,
                    HarnessRunRequest(
                        request_id="conformance",
                        task={"task_id": "conformance", "input": "ping", "metadata": {}},
                        agent={"name": "conformance", "model": "test/model"},
                        environment={
                            "name": "conformance",
                            "instructions": "Respond to the test task.",
                            "context": None,
                            "commands": [],
                            "limits": {"max_turns": 1, "max_seconds": 30},
                            "policy": {},
                            "workspace": "/workspace",
                        },
                    ),
                    timeout_seconds=30,
                )
                return {
                    "valid": True,
                    "events": len(execution.events),
                    "outputs": list(execution.output_paths),
                    "artifacts": list(execution.artifact_paths),
                }
            finally:
                await provider.destroy(handle)

        result = asyncio.run(check())
    except (OSError, ValueError, ValidationError, RuntimeError) as exc:
        _error(str(exc))
    _emit(result)


@harness_app.command("publish")
def harness_publish(
    path: Path = typer.Argument(Path(".")),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Publish a deterministic archive to a local path."""
    try:
        package = load_harness(path)
        destination = output or (
            (path if path.is_dir() else path.parent)
            / ".plural"
            / "publish"
            / f"{package.manifest.name}-{package.manifest.version}.tar.gz"
        )
        digest = build_archive(Path(package.source.uri), destination)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"published": str(destination), "digest": digest, "kind": "archive"})


@harness_app.command("add")
def harness_add(
    harness: str,
    environment: Path = typer.Option(Path("."), "--environment", "-e"),
    digest: str | None = typer.Option(None, "--digest"),
) -> None:
    """Add one exact harness revision to an environment allowlist."""
    try:
        package = load_harness_reference(harness, digest=digest)
        destination = allow_harness_package(environment, package)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"updated": str(destination), "harness_digest": package.source.digest})


@harness_app.command("list")
def harness_list(path: Path = typer.Argument(Path("."))) -> None:
    """List local harness manifests in a directory."""
    candidates = [
        path / "harness.yaml",
        *(item / "harness.yaml" for item in path.iterdir() if item.is_dir()),
    ]
    _emit([str(item) for item in candidates if item.exists()])


@harness_app.command("inspect")
def harness_inspect(
    reference: str = typer.Argument("."),
    digest: str | None = typer.Option(None, "--digest"),
) -> None:
    """Inspect a validated harness and its effective immutable binding."""
    try:
        package = load_harness_reference(reference, digest=digest)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit(
        {
            "package": package.model_dump(mode="json"),
            "package_id": package.package_id,
            "content_hash": package.content_hash,
        }
    )


@benchmark_app.command("init")
def benchmark_init(
    path: Path = typer.Argument(Path("benchmark.yaml")),
    name: str = typer.Option("benchmark", "--name"),
    environment: Path = typer.Option(Path("environment.yaml"), "--environment", "-e"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create an ordered benchmark tied to an exact environment revision."""
    try:
        destination = scaffold_benchmark(
            path,
            name=name,
            environment_path=environment,
            force=force,
        )
    except (OSError, ValueError, ValidationError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": str(destination)})


@benchmark_app.command("validate")
def benchmark_validate(
    path: Path = typer.Argument(Path("benchmark.yaml")),
    environment: Path | None = typer.Option(None, "--environment", "-e"),
) -> None:
    """Strictly validate a benchmark and optional environment ownership."""
    try:
        benchmark = load_benchmark(path)
        if environment is not None:
            loaded_environment = load_environment(environment)
            if benchmark.environment != loaded_environment.identity:
                raise ValueError("benchmark environment identity is stale or incompatible")
            owned = {task.task_id for task in loaded_environment.tasks}
            if any(task_id not in owned for task_id in benchmark.task_ids):
                raise ValueError("benchmark selects a task not owned by the environment")
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"valid": True, "digest": benchmark.content_hash})


@benchmark_app.command("show")
def benchmark_show(path: Path = typer.Argument(Path("benchmark.yaml"))) -> None:
    """Show a validated local benchmark definition."""
    try:
        _emit(load_benchmark(path))
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))


@agent_app.command("init")
def agent_init(
    path: Path = typer.Argument(Path("agent.yaml")),
    name: str = typer.Option("agent", "--name"),
    model: str = typer.Option(..., "--model"),
    environment: Path = typer.Option(Path("environment.yaml"), "--environment", "-e"),
    harness: str = typer.Option("harness.yaml", "--harness"),
    harness_digest: str | None = typer.Option(None, "--harness-digest"),
    secret: list[str] | None = typer.Option(None, "--secret"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a local agent config with exactly one harness binding."""
    try:
        destination = scaffold_agent(
            path,
            name=name,
            model=model,
            environment_path=environment,
            harness_path=harness,
            harness_digest=harness_digest,
            secret_names=tuple(secret or ()),
            force=force,
        )
    except (OSError, ValueError, ValidationError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": str(destination)})


@agent_app.command("list")
def agent_list(path: Path = typer.Argument(Path("."))) -> None:
    """List local agent configs; hosted listing follows in the backend phase."""
    candidates = [
        path / "agent.yaml",
        *(item / "agent.yaml" for item in path.iterdir() if item.is_dir()),
    ]
    _emit([str(item) for item in candidates if item.exists()])


@agent_app.command("show")
def agent_show(path: Path = typer.Argument(Path("agent.yaml"))) -> None:
    """Show a validated local agent config."""
    try:
        _emit(load_agent(path))
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))


@agent_template_app.command("init")
def agent_template_init(
    path: Path = typer.Argument(Path("agent.yaml")),
    name: str = typer.Option("agent", "--name"),
    model: str = typer.Option(..., "--model"),
    environment: Path = typer.Option(Path("environment.yaml"), "--environment", "-e"),
    harness: str | None = typer.Option(None, "--harness"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a local agent template."""
    if harness is None:
        try:
            environment_manifest = load_environment(environment)
            destination = path if path.suffix else path / "agent.yaml"
            if destination.exists() and not force:
                raise FileExistsError(f"{destination} already exists; pass --force to replace it")
            template = AgentTemplate(
                name=name,
                model=model,
                environment=environment_manifest.identity,
            )
            from plural.cli.scaffold import write_yaml

            write_yaml(destination, json.loads(template.model_dump_json()))
        except (OSError, ValueError, ValidationError, FileExistsError) as exc:
            _error(str(exc))
        _emit({"created": str(destination)})
        return
    agent_init(
        path=path,
        name=name,
        model=model,
        environment=environment,
        harness=harness,
        harness_digest=None,
        secret=None,
        force=force,
    )


@agent_template_app.command("show")
def agent_template_show(path: Path = typer.Argument(Path("agent.yaml"))) -> None:
    """Show a local agent template."""
    agent_show(path)


@agent_template_app.command("validate")
def agent_template_validate(path: Path = typer.Argument(Path("agent.yaml"))) -> None:
    """Validate a local agent template."""
    try:
        template = load_agent(path)
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit({"valid": True, "digest": template.content_hash})


@agent_template_app.command("push")
def agent_template_push(
    ctx: typer.Context,
    path: Path = typer.Argument(Path("agent.yaml")),
) -> None:
    """Publish a local agent template to the hosted API."""
    try:
        template = load_agent(path)
        client = _hosted_client(_state(ctx))
        if client is None:
            raise ValueError("template publication requires authentication")
        created = client.agents.templates.create(
            name=template.name,
            model=template.model,
            package_spec=template.model_dump(mode="json"),
        )
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        _error(str(exc))
    _emit(created)


def _instance_client(ctx: typer.Context):
    client = _hosted_client(_state(ctx))
    if client is None:
        _error("hosted instance commands require authentication")
    return client


@agent_instance_app.command("list")
def agent_instance_list(ctx: typer.Context) -> None:
    """List hosted agent instances."""
    try:
        _emit(_instance_client(ctx).agents.instances.list())
    except Exception as exc:  # noqa: BLE001
        _error(str(exc))


@agent_instance_app.command("show")
def agent_instance_show(ctx: typer.Context, instance_id: str) -> None:
    """Show one hosted agent instance."""
    try:
        _emit(_instance_client(ctx).agents.instances.get(instance_id))
    except Exception as exc:  # noqa: BLE001
        _error(str(exc))


@agent_instance_app.command("memory")
def agent_instance_memory(ctx: typer.Context, instance_id: str) -> None:
    """List instance memories."""
    try:
        _emit(_instance_client(ctx).agents.instances.memories(instance_id).list())
    except Exception as exc:  # noqa: BLE001
        _error(str(exc))


@agent_instance_app.command("skills")
def agent_instance_skills(ctx: typer.Context, instance_id: str) -> None:
    """List instance skills."""
    try:
        _emit(_instance_client(ctx).agents.instances.skills(instance_id).list())
    except Exception as exc:  # noqa: BLE001
        _error(str(exc))


@agent_instance_app.command("data")
def agent_instance_data(ctx: typer.Context, instance_id: str) -> None:
    """List instance artifacts."""
    try:
        _emit(_instance_client(ctx).agents.instances.data(instance_id).list())
    except Exception as exc:  # noqa: BLE001
        _error(str(exc))


@agent_instance_app.command("experience")
def agent_instance_experience(ctx: typer.Context, instance_id: str) -> None:
    """Show instance experience counters."""
    try:
        _emit(_instance_client(ctx).agents.instances.experience(instance_id))
    except Exception as exc:  # noqa: BLE001
        _error(str(exc))


@runtime_app.command("list")
def runtime_list() -> None:
    """List providers that are genuinely available."""
    _emit([item.model_dump(mode="json") for item in asyncio.run(default_registry.doctors())])


@runtime_app.command("show")
def runtime_show(name: str) -> None:
    """Show one runtime's dynamic availability and capabilities."""
    try:
        runtime = asyncio.run(default_registry.get(name).doctor())
    except KeyError:
        _error(f"unknown runtime {name!r}")
    _emit(runtime)


@runtime_app.command("doctor")
def runtime_doctor(
    name: str = typer.Argument("local"),
    env_path: Path | None = typer.Option(None, "--env"),
) -> None:
    """Check provider health, or evaluate providers against one environment."""
    try:
        if env_path is None:
            runtime = asyncio.run(default_registry.get(name).doctor())
            _emit(runtime)
            return
        environment = load_environment(env_path)
        reports = []
        for doctor in asyncio.run(default_registry.doctors()):
            try:
                provider = default_registry.get(doctor.name)
            except KeyError:
                continue
            capabilities = asyncio.run(provider.capabilities())
            target = (
                ExecutionTarget.LOCAL
                if doctor.name == "local"
                else ExecutionTarget.REMOTE
                if doctor.name == "daytona"
                else ExecutionTarget.DOCKER
            )
            try:
                policy = resolve_effective_policy(
                    environment=environment,
                    template=AgentTemplate(
                        name="doctor",
                        model="openai/gpt-4.1-mini",
                        environment=environment.identity,
                    ),
                    stamp=None,
                    project=ProjectPolicy.permissive(allow_unsafe_local=True),
                    provider=capabilities,
                    requested_target=target,
                )
                reports.append(
                    {
                        "provider": doctor.name,
                        "target": target.value,
                        "ok": True,
                        "enforced": sorted(item.value for item in policy.enforced),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                reports.append(
                    {
                        "provider": doctor.name,
                        "target": target.value,
                        "ok": False,
                        "error": str(exc),
                    }
                )
        _emit({"environment": environment.name, "providers": reports})
    except KeyError:
        _error(f"unknown runtime {name!r}")
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))


@app.command("run")
def run_job(
    ctx: typer.Context,
    job: Path = typer.Argument(Path("job.yaml"), help="Local job.yaml path."),
    agent: list[Path] | None = typer.Option(None, "--agent", help="Override agent config."),
    n_attempts: int | None = typer.Option(None, "--n-attempts", min=1),
    concurrency: int | None = typer.Option(None, "--concurrency", min=1),
    runtime: str | None = typer.Option(None, "--runtime"),
    retry: int | None = typer.Option(None, "--retry", min=0),
    dry_run: bool = typer.Option(False, "--dry-run"),
    print_config: bool = typer.Option(False, "--print-config"),
    sync_enabled: bool = typer.Option(
        False,
        "--sync/--no-sync",
        help="Opt in to best-effort hosted registration and result upload.",
    ),
    unsafe_local: bool = typer.Option(False, "--unsafe-local"),
    output_format: str = typer.Option("json", "--format", help="json, yaml, or text."),
) -> None:
    """Validate, lock, and execute a local client-orchestrated job."""
    if output_format not in {"json", "yaml", "text"}:
        _error("--format must be json, yaml, or text")
    try:
        spec = load_job(job)
        updates: dict[str, Any] = {}
        if agent:
            updates["agents"] = tuple(AgentBinding(template=load_agent(path)) for path in agent)
        if n_attempts is not None:
            updates["n_attempts"] = n_attempts
        if concurrency is not None:
            updates["concurrency"] = concurrency
        if runtime is not None:
            runtime_updates: dict[str, Any] = {"provider": runtime}
            if (
                runtime == "docker"
                and spec.environment.runtime.image is None
                and spec.environment.runtime.build_context is None
            ):
                job_source = job / "job.yaml" if job.is_dir() else job
                raw_job = yaml.safe_load(job_source.read_text(encoding="utf-8"))
                if not isinstance(raw_job, dict) or not isinstance(raw_job.get("environment"), str):
                    raise ValueError("job environment path is required for Docker build")
                environment_path = Path(raw_job["environment"])
                if not environment_path.is_absolute():
                    environment_path = job_source.parent / environment_path
                environment_source = (
                    environment_path if environment_path.is_dir() else environment_path.parent
                )
                updates["environment"] = spec.environment.model_copy(
                    update={
                        "runtime": spec.environment.runtime.model_copy(
                            update={"build_context": str(environment_source.resolve())}
                        )
                    }
                )
            updates["runtime"] = spec.runtime.model_copy(update=runtime_updates)
        if unsafe_local:
            base_runtime = updates.get("runtime", spec.runtime)
            updates["runtime"] = base_runtime.model_copy(
                update={"provider": "local", "unsafe_local": True}
            )
            env_runtime = (updates.get("environment") or spec.environment).runtime
            updates["environment"] = (updates.get("environment") or spec.environment).model_copy(
                update={
                    "runtime": env_runtime.model_copy(
                        update={
                            "network": NetworkMode.FULL,
                            "network_allowlist": (),
                            "allow_unsafe_local": True,
                            "build_context": None,
                            "dockerfile": None,
                            "targets": frozenset(
                                {*env_runtime.targets, ExecutionTarget.LOCAL}
                            ),
                        }
                    )
                }
            )
        if retry is not None:
            updates["retry"] = RetryPolicy(
                max_retries=retry,
                retryable_codes=spec.retry.retryable_codes,
            )
        if updates:
            if "environment" in updates:
                environment = updates["environment"]
                rebound: list[AgentBinding] = []
                for binding in updates.get("agents", spec.agents):
                    template = binding.template.model_copy(
                        update={"environment": environment.identity}
                    )
                    if template.harness_package is not None:
                        template = template.model_copy(
                            update={
                                "stamp": resolve_harness_stamp(
                                    environment, template.harness_package
                                )
                            }
                        )
                    rebound.append(AgentBinding(template=template, instance=binding.instance))
                updates["agents"] = tuple(rebound)
                if "benchmark" not in updates:
                    updates["benchmark"] = spec.benchmark.model_copy(
                        update={"environment": environment.identity}
                    )
            spec = type(spec).model_validate({**spec.model_dump(mode="json"), **updates})
        plan = spec.plan()
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        _error(str(exc))
    if print_config:
        _emit(spec, output_format)
        return
    if dry_run:
        _emit(
            {
                "dry_run": True,
                "sync": sync_enabled,
                "job_id": plan.job_id,
                "spec_hash": plan.spec_hash,
                "trial_count": plan.trial_count,
                "lock": plan.lock.model_dump(mode="json"),
                "trials": [
                    {**item.model_dump(mode="json"), "trial_id": item.trial_id}
                    for item in plan.trials
                ],
            },
            output_format,
        )
        return
    store = JobStore(job.resolve().parent / ".plural" / "jobs")
    hosted_sync: tuple[Any, dict[str, str], str] | None = None
    sync_error: str | None = None
    if sync_enabled:
        try:
            hosted_sync = _register_sync(_state(ctx), spec, store)
        except Exception as exc:  # noqa: BLE001
            sync_error = str(exc)
            typer.echo(
                f"Hosted sync deferred: {sync_error}. Local execution will continue.",
                err=True,
            )

    def progress(trial: Any, result: Any) -> None:
        nonlocal sync_error
        typer.echo(
            f"{trial.trial_id} {result.status}"
            + (f" ({result.error_code.value})" if result.error_code else ""),
            err=True,
        )
        if hosted_sync is not None:
            client, trial_keys, hosted_job_id = hosted_sync
            try:
                client.jobs.upload_results(
                    hosted_job_id,
                    trial_keys=[trial_keys[trial.trial_id]],
                    results=[result],
                    batch_size=1,
                )
            except Exception as exc:  # noqa: BLE001
                sync_error = str(exc)

    try:
        execution = ExecutionJob(spec, store=store, progress=progress)
        result = asyncio.run(execution.run())
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        if hosted_sync is not None:
            with suppress(Exception):
                hosted_sync[0].jobs.fail(
                    hosted_sync[2],
                    error_code="local_execution_failed",
                    error_message=str(exc),
                )
        _error(str(exc))
    if hosted_sync is not None:
        client, trial_keys, hosted_job_id = hosted_sync
        try:
            ordered_keys = [trial_keys[item.trial_id] for item in execution.plan.trials]
            client.jobs.upload_results(
                hosted_job_id,
                trial_keys=ordered_keys,
                results=result.trials,
            )
            client.jobs.finalize(hosted_job_id, execution.report(result))
            sync_error = None
        except Exception as exc:  # noqa: BLE001
            sync_error = str(exc)
    if sync_enabled and sync_error is not None:
        typer.echo(
            "Hosted sync incomplete; local results are safe. Retry with "
            f"`plural job upload {result.job_id} --store {store.root}`: {sync_error}",
            err=True,
        )
    _emit(result, output_format)
    if any(item.status != "succeeded" for item in result.trials):
        raise typer.Exit(1)


@job_app.command("init")
def job_init(
    path: Path = typer.Argument(Path("job.yaml")),
    environment: Path = typer.Option(Path("environment.yaml"), "--environment", "-e"),
    benchmark: Path = typer.Option(Path("benchmark.yaml"), "--benchmark", "-b"),
    agent: list[Path] = typer.Option(..., "--agent"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create a path-based job.yaml."""
    try:
        destination = scaffold_job(
            path,
            environment_path=environment,
            benchmark_path=benchmark,
            agent_paths=tuple(agent),
            force=force,
        )
    except (OSError, ValueError, ValidationError, FileExistsError) as exc:
        _error(str(exc))
    _emit({"created": str(destination)})


@job_app.command("list")
def job_list(path: Path = typer.Argument(Path(".plural/jobs"))) -> None:
    """List durable local job records."""
    _emit(JobStore(path).list_jobs())


@job_app.command("show")
def job_show(
    identifier: str = typer.Argument("job.yaml"),
    store_path: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Show a path-based job config or durable job record."""
    try:
        path = Path(identifier)
        if path.exists():
            spec = load_job(path)
            result = None
        else:
            store = JobStore(store_path)
            spec = store.load_spec(identifier)
            result = store.read_job_result(identifier)
        plan = spec.plan()
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit(
        {
            "job_id": plan.job_id,
            "trial_count": plan.trial_count,
            "spec": spec.model_dump(mode="json"),
            "lock": plan.lock.model_dump(mode="json"),
            "result": result.model_dump(mode="json") if result is not None else None,
        }
    )


def _stored_execution(
    job_id: str,
    store_path: Path,
    *,
    regrade: bool = False,
) -> None:
    try:
        store = JobStore(store_path)
        spec = store.load_spec(job_id)
        execution = ExecutionJob(spec, store=store)
        result = asyncio.run(execution.regrade() if regrade else execution.run(resume=True))
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        _error(str(exc))
    _emit(result)


@job_app.command("resume")
def job_resume(
    job_id: str,
    store_path: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Resume a compatible locked job, skipping successful trials."""
    _stored_execution(job_id, store_path)


@job_app.command("retry")
def job_retry(
    job_id: str,
    store_path: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Retry failed trials without creating new Trial identities."""
    _stored_execution(job_id, store_path)


@job_app.command("regrade")
def job_regrade(
    job_id: str,
    store_path: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Rerun only the isolated verifier over immutable artifacts."""
    _stored_execution(job_id, store_path, regrade=True)


@job_app.command("cancel")
def job_cancel(
    job_id: str,
    store_path: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Request cancellation for a local job."""
    try:
        store = JobStore(store_path)
        store.load_lock(job_id)
        store.request_cancel(job_id)
    except (OSError, ValueError) as exc:
        _error(str(exc))
    _emit({"job_id": job_id, "cancel_requested": True})


@job_app.command("upload")
def job_upload(
    ctx: typer.Context,
    job_id: str,
    store_path: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Replay a stored local job sync without launching hosted execution."""
    store = JobStore(store_path)
    try:
        spec = store.load_spec(job_id)
        result = store.read_job_result(job_id)
        if result is None:
            raise ValueError("local job has no complete result; resume or retry it before upload")
        client, trial_keys, hosted_job_id = _resume_sync(_state(ctx), store, job_id)
        plan = spec.plan()
        ordered_keys = [trial_keys[item.trial_id] for item in plan.trials]
        uploaded = client.jobs.upload_results(
            hosted_job_id,
            trial_keys=ordered_keys,
            results=result.trials,
        )
        report = ExecutionJob(spec, store=store).report(result)
        hosted = client.jobs.finalize(hosted_job_id, report)
    except (OSError, ValueError, ValidationError, KeyError, RuntimeError) as exc:
        _error(str(exc))
    except Exception as exc:  # noqa: BLE001
        _error(f"hosted upload failed; local results were retained: {exc}")
    _emit(
        {
            "job_id": job_id,
            "hosted_job_id": hosted_job_id,
            "uploaded_executions": uploaded,
            "status": hosted.get("status"),
            "benchmark_run_id": hosted.get("benchmark_run_id"),
        }
    )


@trial_app.command("list")
def trial_list(
    identifier: str,
    store_path: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """List planned trials with local result status."""
    try:
        path = Path(identifier)
        if path.exists():
            plan = load_job(path).plan()
            stored: dict[str, Any] = {}
        else:
            store = JobStore(store_path)
            plan = store.load_spec(identifier).plan()
            stored = {item.receipt.trial_id: item for item in store.trial_results(identifier)}
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    _emit(
        [
            {
                "trial_id": item.trial_id,
                "agent": item.agent_name,
                "task_id": item.task_id,
                "attempt": item.attempt,
                "status": (stored[item.trial_id].status if item.trial_id in stored else "pending"),
            }
            for item in plan.trials
        ]
    )


@trial_app.command("show")
def trial_show(
    trial_id: str,
    job: str = typer.Option("job.yaml", "--job"),
    store_path: Path = typer.Option(Path(".plural/jobs"), "--store"),
) -> None:
    """Show one planned trial and its persisted result."""
    try:
        path = Path(job)
        spec = load_job(path) if path.exists() else JobStore(store_path).load_spec(job)
        trial = next(
            (item for item in spec.plan().trials if item.trial_id == trial_id),
            None,
        )
        stored_result = (
            None
            if path.exists()
            else next(
                (
                    item
                    for item in JobStore(store_path).trial_results(job)
                    if item.receipt.trial_id == trial_id
                ),
                None,
            )
        )
    except (OSError, ValueError, ValidationError) as exc:
        _error(str(exc))
    if trial is None:
        _error(f"trial {trial_id!r} was not found in {job}")
    _emit(
        {
            **trial.model_dump(mode="json"),
            "trial_id": trial.trial_id,
            "result": (
                stored_result.model_dump(mode="json") if stored_result is not None else None
            ),
        }
    )


def main() -> None:
    """Run the console entry point."""
    try:
        app()
    except KeyboardInterrupt:
        typer.echo("Cancelled.", err=True)
        sys.exit(130)


__all__ = ["app", "main"]
