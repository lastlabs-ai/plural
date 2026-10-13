"""The App host process inside a Runtime, and the client every action command uses.

A Job starts one App host per Trial before the Harness runs::

    python -m plural.apps.daemon start /workspace/environment   # bootstrap JSON on stdin

The bootstrap carries the Apps' secrets, a control token, and the Task's reset
inputs. The host copies the staged Environment into a private folder of its
own, resets every App from the Task's state, and listens on a local socket.
When the Runtime runs the host as its own OS user (see
:meth:`plural.sandbox.SandboxProvider.app_user`), the Harness can reach the
socket but cannot read the host's folder, memory, or environment, nor those of
the App servers it starts.

Each action the Harness runs is a short client call::

    python -m plural.apps.daemon reset            # the opening observation
    python -m plural.apps.daemon step <action>    # arguments as JSON on stdin
    python -m plural.apps.daemon turn             # with seats: may this seat act, and its view

It prints only what the Agent may see: the observation, and the error when the
action rejected its input. Rewards, App State, views, and step info stay in
the host.

When several Agents share the episode, each seat's Harness holds its own seat
token (``PLURAL_SEAT_TOKEN``), and the host acts for the seat that token names.
An action from a seat whose turn it is not is refused before it runs.

Only the Job reads the episode back. Its requests (``hello``, ``query``,
``finish``, ``stop``) carry an HMAC over a fresh nonce under the control
token, and every answer carries an HMAC the Job checks outside the Runtime::

    python -m plural.apps.daemon control          # one signed request on stdin

The token never enters a process the Harness can reach, so a replaced host or
a tampered relay is detected rather than believed.

A client outside a Job that finds no host starts one itself, so the same
commands work on a laptop. Under a Job (``PLURAL_APPS_MANAGED=1``) it never does.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets as token_source
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plural.apps.host import AppHost

ENVIRONMENT_FILE = ".plural/apps/environment.json"
TASK_FILE = ".plural/apps/task.json"
BOOTSTRAP_FILE = ".plural/apps/bootstrap.json"
LOG_FILE = ".plural/apps/host.log"
IDLE_SECONDS = float(os.environ.get("PLURAL_APPS_IDLE_SECONDS") or 3600)
START_SECONDS = float(os.environ.get("PLURAL_APPS_START_SECONDS") or 120)
RECEIVE_SECONDS = 30.0
MANAGED = "PLURAL_APPS_MANAGED"
"""Set in the Harness's environment by a Job: never start a host, one is running."""
SEAT_TOKEN = "PLURAL_SEAT_TOKEN"
"""Set in one seat's Harness environment: the token that says which seat it acts for."""
SOCKET_NAME = "host.sock"
_MAX_MESSAGE = 64 * 1024 * 1024
_BOOTSTRAP_STDIN = "PLURAL_APPS_BOOTSTRAP_STDIN"
_CONTROLLED = frozenset({"hello", "query", "finish", "stop"})
_PR_SET_DUMPABLE = 4


class AppHostTampered(RuntimeError):
    """An answer to the Job was not signed by the App host the Job started."""


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


def sandbox_path(path: str | Path) -> Path:
    """Map a Runtime path such as ``/workspace/environment`` onto this machine.

    The local Runtime runs in a folder named by ``PLURAL_SANDBOX_ROOT``; every
    other Runtime uses the path as it is.

    Returns:
        The resolved path.
    """
    text = str(path)
    root = os.environ.get("PLURAL_SANDBOX_ROOT")
    if root and text.startswith("/") and not text.startswith(root):
        return (Path(root) / text.removeprefix("/")).resolve()
    return Path(text).resolve()


def workspace() -> Path:
    """The Environment workspace: ``PLURAL_APPS_WORKSPACE`` or the current folder.

    Returns:
        The resolved workspace folder.
    """
    return Path(os.environ.get("PLURAL_APPS_WORKSPACE") or os.getcwd()).resolve()


def socket_dir(root: Path) -> Path:
    """The folder holding one workspace's socket, within the Unix path length limit.

    Returns:
        The folder for ``root``.
    """
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    # Not TMPDIR: the host and the Harness's action processes can see different values.
    folder = "/tmp" if os.name == "posix" and os.path.isdir("/tmp") else tempfile.gettempdir()
    return Path(folder) / f"plural-apps-{digest}"


def socket_path(root: Path) -> str:
    """The App host's socket for one workspace.

    Returns:
        The socket path for ``root``.
    """
    return str(socket_dir(root) / SOCKET_NAME)


# Signing. The token is shared by the Job and the host only.


