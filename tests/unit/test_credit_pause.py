from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from plural.common import HarnessProtocol
from plural.execution.engine import _credit_pause
from plural.harness import native_runner

_OUT_OF_CREDITS = {"error": {"type": "insufficient_credits", "message": "Out of credits"}}
_REPLY = {"choices": [{"message": {"role": "assistant", "content": "done"}}]}


class _Gateway(BaseHTTPRequestHandler):
    refusals = 0

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers["Content-Length"]))
        refused = type(self).refusals > 0
        type(self).refusals -= 1
        body = json.dumps(_OUT_OF_CREDITS if refused else _REPLY).encode()
        self.send_response(402 if refused else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("PLURAL_GATEWAY_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("PLURAL_API_KEY", "sk-test")
    monkeypatch.delenv("PLURAL_AGENT_ENDPOINT", raising=False)
    waits: list[float] = []
    monkeypatch.setattr(native_runner.time, "sleep", waits.append)
    yield waits
    server.shutdown()


def _call() -> tuple[dict[str, object], float]:
    return native_runner._model_call(
        model="openai/gpt-5.6-luna", routing={}, messages=[], tools=[], timeout=5
    )


def test_a_model_call_waits_for_credits_and_resumes(gateway: list[float]) -> None:
    _Gateway.refusals = 2

    reply, paused = _call()

    assert reply == _REPLY
    assert gateway == [30.0, 30.0]
    assert paused == 60.0


def test_a_model_call_gives_up_once_its_wait_is_spent(
    gateway: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(native_runner.CREDIT_PAUSE_VARIABLE, "45")
    _Gateway.refusals = 10

    with pytest.raises(RuntimeError, match="Out of credits.*plural trial rerun"):
        _call()
    assert gateway == [30.0, 15.0]


def _harness(*command: str) -> HarnessProtocol:
    return HarnessProtocol(name="h", revision="1.0.0", command=command)


def test_only_the_native_runner_on_the_gateway_gets_time_to_wait() -> None:
    native = _harness("python", "native_runner.py", "native.actions.v1")
    gateway = {"PLURAL_GATEWAY_URL": "https://gateway"}

    assert _credit_pause(native, gateway) == native_runner.DEFAULT_CREDIT_PAUSE_SECONDS
    assert _credit_pause(native, {**gateway, native_runner.CREDIT_PAUSE_VARIABLE: "90"}) == 90
    assert _credit_pause(native, {**gateway, "PLURAL_AGENT_ENDPOINT": "https://agent"}) == 0
    assert _credit_pause(_harness("codex", "exec"), gateway) == 0
