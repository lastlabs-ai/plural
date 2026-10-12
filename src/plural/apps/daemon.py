"""The App host process inside a Runtime, and the client every action command uses.

A Job starts one App host per Trial, in the Environment workspace, before the
Harness runs, with the Apps' secret values and a control token as JSON on stdin::

    python -m plural.apps.daemon start

The host keeps every App alive for the episode, so an MCP server started as a
command keeps its session and a Python App keeps its state in memory. It holds
the Apps' secrets; the Harness never receives them. Each action the Harness
runs is a short client call over a local socket::

    python -m plural.apps.daemon reset
    python -m plural.apps.daemon step <action>        # arguments as JSON on stdin
    python -m plural.apps.daemon query <app> <action> # read-only, for Verifiers
    python -m plural.apps.daemon finish               # snapshots for Verifiers
    python -m plural.apps.daemon stop

A host started with a control token answers ``query``, ``finish``, ``stop``,
``states``, and any ``reset`` after the first only to callers that present it,
so the Harness can start the episode and act, but cannot read State, end the
episode, or start it over. The Job sends the token on stdin with
``PLURAL_APPS_CONTROL_STDIN=1``. In that mode the host keeps full App State,
which may hold a secret, in memory rather than in the shared workspace, and the
Job reads it back with ``states`` and ``finish``.

A client that finds no host running starts one with its own environment, so
the same commands work on a laptop without a Job.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plural.apps.host import AppHost

ENVIRONMENT_FILE = ".plural/apps/environment.json"
TASK_FILE = ".plural/apps/task.json"
LOG_FILE = ".plural/apps/host.log"
IDLE_SECONDS = float(os.environ.get("PLURAL_APPS_IDLE_SECONDS") or 3600)
START_SECONDS = float(os.environ.get("PLURAL_APPS_START_SECONDS") or 120)
_MAX_MESSAGE = 64 * 1024 * 1024
_SECRETS_ON_STDIN = "PLURAL_APPS_SECRETS_ON_STDIN"
_CONTROL_STDIN = "PLURAL_APPS_CONTROL_STDIN"
_CONTROLLED = frozenset({"query", "finish", "stop", "states"})
_PR_SET_DUMPABLE = 4


def not_dumpable() -> None:
    """Keep this process's memory, environment, and open files from its own user.

    On Linux a process that is not dumpable cannot be read through ``/proc`` or
    traced by another process of the same user without ``CAP_SYS_PTRACE``. The
    setting lasts until the process runs another program.
    """
    if not sys.platform.startswith("linux"):
        return
    import ctypes

    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0)


def workspace() -> Path:
    """The Environment workspace: ``PLURAL_APPS_WORKSPACE`` or the current folder.

    Returns:
        The resolved workspace folder.
    """
    return Path(os.environ.get("PLURAL_APPS_WORKSPACE") or os.getcwd()).resolve()


def socket_path(root: Path) -> str:
    """A short socket path for one workspace, within the Unix path length limit.

    Returns:
        The socket path for ``root``.
    """
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    # Not TMPDIR: the host and the Harness's action processes can see different values.
    folder = "/tmp" if os.name == "posix" and os.path.isdir("/tmp") else tempfile.gettempdir()
    return str(Path(folder) / f"plural-apps-{digest}.sock")


# Wire format: one JSON object per line in each direction.


def _send(connection: socket.socket, payload: dict[str, Any]) -> None:
    connection.sendall(json.dumps(payload, default=str).encode() + b"\n")


def _receive(connection: socket.socket) -> dict[str, Any]:
    buffer = bytearray()
    while not buffer.endswith(b"\n"):
        chunk = connection.recv(65536)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > _MAX_MESSAGE:
            raise ValueError("App host message is too large")
    if not buffer:
        raise ConnectionError("App host closed the connection")
    parsed = json.loads(buffer)
    if not isinstance(parsed, dict):
        raise ValueError("App host message must be an object")
    return parsed


# The host.


def _load_host(root: Path, private_state: bool = False) -> Any:
    from plural.apps.host import AppHost, load_reward_hooks
    from plural.apps.mcp import hide_from_hooks
    from plural.environments.definition import EnvironmentDefinition
    from plural.environments.env import Environment
    from plural.verifiers import StepTask

    path = root / ENVIRONMENT_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing; the Job writes it before starting the host")
    definition = EnvironmentDefinition.model_validate_json(path.read_text(encoding="utf-8"))
    hide_from_hooks(item.name for item in definition.credentials)
    environment = Environment._from_definition(definition, root=root)
    task = _task_file(root)
    about: dict[str, Any] = task["task"] if isinstance(task.get("task"), dict) else {}
    return AppHost(
        environment,
        workspace=root,
        verifiers=load_reward_hooks(root, task.get("verifiers") or []),
        task=StepTask(
            name=str(about.get("name") or ""),
            info=task.get("info"),
            metadata=dict(about.get("metadata") or {}),
        ),
        private_state=private_state,
    )


def _task_file(root: Path) -> dict[str, Any]:
    path = root / TASK_FILE
    task = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(task, dict):
        raise ValueError(f"{path} must hold an object")
    return task


def _task_inputs(root: Path, provided: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The Task's initial state, info, and seed.

    A Job sends these to the host on stdin, so the hidden initial State never
    lands in the shared workspace. A local client that starts the host itself
    falls back to ``task.json``.

    Returns:
        Keyword arguments for :meth:`AppHost.reset`.
    """
    task = dict(provided) if provided is not None else _task_file(root)
    state = task.get("initial_state")
    seed = task.get("seed")
    return {
        "initial_state": state if isinstance(state, dict) else {},
        "info": task.get("info"),
        "seed": seed if isinstance(seed, int) else None,
    }


