"""Run an Environment's Apps inside a Trial's Runtime.

The Job starts one App host per Trial in the Environment workspace, before the
Harness runs. Every action the Harness takes is a short client command that
talks to that host, so the Harness never holds App secrets. After the episode
the Job asks the host for each App's snapshots, lets function Verifiers query
the still-running Apps, and stops the host before the Runtime is destroyed.
"""

from __future__ import annotations

import contextlib
import inspect
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from plural.environments.definition import EnvironmentDefinition
from plural.environments.env import normalize_initial_state
from plural.sandbox import ExecRequest, FileUpload, SandboxHandle, SandboxProvider
from plural.tasks import TaskDefinition
from plural.verifiers import DeterministicVerifier

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
    about App state, verifiers, or secrets.

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


def _source_files(folder: Path) -> list[Path]:
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    )


def reward_hook_files(task: TaskDefinition) -> tuple[list[dict[str, str]], list[FileUpload]]:
    """The Task's ``reward`` hooks, and their source, for the App host to import.

    A project Verifier ships its whole folder; a function defined elsewhere
    ships the one file it is defined in.

    Returns:
        One entry per hook for the host's task file, and the files to stage.

    Raises:
        ValueError: When a hook was never imported, so its code is not here.
    """
    entries: list[dict[str, str]] = []
    uploads: list[FileUpload] = []
    for binding in task.verifiers:
        verifier = binding.verifier
        if not isinstance(verifier, DeterministicVerifier) or verifier.reward is None:
            continue
        hook = verifier.reward_fn
        if hook is None:
            raise ValueError(
                f"Verifier {verifier.name!r} names its reward hook {verifier.reward_ref!r}, but "
                "it was never imported, so there is no code to run. Load the Task from its "
                "project, or pass the function itself."
            )
        source = inspect.getsourcefile(hook)
        if source is None:
            raise ValueError(f"Verifier {verifier.name!r}: cannot find the reward hook's source.")
        path = Path(source).resolve()
        folder = verifier.source_dir.resolve() if verifier.source_dir else path.parent
        files = _source_files(folder) if verifier.source_dir else [path]
        stage = f".plural/verifiers/{verifier.name}"
        uploads.extend(
            FileUpload(
                path=f"{stage}/{item.relative_to(folder).as_posix()}", data=item.read_bytes()
            )
            for item in files
        )
        entries.append(
            {
                "name": verifier.name,
                "version": verifier.version,
                "dir": stage,
                "python": f"{path.relative_to(folder).as_posix()}:{hook.__qualname__}",
            }
        )
    return entries, uploads


def host_files(task: TaskDefinition) -> tuple[FileUpload, ...]:
    """The files the App host reads: the Environment, the Task, and its ``reward`` hooks.

    The Task's initial State never lands here: it would sit in the shared
    workspace where the Harness could read it, so a Job sends it to the host on
    stdin with :func:`host_inputs`. The file names only the Task and its
    Verifiers.

    Returns:
        Uploads relative to the Environment workspace.
    """
    environment = task.environment
    verifiers, sources = reward_hook_files(task)
    task_file = {
        "task": {"name": task.task_id, "metadata": task.metadata},
        "verifiers": verifiers,
    }
    return (
        FileUpload(
            path=".plural/apps/environment.json",
            data=environment.model_dump_json().encode(),
        ),
        FileUpload(
            path=".plural/apps/task.json",
            data=(json.dumps(task_file, sort_keys=True, default=str) + "\n").encode(),
        ),
        *sources,
    )


def host_inputs(task: TaskDefinition) -> dict[str, Any]:
    """The Task's reset inputs, for the host's start stdin rather than a file.

    Returns:
        The initial State, info, and seed the host resets each App with.
    """
    return {
        "initial_state": normalize_initial_state(task.environment, task.state or {}),
        "info": task.info,
        "seed": None,
    }


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
    token: str,
    inputs: Mapping[str, Any],
) -> None:
    """Start the App host with the Runtime variables, the Apps' secrets, and a control token.

    Secret values, the Task's initial State, and the token travel on stdin, not
    in any process environment or file. Only a caller with the token can read
    the Apps' State or end the episode.
    """
    await _host(
        provider,
        handle,
        ("start",),
        env=env,
        timeout=START_TIMEOUT_SECONDS,
        stdin=json.dumps(
            {"secrets": dict(secrets), "token": token, "inputs": dict(inputs)}, default=str
        ).encode(),
    )


def _controlled(env: Mapping[str, str]) -> dict[str, str]:
    return {**env, "PLURAL_APPS_CONTROL_STDIN": "1"}


def _token(token: str, arguments: Mapping[str, Any] | None = None) -> bytes:
    return json.dumps({"token": token, "arguments": dict(arguments or {})}).encode()


async def finish_host(
    provider: SandboxProvider, handle: SandboxHandle, *, env: Mapping[str, str], token: str
) -> dict[str, Any]:
    """Each App's control level and initial and final snapshots.

    Returns:
        App name to ``{control, initial, final}``; empty when the host is gone.
    """
    report = await _host(
        provider,
        handle,
        ("finish",),
        env=_controlled(env),
        timeout=FINISH_TIMEOUT_SECONDS,
        stdin=_token(token),
    )
    return report if isinstance(report, dict) else {}


async def states_host(
    provider: SandboxProvider, handle: SandboxHandle, *, env: Mapping[str, str], token: str
) -> list[dict[str, Any]]:
    """Each step's recorded App State, kept in the host rather than on the shared disk.

    Returns:
        One entry per step; empty when the host recorded none.
    """
    result = await _host(
        provider,
        handle,
        ("states",),
        env=_controlled(env),
        timeout=FINISH_TIMEOUT_SECONDS,
        stdin=_token(token),
    )
    return result if isinstance(result, list) else []


async def query_host(
    provider: SandboxProvider,
    handle: SandboxHandle,
    app: str,
    action: str,
    arguments: Mapping[str, Any],
    *,
    env: Mapping[str, str],
    timeout: float,
    token: str,
) -> Any:
    """Run one read-only App action for a Verifier.

    Returns:
        The action's observation.
    """
    return await _host(
        provider,
        handle,
        ("query", app, action),
        env=_controlled(env),
        timeout=timeout,
        stdin=_token(token, arguments),
    )


async def stop_host(
    provider: SandboxProvider, handle: SandboxHandle, *, env: Mapping[str, str], token: str
) -> None:
    """Stop the App host so Apps close their sessions before teardown."""
    with contextlib.suppress(Exception):
        await _host(
            provider, handle, ("stop",), env=_controlled(env), timeout=60, stdin=_token(token)
        )


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
    "host_inputs",
    "missing_app_secrets",
    "query_host",
    "start_host",
    "states_host",
    "reward_hook_files",
    "stop_host",
]
