"""Run an Environment's Apps inside a Trial's Runtime.

The Job starts one App host per Trial in the Environment workspace, before the
Harness runs. Every action the Harness takes is a short client command that
talks to that host, so the Harness never holds App secrets, and sees only each
action's observation. After the episode the Job reads the host's report: each
step with its rewards, each step's App State, and each App's snapshots. It
lets function Verifiers query the still-running Apps, and stops the host
before the Runtime is destroyed.

Every request the Job sends is signed with a per-Trial token the Harness never
sees, and every answer is checked outside the Runtime, so nothing the Harness
runs can impersonate the host or alter what it reports. Where the Runtime can
(:meth:`~plural.sandbox.SandboxProvider.isolate_apps`), the host also runs as
its own OS user, so the Harness cannot read the host's folder or memory.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from plural.apps.daemon import (
    BOOTSTRAP_FILE,
    ENVIRONMENT_FILE,
    TASK_FILE,
    AppHostTampered,
    canonical,
    signed_request,
    verify_response,
)
from plural.environments.definition import EnvironmentDefinition
from plural.environments.env import normalize_initial_state
from plural.sandbox import (
    AppIsolation,
    CapabilityError,
    ExecRequest,
    ExecResult,
    FileUpload,
    SandboxHandle,
    SandboxProvider,
)
from plural.tasks import TaskDefinition
from plural.verifiers import DeterministicVerifier

WORKSPACE = "/workspace/environment"
HOST_COMMAND = ("python", "-m", "plural.apps.daemon")
START_TIMEOUT_SECONDS = 180.0
FINISH_TIMEOUT_SECONDS = 300.0
VERIFIER_STAGE = ".plural/verifiers"
_STAGED = (ENVIRONMENT_FILE, TASK_FILE, BOOTSTRAP_FILE, VERIFIER_STAGE)
_SEAL = """
import shutil, sys
from pathlib import Path
root = Path(sys.argv[1])
for name in sys.argv[2:]:
    path = root / name
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()
    if path.exists() or path.is_symlink():
        sys.exit(f"could not remove {path}")
"""
_READABLE = "import os, sys; sys.exit(0 if os.access(sys.argv[1], os.R_OK) else 1)"


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
        **(
            {"turn_command": list((*HOST_COMMAND, "turn"))}
            if task.party is not None and environment.apps
            else {}
        ),
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


HOST_READABLE = 0o644
"""Staged files the App host's own user must read. They are removed once it has
copied them, before the Harness starts."""


def reward_hook_files(task: TaskDefinition) -> tuple[list[dict[str, str]], list[FileUpload]]:
    """The Task's ``reward`` hooks, and their source, for the App host to import.

    A project Verifier ships its whole folder; a function defined elsewhere
    ships the one file it is defined in. The files are staged only until the
    App host has copied them into its private folder, then removed.

    Returns:
        One entry per hook for the host's task file, and the files to stage.

    Raises:
        ValueError: When a hook was never imported, so its code is not here.
    """
    entries: list[dict[str, str]] = []
    uploads: list[FileUpload] = []
    for index, binding in enumerate(task.verifiers):
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
        # By position, not name: a name is free text and must not shape a path.
        stage = f"{VERIFIER_STAGE}/{index}"
        uploads.extend(
            FileUpload(
                path=f"{stage}/{item.relative_to(folder).as_posix()}",
                data=item.read_bytes(),
                mode=HOST_READABLE,
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


def verifier_sources(task: TaskDefinition) -> list[Path]:
    """Every file or folder holding a Task Verifier's code, on this machine.

    The Environment's source package must not ship these to the Runtime,
    where the Harness could read them.

    Returns:
        The resolved paths.
    """
    paths: list[Path] = []
    for binding in task.verifiers:
        verifier = binding.verifier
        if not isinstance(verifier, DeterministicVerifier):
            continue
        if verifier.source_dir is not None:
            paths.append(verifier.source_dir.resolve())
            continue
        for hook in (verifier.check_fn, verifier.reward_fn, verifier.hindsight_fn):
            if hook is None:
                continue
            try:
                source = inspect.getsourcefile(hook)
            except TypeError:
                source = None
            if source is not None:
                paths.append(Path(source).resolve())
    return list(dict.fromkeys(paths))


def app_private_files(environment: EnvironmentDefinition) -> list[str]:
    """Workspace files only the App host reads, named by the Apps' own settings.

    A Python App's class file, an MCP App's ``server`` file, a replay App's
    recordings and tools, and an OpenAPI App's local document. Once the host
    has copied the workspace these leave the Agent's view, so it cannot read
    an App's answers or internals instead of using its actions.

    Returns:
        Workspace-relative paths.
    """
    names: list[str] = []
    for app in environment.apps:
        config = app.config
        candidates = [
            app.python.split(":", 1)[0] if app.python else None,
            str(config["server"]).split(":", 1)[0] if config.get("server") else None,
            config.get("recordings"),
            config.get("tools") if app.kind == "replay" else None,
            config.get("spec") if app.kind == "openapi" else None,
        ]
        for item in candidates:
            if not isinstance(item, str) or not item or "://" in item:
                continue
            path = PurePosixPath(item)
            if path.is_absolute() or ".." in path.parts:
                continue
            names.append(path.as_posix())
    return list(dict.fromkeys(names))


def host_files(task: TaskDefinition) -> tuple[FileUpload, ...]:
    """The files the App host reads: the Environment, the Task, and its ``reward`` hooks.

    The Task's initial State never lands here: it would sit in the shared
    workspace where the Harness could read it, so a Job sends it to the host
    in the bootstrap with :func:`host_inputs`. The file names only the Task
    and its Verifiers, and is removed once the host has started.

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
            path=ENVIRONMENT_FILE, data=environment.model_dump_json().encode(), mode=HOST_READABLE
        ),
        FileUpload(
            path=TASK_FILE,
            data=(json.dumps(task_file, sort_keys=True, default=str) + "\n").encode(),
            mode=HOST_READABLE,
        ),
        *sources,
    )