class _Control:
    """Which callers may do what: the control token, and whether the episode started."""

    def __init__(self, token: str | None, inputs: Mapping[str, Any] | None = None) -> None:
        self.token = token
        self.inputs = inputs
        self.started = False

    def allows(self, request: dict[str, Any]) -> bool:
        if not self.token:
            return True
        presented = request.get("token")
        return isinstance(presented, str) and hmac.compare_digest(presented, self.token)


def _handle(
    host: Any, root: Path, request: dict[str, Any], control: _Control | None = None
) -> tuple[dict[str, Any], bool]:
    control = control or _Control(None)
    operation = request.get("op")
    if operation == "ping":
        return {"ok": True, "result": "pong"}, False
    if operation in _CONTROLLED and not control.allows(request):
        return {
            "ok": False,
            "error": f"Only the Job may {operation} the Apps.",
            "kind": "PermissionError",
        }, False
    if operation == "reset":
        if control.started and not control.allows(request):
            return {"ok": True, "result": _already_started(host)}, False
        control.started = True
        return {"ok": True, "result": host.reset(**_task_inputs(root, control.inputs))}, False
    if operation == "step":
        arguments = request.get("arguments")
        if not isinstance(arguments, dict):
            return {"ok": True, "result": _argument_error(host, request)}, False
        return {"ok": True, "result": host.step(str(request.get("action")), arguments)}, False
    if operation == "query":
        result = host.query(
            str(request.get("app")), str(request.get("action")), request.get("arguments") or {}
        )
        return {"ok": True, "result": result}, False
    if operation == "finish":
        return {"ok": True, "result": host.snapshot()}, False
    if operation == "states":
        return {"ok": True, "result": host.recorded_states()}, False
    if operation == "stop":
        return {"ok": True, "result": "stopped"}, True
    return {"ok": False, "error": f"unknown App host operation {operation!r}"}, False


def _already_started(host: AppHost) -> dict[str, Any]:
    return host._envelope(
        "reset",
        observation=None,
        rendered="",
        info={"error": "The episode has already started; it cannot be reset."},
    )


def _argument_error(host: AppHost, request: dict[str, Any]) -> dict[str, Any]:
    return host._envelope(
        "step",
        action=str(request.get("action")),
        observation=None,
        rendered="",
        info={"error": "action arguments must be a JSON object"},
    )


def serve(root: Path) -> None:
    """Run the App host for one workspace until stopped or idle."""
    not_dumpable()
    token: str | None = None
    inputs: Mapping[str, Any] | None = None
    if os.environ.pop(_SECRETS_ON_STDIN, None) == "1":
        received = json.loads(sys.stdin.read() or "{}")
        if isinstance(received, dict):
            secrets = received.get("secrets")
            token = str(received.get("token") or "") or None
            given = received.get("inputs")
            inputs = given if isinstance(given, dict) and given else None
            os.environ.update({str(key): str(value) for key, value in dict(secrets or {}).items()})
    control = _Control(token, inputs)
    host = _load_host(root, private_state=bool(token))
    path = socket_path(root)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    os.chmod(path, 0o600)
    server.listen(8)
    server.settimeout(1.0)
    last = time.monotonic()
    closed = False
    try:
        while time.monotonic() - last < IDLE_SECONDS and root.exists():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            last = time.monotonic()
            with connection:
                connection.settimeout(None)
                stop = False
                try:
                    response, stop = _handle(host, root, _receive(connection), control)
                except Exception as exc:  # noqa: BLE001 - every failure goes back to the caller
                    # The traceback goes to the host's log, not to the caller.
                    traceback.print_exc()
                    response = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "kind": type(exc).__name__,
                    }
                if stop:
                    # The caller destroys the Runtime once it has the reply.
                    host.close()
                    closed = True
                with contextlib.suppress(OSError):
                    _send(connection, response)
                if stop:
                    break
    finally:
        if not closed:
            host.close()
        server.close()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)


# The client.


def _request(root: Path, payload: dict[str, Any], *, timeout: float | None) -> dict[str, Any]:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(socket_path(root))
        _send(connection, payload)
        return _receive(connection)
    finally:
        connection.close()


