"""Run an Environment's Apps inside a Trial's Runtime.

The Job starts one App host per Trial in the Environment workspace, before the
Harness runs. Every action the Harness takes is a short client command that
talks to that host, so the Harness never holds App secrets. After the episode
the Job asks the host for each App's snapshots, lets function Verifiers query
the still-running Apps, and stops the host before the Runtime is destroyed.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from typing import Any

from plural.environments.definition import EnvironmentDefinition
from plural.environments.env import normalize_initial_state
from plural.sandbox import ExecRequest, FileUpload, SandboxHandle, SandboxProvider
from plural.tasks import TaskDefinition

WORKSPACE = "/workspace/environment"
HOST_COMMAND = ("python", "-m", "plural.apps.daemon")
START_TIMEOUT_SECONDS = 180.0
FINISH_TIMEOUT_SECONDS = 300.0


class AppHostError(RuntimeError):
    """The App host could not start or answer."""


def action_command(name: str) -> tuple[str, ...]:
    """The command a Harness runs for one exposed action."""
    return (*HOST_COMMAND, "step", name)


def environment_payload(task: TaskDefinition) -> dict[str, Any]:
    """What a Harness learns about the Environment.

    It lists each exposed action with the command that runs it, and nothing
    about App state, rewarders, or secrets.

    Returns:
        The ``environment`` field of the Harness run request.
    """
    environment = task.environment
    return {
        "name": environment.name,
        "overview": environment.overview,
        "limits": environment.limits.model_dump(mode="json"),
        "guardrails": [item.model_dump(mode="json") for item in environment.guardrails],
        "resources": [item.model_dump(mode="json") for item in environment.resources],
        "workspace": WORKSPACE,
        "apps": [
            {"name": item.name, "description": item.description, "control": item.control}
            for item in environment.apps
        ],
        "actions": [
            {
                "name": item.name,
                "app": item.app,
                "description": item.description,
                "parameters": item.parameters,
                "mutates_state": item.mutates_state,
                "timeout_seconds": item.timeout_seconds,
                "command": list(action_command(item.name)),
            }
            for item in environment.actions
        ],
        "reset_command": list((*HOST_COMMAND, "reset")) if environment.apps else [],
    }


def missing_app_secrets(
    environment: EnvironmentDefinition, environ: Mapping[str, str]
) -> dict[str, list[str]]:
    """Required App secrets with no value, grouped by App.

    Returns:
        App name to the missing names.
    """
    missing: dict[str, list[str]] = {}
    for app in environment.apps:
        names = [item.name for item in app.secrets if item.required and not environ.get(item.name)]
        if names:
            missing[app.name] = names
    return missing


def describe_missing(missing: Mapping[str, list[str]]) -> str:
    """A message naming each App's missing secrets, never their values.

    Returns:
        The message.
    """
    lines = [f"  App {app!r} needs {', '.join(names)}" for app, names in missing.items()]
    return (
        "The Environment's Apps are missing secrets:\n"
        + "\n".join(lines)
        + "\nExport those names before the run, or set them in the hosted project with "
        "`plural secret set NAME`."
    )


def app_secret_values(
    environment: EnvironmentDefinition, environ: Mapping[str, str]
) -> dict[str, str]:
    """Every App secret value available in ``environ``.

    Returns:
        Name to value.

    Raises:
        ValueError: When a required App secret is missing.
    """
    missing = missing_app_secrets(environment, environ)
    if missing:
        raise ValueError(describe_missing(missing))
    return {item.name: environ[item.name] for item in environment.secrets if environ.get(item.name)}


def host_files(task: TaskDefinition) -> tuple[FileUpload, ...]:
    """The files the App host reads: the Environment and the Task's starting point.

    Returns:
        Uploads relative to the Environment workspace.
    """
    environment = task.environment
    state = normalize_initial_state(environment, task.state or {})
    task_file = {"initial_state": state, "info": task.info, "seed": None}
    return (
        FileUpload(
            path=".plural/apps/environment.json",
            data=environment.model_dump_json().encode(),
        ),
        FileUpload(
            path=".plural/apps/task.json",
            data=(json.dumps(task_file, sort_keys=True, default=str) + "\n").encode(),
        ),
    )


async def _host(
    provider: SandboxProvider,
    handle: SandboxHandle,
    operation: tuple[str, ...],
    *,
    env: Mapping[str, str],
    timeout: float,
    stdin: bytes | None = None,
) -> Any:
    result = await provider.exec(
        handle,
        ExecRequest(
            command=(*HOST_COMMAND, *operation),
            cwd=WORKSPACE,
            env=dict(env),
            timeout_seconds=timeout,
            stdin=stdin,
        ),
    )
    if result.timed_out:
        raise AppHostError(f"App host {operation[0]} timed out after {timeout:g}s")
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()[-3000:]
        raise AppHostError(f"App host {operation[0]} failed: {detail}")
    text = result.stdout.decode(errors="replace").strip()
    try:
        return json.loads(text.splitlines()[-1]) if text else None
    except json.JSONDecodeError as exc:
        raise AppHostError(f"App host {operation[0]} printed no JSON: {text[-500:]}") from exc


async def start_host(
    provider: SandboxProvider,
    handle: SandboxHandle,
    *,
    env: Mapping[str, str],
    secrets: Mapping[str, str],
) -> None:
    """Start the App host with the Runtime variables and the Apps' secrets.

    Secret values travel on stdin, not in any process environment.
    """
    await _host(
        provider,
        handle,
        ("start",),
        env=env,
        timeout=START_TIMEOUT_SECONDS,
        stdin=json.dumps(dict(secrets)).encode(),
    )


async def finish_host(
    provider: SandboxProvider, handle: SandboxHandle, *, env: Mapping[str, str]
) -> dict[str, Any]:
    """Each App's control level and initial and final snapshots.

    Returns:
        App name to ``{control, initial, final}``; empty when the host is gone.
    """
    report = await _host(provider, handle, ("finish",), env=env, timeout=FINISH_TIMEOUT_SECONDS)
    return report if isinstance(report, dict) else {}


async def query_host(
    provider: SandboxProvider,
    handle: SandboxHandle,
    app: str,
    action: str,
    arguments: Mapping[str, Any],
    *,
    env: Mapping[str, str],
    timeout: float,
) -> Any:
    """Run one read-only App action for a Verifier.

    Returns:
        The action's observation.
    """
    return await _host(
        provider,
        handle,
        ("query", app, action),
        env=env,
        timeout=timeout,
        stdin=json.dumps(dict(arguments)).encode(),
    )


async def stop_host(
    provider: SandboxProvider, handle: SandboxHandle, *, env: Mapping[str, str]
) -> None:
    """Stop the App host so Apps close their sessions before teardown."""
    with contextlib.suppress(Exception):
        await _host(provider, handle, ("stop",), env=env, timeout=60)


__all__ = [
    "HOST_COMMAND",
    "WORKSPACE",
    "AppHostError",
    "action_command",
    "app_secret_values",
    "describe_missing",
    "environment_payload",
    "finish_host",
    "host_files",
    "missing_app_secrets",
    "query_host",
    "start_host",
    "stop_host",
]
