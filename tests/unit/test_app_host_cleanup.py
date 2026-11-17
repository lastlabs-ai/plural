"""An interrupted run leaves no App host behind: on cancel, on Ctrl-C, and on a crash."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="process groups and signals")

# A Job on the local Runtime whose Agent waits on a model server that never answers,
# so the App host is up and the Trial is mid-episode when the run is interrupted.
_RUN = textwrap.dedent(
    """
    import asyncio
    import json
    import sys
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from counter_app import Counter
    from plural import (
        Agent, DeterministicVerifier, Environment, Episode, Job, Runtime, Task, VerifierOutput,
    )
    from plural.execution.engine import JobRunner

    CALLED = threading.Event()


    class Silent(BaseHTTPRequestHandler):
        def _send(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self._send(200 if self.path == "/v1/models" else 404, {"data": [{"id": "m"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "max_tokens" in body:
                message = {"role": "assistant", "content": "ok"}
                self._send(200, {"model": "m", "choices": [{"message": message}]})
                return
            CALLED.set()
            print("MODEL-CALLED", flush=True)
            time.sleep(600)

        def log_message(self, *args):
            return


    def check(episode: Episode) -> VerifierOutput:
        return VerifierOutput(score=1.0)


    server = ThreadingHTTPServer(("127.0.0.1", 0), Silent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    task = Task(
        name="count",
        instructions="Bump the counter.",
        environment=Environment(name="counter", apps=[Counter()], runtime=Runtime.local()),
        verifiers=[DeterministicVerifier(name="ok", check=check)],
    )
    agent = Agent(model="m", endpoint=f"http://127.0.0.1:{server.server_port}/v1")
    job = Job(task, agents=[agent], allow_local_models=True)


    async def cancel_mid_episode():
        runner = JobRunner(job.spec, environ=job._credential_environ())
        running = asyncio.ensure_future(runner.run())
        while not CALLED.is_set() and not running.done():
            await asyncio.sleep(0.1)
        await runner.cancel()
        print("STATUS", (await running).status, flush=True)


    if sys.argv[1] == "cancel":
        asyncio.run(cancel_mid_episode())
    else:
        job.run()
    """
)


_APP = textwrap.dedent(
    '''
    from plural import App, action


    class Counter(App):
        @action
        def bump(self) -> int:
            """Add one."""
            return 1
    '''
)


def _hosts(root: Path) -> list[int]:
    """The App host processes serving a workspace under ``root``.

    ``ww`` keeps ``ps`` from cutting a long command line to the terminal's width.
    """
    listing = subprocess.run(
        ["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, check=True
    ).stdout
    return [
        int(line.split(None, 1)[0])
        for line in listing.splitlines()
        if "plural.apps.daemon serve" in line and str(root) in line
    ]


def _start(tmp_path: Path, mode: str) -> subprocess.Popen[str]:
    project = tmp_path / "project"
    project.mkdir()
    script = project / "run_job.py"
    script.write_text(_RUN, encoding="utf-8")
    (project / "counter_app.py").write_text(_APP, encoding="utf-8")
    sandboxes = tmp_path / "sandboxes"
    sandboxes.mkdir()
    env = {
        **os.environ,
        "TMPDIR": str(sandboxes),
        "PLURAL_CONFIG_HOME": str(tmp_path / "config"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(project),
    }
    env.pop("PLURAL_API_KEY", None)
    process = subprocess.Popen(
        [sys.executable, str(script), mode],
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
        # A shell's background jobs inherit SIGINT ignored, and Python then never raises
        # KeyboardInterrupt; a terminal's Ctrl-C reaches a run with the default handler.
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
    )
    assert process.stdout is not None
    output = []
    for line in process.stdout:
        output.append(line)
        if "MODEL-CALLED" in line:
            break
    assert _hosts(sandboxes), (
        "the App host never started:\n" + "".join(output) + _evidence(sandboxes)
    )
    return process


def _evidence(sandboxes: Path) -> str:
    """Every App host process, and each host's log, for a failure message."""
    listing = subprocess.run(
        ["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, check=True
    ).stdout
    lines = [line for line in listing.splitlines() if "plural.apps.daemon" in line]
    logs = [
        f"{path}:\n{path.read_text(errors='replace')[-3000:]}"
        for path in sorted(sandboxes.rglob("host.log"))
    ]
    return "\nprocesses:\n" + "\n".join(lines) + "\nlogs:\n" + "\n".join(logs)


def _gone(root: Path, seconds: float = 10) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _hosts(root):
            return True
        time.sleep(0.2)
    return False


@pytest.mark.parametrize("mode", ["cancel", "interrupt", "crash"])
def test_no_app_host_outlives_an_interrupted_run(tmp_path: Path, mode: str) -> None:
    process = _start(tmp_path, mode)
    sandboxes = tmp_path / "sandboxes"
    try:
        if mode == "cancel":
            assert process.stdout is not None
            assert "STATUS cancelled" in process.stdout.read()
        if mode == "interrupt":
            process.send_signal(signal.SIGINT)
        elif mode == "crash":
            process.kill()
        process.wait(timeout=60)
        assert _gone(sandboxes), f"App host left running after {mode}"
    finally:
        if process.poll() is None:
            process.kill()
        for pid in _hosts(sandboxes):
            os.kill(pid, signal.SIGKILL)