def canonical(value: Any) -> bytes:
    """The bytes both sides sign: sorted, compact JSON.

    Returns:
        The encoded value.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _mac(token: str, nonce: str, payload: Any) -> str:
    return hmac.new(
        token.encode(), nonce.encode() + b"\n" + canonical(payload), hashlib.sha256
    ).hexdigest()


def signed_request(token: str, operation: str, **fields: Any) -> dict[str, Any]:
    """A Job request the host will act on: the operation, a fresh nonce, and its HMAC.

    Returns:
        The request to send.
    """
    body = json.loads(canonical({"op": operation, **fields}))
    nonce = token_source.token_urlsafe(18)
    return {**body, "nonce": nonce, "auth": _mac(token, nonce, body)}


def verify_response(token: str, request: Mapping[str, Any], response: Mapping[str, Any]) -> Any:
    """Check that the host the Job started signed this answer to this request.

    Returns:
        The response without its signature.

    Raises:
        AppHostTampered: When the signature is missing or wrong.
    """
    payload = {key: value for key, value in response.items() if key != "mac"}
    mac = response.get("mac")
    expected = _mac(token, str(request.get("nonce") or ""), payload)
    if not isinstance(mac, str) or not hmac.compare_digest(mac, expected):
        raise AppHostTampered(
            "The App host's answer was not signed with this Trial's control token. Something "
            "in the Runtime replaced the App host or altered its answer, so the episode's "
            "State and rewards cannot be trusted."
        )
    return payload


# Wire format: one JSON object per line in each direction.


def _send(connection: socket.socket, payload: Mapping[str, Any]) -> None:
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


def _load_host(
    root: Path,
    *,
    private_state: bool,
    inputs: Mapping[str, Any] | None,
    seats: Sequence[str] = (),
) -> AppHost:
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
    info = _task_inputs(root, inputs)["info"]
    return AppHost(
        environment,
        workspace=root,
        verifiers=load_reward_hooks(root, task.get("verifiers") or []),
        task=StepTask(
            name=str(about.get("name") or ""),
            info=info,
            metadata=dict(about.get("metadata") or {}),
        ),
        private_state=private_state,
        seats=seats,
    )


def _task_file(root: Path) -> dict[str, Any]:
    path = root / TASK_FILE
    task = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(task, dict):
        raise ValueError(f"{path} must hold an object")
    return task


def _task_inputs(root: Path, provided: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The Task's initial state, info, and seed.

    A Job sends these in the bootstrap, so the hidden initial State never lands
    in a file. A local client that starts the host itself falls back to
    ``task.json``.

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
    """Whether a request comes from the Job: a valid HMAC over a nonce never seen before.

    With seats, it also tells which seat a Harness acts for, by the seat token
    only that seat's Harness was given.
    """

    def __init__(self, token: str | None, seats: Mapping[str, str] | None = None) -> None:
        self.token = token
        self.seats = dict(seats or {})
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def seat(self, request: Mapping[str, Any]) -> str | None:
        """The seat whose token the request carries.

        Returns:
            The seat, or ``None`` for no token or one no seat holds.
        """
        given = request.get("seat_token")
        if not isinstance(given, str) or not given:
            return None
        found = None
        for seat, token in self.seats.items():
            if hmac.compare_digest(given.encode(), token.encode()):
                found = seat
        return found

    def authorized(self, request: Mapping[str, Any]) -> bool:
        if not self.token:
            return True
        nonce, auth = request.get("nonce"), request.get("auth")
        if not isinstance(nonce, str) or not isinstance(auth, str) or not nonce:
            return False
        body = {key: value for key, value in request.items() if key not in {"nonce", "auth"}}
        if not hmac.compare_digest(auth, _mac(self.token, nonce, body)):
            return False
        with self._lock:
            if nonce in self._seen:
                return False
            self._seen.add(nonce)
        return True

    def sign(self, request: Mapping[str, Any], response: dict[str, Any]) -> dict[str, Any]:
        if not self.token or request.get("op") not in _CONTROLLED:
            return response
        # Sign exactly what the Job will parse back.
        payload = json.loads(canonical(response))
        return {**payload, "mac": _mac(self.token, str(request.get("nonce") or ""), payload)}


def _handle(
    host: AppHost, private: Path, request: dict[str, Any], control: _Control
) -> tuple[dict[str, Any], bool]:
    operation = request.get("op")
    if operation == "ping":
        return {"ok": True, "result": "pong"}, False
    if operation in _CONTROLLED and not control.authorized(request):
        return {
            "ok": False,
            "error": f"Only the Job may {operation} the Apps.",
            "kind": "PermissionError",
        }, False
    if operation in {"reset", "step", "turn"} and host.finished:
        from plural.apps.host import EPISODE_OVER

        # The Job has read the episode back; a Harness process still running may not act.
        return {"ok": False, "error": EPISODE_OVER, "kind": "EpisodeOver"}, False
    if operation == "reset":
        if not host.started:
            host.start(**_task_inputs(private))
        return {"ok": True, "result": host.agent_reset()}, False
    if operation == "step":
        if not host.started:
            host.start(**_task_inputs(private))
        arguments = request.get("arguments")
        if not isinstance(arguments, dict):
            return {"ok": True, "result": host.agent_argument_error(request.get("action"))}, False
        seat = control.seat(request) if host.seats else None
        envelope = host.step(str(request.get("action")), arguments, seat=seat)
        return {"ok": True, "result": host.agent_view(envelope)}, False
    if operation == "turn":
        if not host.seats:
            return {"ok": True, "result": {"seat": None, "your_turn": True}}, False
        seat = control.seat(request)
        if seat is None:
            return {
                "ok": False,
                "error": "This Harness holds no seat's token.",
                "kind": "PermissionError",
            }, False
        return {"ok": True, "result": host.seat_view(seat)}, False
    if operation == "hello":
        return {
            "ok": True,
            "result": {
                "pid": os.getpid(),
                "uid": os.getuid() if hasattr(os, "getuid") else None,
                "private": str(private),
            },
        }, False
    if operation == "query":
        result = host.query(
            str(request.get("app")), str(request.get("action")), request.get("arguments") or {}
        )
        return {"ok": True, "result": result}, False
    if operation == "finish":
        # Outside a Job, a laptop's host keeps serving after a look at its report.
        return {"ok": True, "result": host.finish() if control.token else host.report()}, False
    if operation == "stop":
        return {"ok": True, "result": "stopped"}, True
    return {"ok": False, "error": f"unknown App host operation {operation!r}"}, False


def _failure(request: Mapping[str, Any], exc: BaseException) -> dict[str, Any]:
    if request.get("op") in _CONTROLLED:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "kind": type(exc).__name__}
    # The Harness, and so the model, may read this; the details are in the host's log.
    return {"ok": False, "error": "The App host failed on this request.", "kind": "HostError"}


def _bind(root: Path) -> socket.socket:
    """Listen on this workspace's socket, refusing a folder another user holds.

    The folder is ``0711`` and the socket ``0666``: another user, such as the
    Harness's, can connect but cannot list, remove, or replace either.

    Returns:
        The listening socket.

    Raises:
        RuntimeError: When another user holds the folder or a host already answers.
    """
    directory = socket_dir(root)
    try:
        directory.mkdir(mode=0o711)
    except FileExistsError:
        info = os.lstat(directory)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or (hasattr(os, "getuid") and info.st_uid != os.getuid())
        ):
            raise RuntimeError(f"{directory} is held by another user; not starting") from None
        if running(root):
            raise RuntimeError("An App host already answers for this workspace") from None
    os.chmod(directory, 0o711)
    path = directory / SOCKET_NAME
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    os.chmod(path, 0o666)
    server.listen(64)
    server.settimeout(1.0)
    return server


def _read_bootstrap() -> dict[str, Any]:
    if os.environ.pop(_BOOTSTRAP_STDIN, None) != "1":
        return {}
    received = json.loads(sys.stdin.read() or "{}")
    return received if isinstance(received, dict) else {}


def _ensure_home(private: Path) -> None:
    home = os.environ.get("HOME")
    if home and os.path.isdir(home) and os.access(home, os.W_OK):
        return
    folder = private / ".home"
    folder.mkdir(mode=0o700, exist_ok=True)
    os.environ["HOME"] = str(folder)


def serve(root: Path, private: Path | None = None) -> None:
    """Run the App host for one workspace until stopped or idle."""
    not_dumpable()
    private = private or root
    # The workspace is not on the import path: a Harness could write modules there.
    unsafe = {"", str(root)} | ({os.getcwd()} if Path.cwd().resolve() != private else set())
    sys.path[:] = [item for item in sys.path if item not in unsafe]
    boot = _read_bootstrap()
    token = str(boot.get("token") or "") or None
    given = boot.get("inputs")
    inputs = given if isinstance(given, dict) and given else None
    values = {str(key): str(value) for key, value in dict(boot.get("secrets") or {}).items()}
    from plural.apps.mcp import protect_values

    protect_values(values)
    os.environ.update(values)
    _ensure_home(private)
    seat_tokens = boot.get("seats")
    seats = (
        {str(seat): str(value) for seat, value in seat_tokens.items()}
        if isinstance(seat_tokens, dict)
        else {}
    )
    control = _Control(token, seats)
    host = _load_host(private, private_state=bool(token), inputs=inputs, seats=tuple(seats))
    host.redact_values(values.values())
    if token:
        # The Job's own reset, from the Task's state, before the Harness can act.
        host.start(**_task_inputs(private, inputs))
    server = _bind(root)
    lock = threading.RLock()
    stopping = threading.Event()
    activity = [time.monotonic()]

    def answer(connection: socket.socket) -> None:
        with connection:
            try:
                connection.settimeout(RECEIVE_SECONDS)
                request = _receive(connection)
            except (OSError, ValueError, ConnectionError):
                return
            connection.settimeout(None)
            activity[0] = time.monotonic()
            stop = False
            if request.get("op") == "ping":
                response: dict[str, Any] = {"ok": True, "result": "pong"}
            else:
                with lock:
                    if stopping.is_set():
                        response = {"ok": False, "error": "The App host is stopping."}
                    else:
                        try:
                            response, stop = _handle(host, private, request, control)
                        except Exception as exc:  # noqa: BLE001 - every failure answers the caller
                            traceback.print_exc()
                            response = _failure(request, exc)
                        if stop:
                            stopping.set()
                            host.close()
            with contextlib.suppress(OSError):
                _send(connection, control.sign(request, response))
            activity[0] = time.monotonic()

    try:
        while (
            not stopping.is_set()
            and time.monotonic() - activity[0] < IDLE_SECONDS
            # Under a Job the Harness can delete or move any shared path, so only the
            # signed stop or the idle timer ends the host.
            and (token is not None or root.exists())
        ):
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            threading.Thread(target=answer, args=(connection,), daemon=True).start()
    finally:
        with lock:
            if not stopping.is_set():
                stopping.set()
                host.close()
        server.close()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(socket_path(root))
        if private != root:
            shutil.rmtree(private, ignore_errors=True)


# The client.


def _request(root: Path, payload: Mapping[str, Any], *, timeout: float | None) -> dict[str, Any]:
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


def _private_root(public: Path) -> Path:
    """Copy the staged Environment into a new folder only this user can read.

    Returns:
        The private folder.
    """
    try:
        folder = tempfile.mkdtemp(prefix=".plural-apps-", dir=str(public.parent))
    except OSError:
        # The App user may not write beside the workspace; its own temp folder will do.
        folder = tempfile.mkdtemp(prefix="plural-apps-private-", dir=str(socket_dir(public).parent))
    private = Path(folder).resolve()
    shutil.copytree(public, private, dirs_exist_ok=True, symlinks=True)
    # copytree copies the public folder's mode onto this one.
    os.chmod(private, 0o700)
    with contextlib.suppress(FileNotFoundError):
        (private / BOOTSTRAP_FILE).unlink()
    return private


def start(
    root: Path,
    secrets: dict[str, str] | None = None,
    token: str | None = None,
    inputs: Mapping[str, Any] | None = None,
    seats: Mapping[str, str] | None = None,
) -> None:
    """Start the App host for ``root`` in the background and wait until it answers.

    With a control ``token`` the host runs from a private copy of ``root``.
    ``seats`` maps each seat of a Task several Agents share to the token its
    Harness alone holds. ``secrets``, the tokens, and the Task's ``inputs`` reach it through a pipe
    rather than its environment or a file, so they do not appear in its
    process listing or the shared workspace.

    Raises:
        RuntimeError: When the host exits or does not answer in time.
    """
    if running(root):
        if token:
            raise RuntimeError("An App host already answers for this workspace")
        return
    private = _private_root(root) if token else root
    log = private / LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "plural.apps.daemon", "serve", str(root), str(private)]
    bootstrap = secrets or token or seats or inputs is not None
    env = {**os.environ, _BOOTSTRAP_STDIN: "1"} if bootstrap else None
    if env is not None:
        env.pop(MANAGED, None)
        env.pop(SEAT_TOKEN, None)
    with log.open("ab") as stream:
        process = subprocess.Popen(  # noqa: S603 - the interpreter running Plural
            command,
            cwd=str(private),
            env=env,
            stdin=subprocess.PIPE if bootstrap else subprocess.DEVNULL,
            stdout=stream,
            stderr=stream,
            start_new_session=True,
        )
    if bootstrap and process.stdin is not None:
        process.stdin.write(
            json.dumps(
                {
                    "secrets": secrets or {},
                    "token": token,
                    "inputs": dict(inputs or {}),
                    "seats": dict(seats or {}),
                },
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
    if private != root:
        shutil.rmtree(private, ignore_errors=True)
    raise RuntimeError(f"The App host did not start.\n{detail}".rstrip())


def call(
    operation: str,
    *,
    root: Path | None = None,
    timeout: float | None = None,
    token: str | None = None,
    **fields: Any,
) -> Any:
    """Send one operation to the App host, starting it first when allowed.

    Outside a Job, a client that finds no host starts one. Under a Job
    (``PLURAL_APPS_MANAGED=1``) the Job started it, so a missing host is an error.
    With the control ``token`` the request is signed and the answer checked.

    Returns:
        The operation's result.

    Raises:
        RuntimeError: When the host is missing or reports a failure.
    """
    base = root or workspace()
    if not running(base):
        if operation in {"stop", "finish"}:
            return None
        if os.environ.get(MANAGED) == "1":
            raise RuntimeError("The Environment's App host is not running.")
        start(base)
    seat_token = os.environ.get(SEAT_TOKEN)
    if seat_token and operation in {"step", "turn"}:
        fields = {**fields, "seat_token": seat_token}
    request = signed_request(token, operation, **fields) if token else {"op": operation, **fields}
    try:
        response = _request(base, request, timeout=timeout)
    except (ConnectionRefusedError, FileNotFoundError):
        if operation in {"stop", "finish"}:
            # It stopped between the ping and this request.
            return None
        raise
    if token and operation in _CONTROLLED:
        response = verify_response(token, request, response)
    if response.get("ok") is not True:
        kind = str(response.get("kind") or "")
        message = str(response.get("error") or "App host failed")
        if kind == "PermissionError":
            raise PermissionError(message)
        if kind == "KeyError":
            raise KeyError(message)
        raise RuntimeError(message)
    return response.get("result")


def _relay(root: Path, raw: str) -> None:
    """Send one signed Job request and print the host's answer exactly as it came."""
    request = json.loads(raw)
    if not isinstance(request, dict):
        raise SystemExit("control reads one signed request object")
    timeout = float(os.environ.get("PLURAL_APPS_CALL_TIMEOUT") or 0) or None
    try:
        response = _request(root, request, timeout=timeout)
    except (OSError, ValueError, ConnectionError) as exc:
        response = {"ok": False, "error": f"App host unreachable: {exc}", "kind": "Unreachable"}
    print(json.dumps(response, default=str))


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point used by Jobs and Harnesses."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit(__doc__)
    operation, rest = args[0], args[1:]
    if operation == "serve":
        serve(
            Path(rest[0]).resolve() if rest else workspace(),
            Path(rest[1]).resolve() if len(rest) > 1 else None,
        )
        return
    if operation == "start":
        not_dumpable()
        root = sandbox_path(rest[0]) if rest else workspace()
        source = root / BOOTSTRAP_FILE
        if source.is_file():
            raw = source.read_text(encoding="utf-8")
        else:
            raw = "" if sys.stdin.isatty() else sys.stdin.read().strip()
        received = json.loads(raw) if raw else {}
        if not isinstance(received, dict) or not isinstance(received.get("secrets", {}), dict):
            raise SystemExit(
                'start reads {"secrets": {...}, "token": "...", "inputs": {...}} on stdin'
            )
        secrets = {str(key): str(value) for key, value in received.get("secrets", {}).items()}
        given = received.get("inputs")
        seated = received.get("seats")
        start(
            root,
            secrets or None,
            str(received.get("token") or "") or None,
            given if isinstance(given, dict) else None,
            {str(key): str(value) for key, value in seated.items()}
            if isinstance(seated, dict)
            else None,
        )
        print(json.dumps({"ok": True}))
        return
    if operation == "control":
        root = sandbox_path(rest[0]) if rest else workspace()
        encoded = rest[1] if len(rest) > 1 else ""
        raw = base64.b64decode(encoded).decode() if encoded else sys.stdin.read()
        _relay(root, raw)
        return
    root = workspace()
    timeout = float(os.environ.get("PLURAL_APPS_CALL_TIMEOUT") or 0) or None
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
        raw = sys.stdin.read().strip()
        result = call(
            "query",
            root=root,
            timeout=timeout,
            app=rest[0],
            action=rest[1],
            arguments=json.loads(raw) if raw else {},
        )
    elif operation == "turn":
        result = call("turn", root=root, timeout=timeout)
    elif operation in {"reset", "finish", "stop"}:
        result = call(operation, root=root, timeout=timeout)
    else:
        raise SystemExit(f"unknown operation {operation!r}")
    print(json.dumps(result, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