def trial_seed(task_digest: str, attempt: int) -> int:
    """The seed one attempt of a Task starts from.

    It depends only on the Task and the attempt, so every Agent on that attempt
    faces the same world, and a rerun faces it again.

    Returns:
        A 32-bit seed.
    """
    digest = hashlib.sha256(f"{task_digest}:{attempt}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def host_inputs(task: TaskDefinition, *, seed: int) -> dict[str, Any]:
    """The Task's reset inputs, for the host's bootstrap rather than a file.

    Returns:
        The initial State, info, and seed the host resets each App with.
    """
    return {
        "initial_state": normalize_initial_state(task.environment, task.state or {}),
        "info": task.info,
        "seed": seed,
    }


@dataclass
class HostReport:
    """What the App host recorded over one episode, as its signed answer gave it.

    ``apps`` maps each App to its control level and ``initial``/``final``
    snapshots. ``steps`` holds every action the Harness took, in order, with
    its observation, rewards, and info. ``states`` holds the App State after
    each step. ``observation`` and ``view`` are the last ones.
    """

    apps: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    states: list[dict[str, Any]] = field(default_factory=list)
    observation: dict[str, Any] = field(default_factory=dict)
    view: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, value: Any) -> HostReport:
        """Read the host's ``finish`` answer.

        Returns:
            The report; empty fields for anything missing or malformed.
        """
        if not isinstance(value, Mapping):
            return cls()

        def mapping(key: str) -> dict[str, Any]:
            item = value.get(key)
            return dict(item) if isinstance(item, Mapping) else {}

        def rows(key: str) -> list[dict[str, Any]]:
            items = value.get(key)
            if not isinstance(items, list):
                return []
            return [dict(item) for item in items if isinstance(item, Mapping)]

        return cls(
            apps=mapping("apps"),
            steps=rows("steps"),
            states=rows("states"),
            observation=mapping("observation"),
            view=mapping("view"),
        )