def running(root: Path) -> bool:
    """Whether an App host answers for this workspace.

    Returns:
        True when a host replied to a ping.
    """
    try:
        return _request(root, {"op": "ping"}, timeout=5).get("ok") is True
    except (OSError, ValueError, ConnectionError):
        return False


def start(
    root: Path,
    secrets: dict[str, str] | None = None,
    token: str | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> None:
    """Start the App host for ``root`` in the background and wait until it answers.

    ``secrets``, the control ``token``, and the Task's ``inputs`` reach the host
    through a pipe rather than its environment or a file, so they do not appear
    in the host's process listing or the shared workspace.

    Raises:
        RuntimeError: When the host exits or does not answer in time.
    """
    if running(root):
        return
    log = root / LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "plural.apps.daemon", "serve", str(root)]
    private = secrets or token or inputs is not None
    env = {**os.environ, _SECRETS_ON_STDIN: "1"} if private else None
    with log.open("ab") as stream:
        process = subprocess.Popen(  # noqa: S603 - the interpreter running Plural
            command,
            cwd=str(root),
            env=env,
            stdin=subprocess.PIPE if private else subprocess.DEVNULL,
            stdout=stream,
            stderr=stream,
            start_new_session=True,
        )
    if private and process.stdin is not None:
        process.stdin.write(
            json.dumps(
                {"secrets": secrets or {}, "token": token, "inputs": dict(inputs or {})},
                default=str,
            ).encode()
        )
        process.stdin.close()
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        if running(root):
            return
        if process.poll() is not None:
            break
        time.sleep(0.05)
    detail = log.read_text(encoding="utf-8", errors="replace")[-3000:] if log.exists() else ""
    if process.poll() is None:
        process.kill()
    raise RuntimeError(f"The App host did not start.\n{detail}".rstrip())


def call(
    operation: str,
    *,
    root: Path | None = None,
    timeout: float | None = None,
    token: str | None = None,
    **fields: Any,
) -> Any:
    """Send one operation to the App host, starting it first when needed.

    ``token`` is the control token the Job started the host with, for the
    operations only the Job may run.

    Returns:
        The operation's result.

    Raises:
        RuntimeError: When the host reports a failure.
    """
    base = root or workspace()
    if not running(base):
        if operation in {"stop", "finish"}:
            return None
        start(base)
    request = {"op": operation, **fields}
    if token:
        request["token"] = token
    response = _request(base, request, timeout=timeout)
    if response.get("ok") is not True:
        kind = str(response.get("kind") or "")
        message = str(response.get("error") or "App host failed")
        if kind == "PermissionError":
            raise PermissionError(message)
        if kind == "KeyError":
            raise KeyError(message)
        raise RuntimeError(message)
    return response.get("result")


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point used by Jobs and Harnesses."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit(__doc__)
    operation, rest = args[0], args[1:]
    root = workspace()
    if operation == "serve":
        serve(Path(rest[0]).resolve() if rest else root)
        return
    if operation == "start":
        not_dumpable()
        raw = "" if sys.stdin.isatty() else sys.stdin.read().strip()
        received = json.loads(raw) if raw else {}
        if not isinstance(received, dict) or not isinstance(received.get("secrets", {}), dict):
            raise SystemExit(
                'start reads {"secrets": {...}, "token": "...", "inputs": {...}} on stdin'
            )
        secrets = {str(key): str(value) for key, value in received.get("secrets", {}).items()}
        given = received.get("inputs")
        start(
            root,
            secrets or None,
            str(received.get("token") or "") or None,
            given if isinstance(given, dict) else None,
        )
        print(json.dumps({"ok": True}))
        return
    timeout = float(os.environ.get("PLURAL_APPS_CALL_TIMEOUT") or 0) or None
    token: str | None = None
    controlled_input: Any = None
    if os.environ.get(_CONTROL_STDIN) == "1":
        not_dumpable()
        envelope = json.loads(sys.stdin.read() or "{}")
        token = str(envelope.get("token") or "") or None
        controlled_input = envelope.get("arguments")
    if operation == "step":
        if len(rest) != 1:
            raise SystemExit("usage: python -m plural.apps.daemon step <action>")
        raw = sys.stdin.read().strip()
        try:
            arguments = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            arguments = None
        result = call("step", root=root, timeout=timeout, action=rest[0], arguments=arguments)
    elif operation == "query":
        if len(rest) != 2:
            raise SystemExit("usage: python -m plural.apps.daemon query <app> <action>")
        if token is not None:
            arguments = controlled_input or {}
        else:
            raw = sys.stdin.read().strip()
            arguments = json.loads(raw) if raw else {}
        result = call(
            "query",
            root=root,
            timeout=timeout,
            token=token,
            app=rest[0],
            action=rest[1],
            arguments=arguments,
        )
    elif operation in {"reset", "finish", "stop", "states"}:
        result = call(operation, root=root, timeout=timeout, token=token)
    else:
        raise SystemExit(f"unknown operation {operation!r}")
    print(json.dumps(result, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
