from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from plural import Agent, DeterministicVerifier, Environment, Episode, Job, Runtime, Task
from plural.auth import AuthHTTPError, check_gateway_key
from plural.common import ErrorCode
from plural.execution.engine import ExecutionFailure
from plural.verifiers import VerifierOutput

KEY = "plural_secret-key-value"


class _Gateway(BaseHTTPRequestHandler):
    """A gateway whose key check and model calls answer with the given statuses."""

    key_status = 200
    chat_status = 401
    chats = 0

    def _send(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        cls = type(self)
        if self.path == "/v1/key" and cls.key_status == 200:
            self._send(200, {"valid": True, "prefix": "plural_sec", "scope": "user"})
        else:
            self._send(cls.key_status, {"error": {"type": "invalid_api_key"}})

    def do_POST(self) -> None:  # noqa: N802
        cls = type(self)
        self.rfile.read(int(self.headers["Content-Length"]))
        cls.chats += 1
        self._send(cls.chat_status, {"error": {"message": "Invalid API key"}})

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[str]:
    _Gateway.key_status, _Gateway.chat_status, _Gateway.chats = 200, 401, 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/v1"
    monkeypatch.setenv("PLURAL_GATEWAY_URL", url)
    monkeypatch.setenv("PLURAL_API_KEY", KEY)
    monkeypatch.setenv("PLURAL_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    yield url
    server.shutdown()


def _paid(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1.0 if episode.answer else 0.0)


def _task() -> Task:
    return Task(
        name="refund-01",
        instructions="Say PAID.",
        environment=Environment(name="support", runtime=Runtime.local()),
        verifiers=[DeterministicVerifier(name="paid", check=_paid)],
    )


def _client(status: int, body: dict[str, object], **headers: str) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(status, json=body, headers=headers))
    )


def test_a_rejected_key_stops_with_the_next_step_and_never_shows_the_key() -> None:
    with pytest.raises(AuthHTTPError) as rejected:
        check_gateway_key("https://gw/v1", KEY, http=_client(401, {}))

    assert rejected.value.code is ErrorCode.AUTHENTICATION
    assert "rejected PLURAL_API_KEY" in str(rejected.value)
    assert "Next: plural auth login" in str(rejected.value)
    assert KEY not in str(rejected.value)


def test_a_lockout_says_how_long_to_wait() -> None:
    error = {"error": {"type": "auth_locked_out", "message": "Too many requests until 12:00."}}

    locked = _client(429, error, **{"Retry-After": "840"})
    with pytest.raises(AuthHTTPError, match=r"(?s)until 12:00\..*wait 840 seconds"):
        check_gateway_key("https://gw/v1", KEY, http=locked)


@pytest.mark.parametrize("status", [404, 500])
def test_a_gateway_without_the_check_is_not_an_answer(status: int) -> None:
    check_gateway_key("https://gw/v1", KEY, http=_client(status, {}))


def test_a_job_with_a_rejected_key_runs_no_trial(gateway: str) -> None:
    _Gateway.key_status = 401

    with pytest.raises(ExecutionFailure, match="rejected PLURAL_API_KEY") as stopped:
        Job(_task(), agents=[Agent(model="openai/gpt-5.6-luna")], attempts=3).run()

    assert stopped.value.code is ErrorCode.AUTHENTICATION
    assert _Gateway.chats == 0


def test_the_first_authentication_failure_stops_every_trial(gateway: str) -> None:
    job = Job(_task(), agents=[Agent(model="openai/gpt-5.6-luna")], attempts=4, concurrency=1)

    result = job.run()

    statuses = [trial.status for trial in result.trials]
    assert statuses[0] == "failed"
    assert result.trials[0].error_code is ErrorCode.AUTHENTICATION
    assert statuses[1:] == ["cancelled"] * 3
    assert _Gateway.chats == 1
    assert result.stopped is not None
    assert "failed to authenticate" in result.stopped
    assert KEY not in result.stopped