class AppHostSession:
    """The Job's side of one Trial's App host.

    Args:
        provider: The Runtime's sandbox provider.
        handle: The Trial's sandbox.
        env: Variables every host process gets, such as ``PYTHONPATH``.
        token: The per-Trial control token. It stays in the Job.
        isolation: The users the host and the Harness run as.
    """

    def __init__(
        self,
        provider: SandboxProvider,
        handle: SandboxHandle,
        *,
        env: Mapping[str, str],
        token: str,
        isolation: AppIsolation | None = None,
        private_files: Sequence[str] = (),
    ) -> None:
        self.provider = provider
        self.handle = handle
        self.env = dict(env)
        self.token = token
        self.isolation = isolation or AppIsolation()
        self.private_files = tuple(private_files)
        self.private: str | None = None
        self.isolated = False

    async def _exec(
        self,
        command: Sequence[str],
        *,
        timeout: float,
        stdin: bytes | None = None,
        user: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        result = await self.provider.exec(
            self.handle,
            ExecRequest(
                command=tuple(command),
                # Not the workspace: Python would import whatever the Harness left there.
                cwd="/",
                env=dict(self.env if env is None else env),
                timeout_seconds=timeout,
                stdin=stdin,
                user=user,
            ),
        )
        if result.timed_out:
            name = command[3] if len(command) > 3 else command[0]
            raise AppHostError(f"App host {name} timed out after {timeout:g}s")
        return result

    async def start(
        self,
        *,
        secrets: Mapping[str, str],
        inputs: Mapping[str, Any],
        seats: Mapping[str, str] | None = None,
    ) -> None:
        """Start the host as the App user, then remove what was staged for it.

        Secret values, the Task's initial State, the token, and each seat's
        token travel on stdin. A Runtime without stdin gets them in a staging file the host
        never copies, removed before the Harness starts.

        Raises:
            AppHostError: When the host does not start or answer.
        """
        bootstrap = json.dumps(
            {
                "secrets": dict(secrets),
                "token": self.token,
                "inputs": dict(inputs),
                "seats": dict(seats or {}),
            },
            default=str,
        ).encode()
        command = (*HOST_COMMAND, "start", WORKSPACE)
        user = self.isolation.app_user
        try:
            try:
                result = await self._exec(
                    command, timeout=START_TIMEOUT_SECONDS, stdin=bootstrap, user=user
                )
            except CapabilityError:
                await self.provider.upload_files(
                    self.handle,
                    (FileUpload(path=BOOTSTRAP_FILE, data=bootstrap, mode=0o644),),
                    root=WORKSPACE,
                )
                result = await self._exec(command, timeout=START_TIMEOUT_SECONDS, user=user)
        finally:
            await self.seal()
        if result.exit_code != 0:
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()[-3000:]
            raise AppHostError(f"App host start failed: {detail}")
        hello = await self.request("hello", timeout=60)
        self.private = str(hello.get("private") or "") if isinstance(hello, dict) else ""
        self.isolated = await self._probe_isolation()

    async def seal(self) -> None:
        """Remove what only the host reads from the workspace the Agent sees.

        That is the Environment, Task, bootstrap, and Verifier code staged for
        the host, and each App's own files (:func:`app_private_files`).

        Raises:
            AppHostError: When any of it is still there.
        """
        result = await self._exec(
            ("python", "-c", _SEAL, WORKSPACE, *_STAGED, *self.private_files),
            timeout=60,
            env={},
        )
        if result.exit_code != 0:
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()[-500:]
            raise AppHostError(f"Could not remove the App host's staged files: {detail}")

    async def _probe_isolation(self) -> bool:
        """Whether the Harness's user is kept out of the host's private folder.

        Returns:
            True only when the host runs as its own user and the Harness's
            user cannot read the folder.
        """
        if not self.isolation.app_user or not self.private:
            return False
        result = await self._exec(
            ("python", "-c", _READABLE, self.private),
            timeout=30,
            user=self.isolation.agent_user,
            env={},
        )
        return result.exit_code == 1

    async def request(self, operation: str, *, timeout: float, **fields: Any) -> Any:
        """Send one signed request through the relay and check the host signed the answer.

        Returns:
            The operation's result.

        Raises:
            AppHostError: When the host is unreachable or reports a failure.
            AppHostTampered: When the answer is not signed with this Trial's token.
        """
        body = signed_request(self.token, operation, **fields)
        raw = canonical(body)
        command: tuple[str, ...] = (*HOST_COMMAND, "control", WORKSPACE)
        env = {**self.env, "PLURAL_APPS_CALL_TIMEOUT": str(timeout)}
        try:
            result = await self._exec(
                command, timeout=timeout + 30, stdin=raw, user=self.isolation.app_user, env=env
            )
        except CapabilityError:
            encoded = base64.b64encode(raw).decode()
            result = await self._exec(
                (*command, encoded), timeout=timeout + 30, user=self.isolation.app_user, env=env
            )
        text = result.stdout.decode(errors="replace").strip()
        if result.exit_code != 0 or not text:
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()[-3000:]
            raise AppHostError(f"App host {operation} failed: {detail}")
        try:
            response = json.loads(text.splitlines()[-1])
        except json.JSONDecodeError as exc:
            raise AppHostError(f"App host {operation} printed no JSON: {text[-500:]}") from exc
        if not isinstance(response, dict):
            raise AppHostError(f"App host {operation} answered {type(response).__name__}")
        if response.get("kind") == "Unreachable" and "mac" not in response:
            raise AppHostError(str(response.get("error") or "App host unreachable"))
        verified = verify_response(self.token, body, response)
        if verified.get("ok") is not True:
            kind = str(verified.get("kind") or "")
            message = str(verified.get("error") or f"App host {operation} failed")
            if kind == "PermissionError":
                raise PermissionError(message)
            raise AppHostError(message)
        return verified.get("result")

    async def finish(self) -> HostReport:
        """Everything the host recorded over the episode.

        Returns:
            The host's signed report.
        """
        return HostReport.parse(await self.request("finish", timeout=FINISH_TIMEOUT_SECONDS))

    async def query(
        self, app: str, action: str, arguments: Mapping[str, Any], *, timeout: float
    ) -> Any:
        """Run one read-only App action for a Verifier.

        Returns:
            The action's observation.
        """
        return await self.request(
            "query", timeout=timeout, app=app, action=action, arguments=dict(arguments)
        )

    async def stop(self) -> None:
        """Stop the host so Apps close their sessions before teardown."""
        try:
            await self.request("stop", timeout=60)
        except (AppHostError, AppHostTampered, PermissionError, OSError):
            return


__all__ = [
    "HOST_COMMAND",
    "WORKSPACE",
    "AppHostError",
    "AppHostSession",
    "AppHostTampered",
    "HostReport",
    "action_command",
    "app_private_files",
    "app_secret_values",
    "describe_missing",
    "environment_payload",
    "host_files",
    "host_inputs",
    "trial_seed",
    "missing_app_secrets",
    "reward_hook_files",
    "verifier_sources",
]
