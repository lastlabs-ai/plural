"""External Agents: a service of its own works a Task over signed HTTPS."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from plural import (
    Agent,
    DeterministicVerifier,
    Environment,
    Job,
    Resource,
    Runtime,
    Task,
    VerifierOutput,
)
from plural.environments.env import load_reference
from plural.execution.engine import JobRunner
from plural.execution.episode_server import (
    EpisodeServer,
    EpisodeServerOptions,
)
from plural.execution.integrity import audit_external
from plural.external import (
    Episode,
    EpisodeAction,
    SignatureError,
    new_signing_key,
    sign,
    signing_key,
    verify,
    verify_request,
)
from plural.external.protocol import _Seen
from plural.jobs import JobMode
from plural.sandbox import DownloadedFile
from plural.studio import AgentsAPI

KEY = new_signing_key()
APP_SOURCE = '''
from plural import App, State, action


class Count(State):
    doors: int | None = None


class Takeoff(App[Count]):
    """Record what the drawing shows."""

    @action
    def submit(self, doors: int) -> str:
        """Submit the number of doors."""
        self.state.doors = doors
        return "recorded"

    def terminated(self) -> bool:
        return self.state.doors is not None
'''
TRACE = {
    "schema_version": "ATIF-v1.6",
    "session_id": "acme-1",
    "agent": {"name": "acme-takeoff", "version": "2026.10.3"},
    "steps": [{"step_id": 1, "source": "user", "message": "Count the doors."}],
}

Work = Callable[[Episode], None]


class _Service(BaseHTTPRequestHandler):
    work: Work | None = None
    status = 202
    reply: dict[str, Any] | None = None
    received: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        try:
            message = verify_request(body, dict(self.headers), key=KEY)
        except SignatureError:
            self.send_response(401)
            self.end_headers()
            return
        type(self).received.append(json.loads(body))
        payload = json.dumps(type(self).reply or {}).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        work = type(self).work
        if message.type == "episode.start" and work is not None:
            threading.Thread(target=self._work, args=(work, Episode(message))).start()

    @staticmethod
    def _work(work: Work, episode: Episode) -> None:
        try:
            work(episode)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the test
            _Service.errors.append(exc)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("ACME_SIGNING_KEY", KEY)
    _Service.work, _Service.status, _Service.reply = None, 202, None
    _Service.received, _Service.errors = [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/plural"
    finally:
        server.shutdown()


def _agent(url: str) -> Agent:
    return Agent(
        model="acme/takeoff-v3",
        external={"url": url, "signing_key": "ACME_SIGNING_KEY", "version": "2026.10.3"},
    )


def _task(root: Path, *, max_seconds: float = 20, info: dict[str, Any] | None = None) -> Task:
    (root / "takeoff.py").write_text(APP_SOURCE)
    drawing = root / "A-201.pdf"
    drawing.write_bytes(b"%PDF-1.7 doors=12")
    takeoff = load_reference("takeoff.py:Takeoff", root)
    environment = Environment(
        name="drawings",
        apps=[takeoff()],
        runtime=Runtime.local(),
        source=root,
        limits={"max_seconds": max_seconds, "max_turns": 2},
    )

    def doors(episode: Any) -> VerifierOutput:
        return VerifierOutput(score=float(episode.state.get("doors") == 12))

    return Task(
        name="count-doors",
        instructions="Count the doors on A-201.",
        info=info or {},
        environment=environment,
        resources=[Resource.from_file(drawing)],
        verifiers=[DeterministicVerifier(name="doors", check=doors)],
    )


def _count_doors(episode: Episode) -> None:
    drawing = episode.read("task-resources/A-201.pdf")
    doors = int(drawing.split(b"doors=")[1])
    episode.act("submit", doors=doors)
    episode.trace(TRACE)
    episode.finish(f"{doors} doors")


def test_an_external_agent_names_its_service_and_never_its_key() -> None:
    agent = _agent("https://agents.acme.dev/plural")

    assert agent.name == "takeoff-v3"
    moved = Agent(
        model="acme/takeoff-v3",
        external={
            "url": "https://agents.acme.dev/plural",
            "signing_key": "OTHER_KEY",
            "version": "2026.10.3",
            "ca_bundle": "/etc/acme/ca.pem",
        },
    )
    assert moved.content_hash == agent.content_hash
    pushed = AgentsAPI._revision_payload(object.__new__(AgentsAPI), moved)
    assert "ca_bundle" not in pushed["external"]
    released = _agent("https://agents.acme.dev/plural").model_copy(
        update={"external": agent.external.model_copy(update={"version": "2026.11.0"})}
    )
    assert released._definition().content_hash != agent.content_hash
    assert (
        Agent(model="openai/gpt-5.6-luna").content_hash
        == Agent(model="openai/gpt-5.6-luna").content_hash
    )


@pytest.mark.parametrize(
    ("external", "fields", "message"),
    [
        ({"url": "http://agents.acme.dev"}, {}, "uses http"),
        ({"url": "https://user:pw@agents.acme.dev"}, {}, "user name or password"),
        ({"url": "ftp://agents.acme.dev"}, {}, "https URL"),
        ({"url": "https://agents.acme.dev", "signing_key": "the-key-itself"}, {}, "pattern"),
        ({"url": "https://agents.acme.dev"}, {"harness": "codex"}, "harness"),
        ({"url": "https://agents.acme.dev"}, {"endpoint": "https://m.dev/v1"}, "endpoint"),
        ({"url": "https://agents.acme.dev"}, {"temperature": 0.2}, "temperature"),
    ],
)
def test_an_external_agent_refuses_what_it_cannot_honor(
    external: dict[str, Any], fields: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Agent(model="acme/takeoff", external={"signing_key": "ACME_KEY", **external}, **fields)


def test_a_signature_checks_the_body_the_time_and_the_id() -> None:
    key = signing_key(KEY)
    body = b'{"type":"ping"}'
    headers = sign(key, body, message_id="msg_1")
    seen = _Seen()

    assert verify(key, body, headers, seen=seen) == "msg_1"
    with pytest.raises(SignatureError, match="already received"):
        verify(key, body, headers, seen=seen)
    with pytest.raises(SignatureError, match="does not match"):
        verify(key, b'{"type":"pong"}', sign(key, body, message_id="msg_2"), seen=seen)
    with pytest.raises(SignatureError, match="does not match"):
        verify(signing_key(new_signing_key()), body, sign(key, body, message_id="msg_3"))
    stale = sign(key, body, message_id="msg_4", timestamp=int(time.time()) - 301)
    with pytest.raises(SignatureError, match="five minutes"):
        verify(key, body, stale, seen=seen)
    with pytest.raises(SignatureError, match="missing"):
        verify(key, body, {}, seen=seen)
    with pytest.raises(ValueError, match="at least 32 bytes"):
        signing_key("short")


def test_a_job_runs_an_external_agent_through_the_app_host(
    service: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _Service.work = _count_doors

    result = Job(_task(tmp_path), agents=[_agent(service)]).run()

    assert not _Service.errors, _Service.errors
    trial = result.trials[0]
    assert trial.status == "succeeded", trial.error_message
    assert (trial.score, trial.stop_reason, trial.turns) == (1.0, "environment_terminated", 1)
    assert trial.receipt.model.provider == "external"
    [start] = _Service.received
    assert start["protocol"] == "plural-episode-v1"
    assert start["task"]["instructions"] == "Count the doors on A-201."
    assert [item["name"] for item in start["actions"]] == ["submit"]
    assert "task-resources/A-201.pdf" in start["files"]
    assert not {"score", "reward", "verifiers", "state"} & set(start)
    trial_dir = next((tmp_path / ".plural" / "jobs").glob("*/trials/*/executions/*"))
    stored = {path.name: path.read_bytes() for path in trial_dir.rglob("*") if path.is_file()}
    outcome = json.loads(stored["result.json"])
    assert outcome["response"] == "12 doors"
    assert (outcome["agent_kind"], outcome["trace"]) == ("external", "self_reported")
    assert json.loads(stored["agent-trace.json"])["agent"]["name"] == "acme-takeoff"
    assert [item.code for item in trial.integrity] == ["actions_not_traced"]
    steps = [json.loads(line) for line in stored["steps.jsonl"].splitlines()]
    assert [step.get("action") for step in steps if step.get("action")] == ["submit"]
    every_byte = b"".join(stored.values()) + b"".join(
        path.read_bytes() for path in (tmp_path / ".plural").rglob("*") if path.is_file()
    )
    assert start["token"].encode() not in every_byte
    assert KEY.encode() not in every_byte


def test_an_external_agent_calls_models_only_with_its_executions_own_key(
    service: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLURAL_API_KEY", "plural_the-users-own-key")
    _Service.status, _Service.reply = 200, {"response": "12 doors"}
    minted: list[tuple[str, int, int]] = []

    def gateway_keys(trial_id: str, execution_id: int, ttl: int) -> str:
        minted.append((trial_id, execution_id, ttl))
        return "plural_trial-execution-key"

    job = Job(_task(tmp_path), agents=[_agent(service)])
    runner = JobRunner(job.spec, environ=dict(os.environ), gateway_keys=gateway_keys)
    trial = asyncio.run(runner.run()).trials[0]

    assert trial.status == "succeeded", trial.error_message
    [start] = _Service.received
    assert start["gateway"]["key"] == "plural_trial-execution-key"
    assert "plural_the-users-own-key" not in json.dumps(start)
    assert minted and 600 <= minted[0][2] <= 86_400
    every_byte = b"".join(
        path.read_bytes() for path in (tmp_path / ".plural").rglob("*") if path.is_file()
    )
    assert b"plural_trial-execution-key" not in every_byte


def test_an_agent_may_answer_in_its_reply_to_the_start(
    service: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _Service.status, _Service.reply = 200, {"response": "I could not find any doors"}

    trial = Job(_task(tmp_path), agents=[_agent(service)]).run().trials[0]

    assert trial.status == "succeeded", trial.error_message
    assert (trial.score, trial.stop_reason, trial.turns) == (0.0, "agent_finished", 0)


def test_an_agent_that_refuses_or_never_finishes_fails_the_trial(
    service: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _Service.status = 503

    refused = Job(_task(tmp_path), agents=[_agent(service)]).run().trials[0]
    _Service.status = 202
    silent = Job(_task(tmp_path, max_seconds=1), agents=[_agent(service)]).run().trials[0]

    assert refused.status == "failed"
    assert "refused the episode with HTTP 503" in (refused.error_message or "")
    assert silent.status == "failed"
    assert silent.stop_reason == "harness_timeout"


def test_a_wrong_signing_key_is_refused_by_the_agent(
    service: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ACME_SIGNING_KEY", new_signing_key())

    trial = Job(_task(tmp_path), agents=[_agent(service)]).run().trials[0]

    assert "HTTP 401" in (trial.error_message or "")
    assert _Service.received == []


def test_a_job_needs_the_signing_key_and_never_trains_an_external_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ACME_SIGNING_KEY", raising=False)
    agent = _agent("https://agents.acme.dev/plural")

    with pytest.raises(Exception, match="signs its episodes with ACME_SIGNING_KEY"):
        Job(_task(tmp_path), agents=[agent]).run()
    with pytest.raises(ValueError, match="train Job cannot use external Agent"):
        Job(_task(tmp_path), agents=[agent], mode=JobMode.TRAIN)


def test_a_task_that_tells_the_answer_never_reaches_an_external_agent(
    service: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    task = _task(tmp_path, info={"expected": 12})
    trial = Job(task, agents=[_agent(service)]).run().trials[0]

    assert trial.status == "failed"
    assert "'expected'" in (trial.error_message or "")
    assert _Service.received == []


async def _episode(server: EpisodeServer, **fields: Any) -> tuple[Any, str, Any]:
    async def act(_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"observation": {"got": arguments}, "done": False}

    return await server.register(
        actions=(EpisodeAction(name="submit"),),
        files={"task-resources/A-201.pdf": b"%PDF"},
        max_turns=fields.get("max_turns", 2),
        deadline=fields.get("deadline", time.time() + 60),
        act=act,
    )


async def test_a_token_opens_only_its_own_episode_until_it_ends() -> None:
    async with EpisodeServer() as server:
        first, token, urls = await _episode(server)
        _, other_token, other = await _episode(server)
        _, late_token, late = await _episode(server, deadline=time.time() - 31)
        async with httpx.AsyncClient() as client:

            async def post(url: str, token: str | None, payload: Any) -> httpx.Response:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                return await client.post(url, json=payload, headers=headers)

            assert (await post(f"{urls.actions}/submit", None, {})).status_code == 401
            assert (await post(f"{urls.actions}/submit", other_token, {})).status_code == 401
            assert (await post(f"{late.actions}/submit", late_token, {})).status_code == 401
            reply = await post(f"{urls.actions}/submit", token, {"doors": 1})
            assert reply.json() == {"observation": {"got": {"doors": 1}}, "done": False}
            assert (await post(f"{urls.actions}/nope", token, {})).status_code == 404
            await post(f"{urls.actions}/submit", token, {})
            assert (await post(f"{urls.actions}/submit", token, {})).status_code == 409
            file = await client.get(
                f"{urls.files}/task-resources/A-201.pdf",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert file.headers["content-disposition"] == "attachment"
            assert file.headers["x-content-type-options"] == "nosniff"
            assert (await post(urls.trace, token, {"steps": []})).status_code == 422
            assert (await post(urls.finish, token, {"response": "done"})).status_code == 200
            assert await first.finished == "done"
            assert (await post(f"{urls.actions}/submit", token, {})).status_code == 401
            assert (await post(f"{other.actions}/submit", other_token, {})).status_code == 200


async def test_the_server_caps_what_an_agent_may_send() -> None:
    async with EpisodeServer() as server:
        _, token, urls = await _episode(server)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient() as client:
            big = b'{"doors": "' + b"9" * (1024 * 1024) + b'"}'
            reply = await client.post(f"{urls.actions}/submit", content=big, headers=headers)
            assert reply.status_code == 413
            streamed = await client.post(
                f"{urls.actions}/submit",
                content=_chunks(big),
                headers=headers,
            )
            assert streamed.status_code == 413


async def _chunks(data: bytes) -> Any:
    for start in range(0, len(data), 65536):
        yield data[start : start + 65536]
        await asyncio.sleep(0)


def test_the_server_never_listens_beyond_loopback_without_tls(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="without TLS"):
        EpisodeServerOptions(listen="0.0.0.0:8765")
    with pytest.raises(ValidationError, match="go together"):
        EpisodeServerOptions(tls_cert=tmp_path / "cert.pem")
    with pytest.raises(ValidationError, match="https"):
        EpisodeServerOptions(public_url="http://runner.acme.internal")
    assert (
        EpisodeServerOptions(
            listen="0.0.0.0:8765", tls_cert=tmp_path / "c.pem", tls_key=tmp_path / "k.pem"
        ).port
        == 8765
    )


async def test_mcp_offers_the_episode_actions_behind_the_token() -> None:
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    async with EpisodeServer() as server:
        _, token, urls = await _episode(server)
        transport = StreamableHttpTransport(urls.mcp, headers={"Authorization": f"Bearer {token}"})
        async with Client(transport) as client:
            assert [tool.name for tool in await client.list_tools()] == ["submit"]
            result = await client.call_tool("submit", {"doors": 12})
            assert json.loads(result.content[0].text) == {"got": {"doors": 12}}
        async with httpx.AsyncClient() as raw:
            refused = await raw.post(urls.mcp, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
            assert refused.status_code == 401


def test_the_cli_writes_keys_and_tests_an_external_agent(
    service: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    from typer.testing import CliRunner

    from plural.cli.main import app

    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["project", "init", "takeoffs"]).exit_code == 0
    monkeypatch.chdir(tmp_path / "takeoffs")

    made = runner.invoke(
        app, ["agent", "init", "acme", "--external", service, "--model", "acme/takeoff-v3"]
    )
    assert made.exit_code == 0, made.output
    manifest = (tmp_path / "takeoffs" / "agents" / "acme" / "agent.yaml").read_text()
    assert f"url: {service}" in manifest
    assert "signing_key: ACME_SIGNING_KEY" in manifest
    assert runner.invoke(app, ["agent", "validate", "acme"]).exit_code == 0
    key = runner.invoke(app, ["agent", "key"]).output.strip()
    assert signing_key(key)

    tested = runner.invoke(app, ["agent", "test", "acme", "--json"])
    assert tested.exit_code == 0, tested.output
    assert json.loads(tested.output)["status"] == 202
    assert _Service.received == [{"protocol": "plural-episode-v1", "type": "ping"}]
    monkeypatch.setenv("ACME_SIGNING_KEY", key)
    assert runner.invoke(app, ["agent", "test", "acme"]).exit_code == 1
    insecure = runner.invoke(app, ["agent", "init", "b", "--external", "http://acme.dev/x"])
    assert insecure.exit_code != 0 and "Use https" in insecure.output


def _audit(trace: dict[str, Any] | None, *, response: str = "12 doors") -> list[str]:
    began = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    files = [
        DownloadedFile(path="result.json", data=json.dumps({"response": response}).encode()),
        DownloadedFile(path="steps.jsonl", data=b'{"action": "submit", "step": 1}\n'),
    ]
    if trace is not None:
        files.append(DownloadedFile(path="agent-trace.json", data=json.dumps(trace).encode()))
    findings = audit_external(
        files, actions=["submit"], started_at=began, finished_at=began + timedelta(minutes=5)
    )
    return [item.code for item in findings]


def test_the_audit_sets_the_trace_beside_what_plural_observed() -> None:
    def step(when: str, **fields: Any) -> dict[str, Any]:
        return {"source": "agent", "timestamp": f"2026-10-22T{when}Z", **fields}

    submit = {"function_name": "submit", "arguments": {"doors": 12}}
    honest = {
        "steps": [
            step("12:01:00", message="", tool_calls=[submit]),
            step("12:02:00", message="There are 12 doors."),
        ]
    }
    padded = {
        "steps": [
            step("12:01:00", message="", tool_calls=[submit, submit]),
            step("09:00:00", message="I found 14 doors."),
        ]
    }

    assert _audit(honest) == []
    assert _audit(None) == ["no_trace"]
    assert _audit(padded) == ["actions_not_observed", "answer_differs", "trace_outside_episode"]
    assert _audit({"steps": []}) == ["actions_not_traced"]
