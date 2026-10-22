from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from pydantic import ValidationError

from plural import (
    Agent,
    DeterministicVerifier,
    Environment,
    Episode,
    Harness,
    HarnessResult,
    Job,
    Runtime,
    Task,
    VerifierOutput,
)
from plural.common import ErrorCode
from plural.execution.engine import ExecutionFailure, _harness_environment
from plural.harness import native_runner
from plural.harness.packages import native_actions_v1, native_chat_v1
from plural.jobs import AgentBinding


class _AgentServer(BaseHTTPRequestHandler):
    requests: list[tuple[str, str | None, dict[str, Any]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append((self.path, self.headers.get("Authorization"), body))
        payload = json.dumps(
            {
                "choices": [{"message": {"role": "assistant", "content": "PAID"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def agent_server() -> Iterator[str]:
    _AgentServer.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AgentServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()


class AskTheEndpoint(Harness):
    name = "ask-the-endpoint"

    def run(self, task, agent, environment):
        reply = agent.complete([{"role": "user", "content": task.instructions}])
        return HarnessResult(response=reply.text)


def answered_paid(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1.0 if "PAID" in json.dumps(episode.trajectory) else 0.0)


def test_an_endpoint_agent_needs_no_catalog_model() -> None:
    agent = Agent(
        model="acme/support-agent",
        endpoint="https://agents.acme.dev/v1",
        endpoint_key="ACME_AGENT_KEY",
    )

    assert agent.name == "support-agent"
    definition = agent._definition()
    assert definition.endpoint == "https://agents.acme.dev/v1"
    assert definition.endpoint_key == "ACME_AGENT_KEY"
    with pytest.raises(ValidationError, match="Unknown model"):
        Agent(model="acme/support-agent")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"endpoint": "agents.acme.dev"}, "http"),
        ({"endpoint": "https://a.dev/v1", "harness": "codex"}, "cannot use an endpoint"),
        ({"endpoint": "https://a.dev/v1", "secrets": ("X",)}, "takes no secrets"),
        ({"endpoint": "https://a.dev/v1", "fallback_models": ("x/y",)}, "fallback_models"),
        ({"endpoint": "https://a.dev/v1", "endpoint_key": "PLURAL_API_KEY"}, "resource controls"),
    ],
)
def test_endpoint_agent_rejects_settings_it_cannot_honor(
    fields: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Agent(model="acme/support-agent", **fields)


def test_the_endpoint_key_reaches_only_the_native_runner() -> None:
    binding = AgentBinding(
        agent=Agent(
            model="acme/agent", endpoint="https://a.dev/v1", endpoint_key="ACME_KEY"
        )._definition()
    )

    environment, secrets = _harness_environment(
        binding, native_actions_v1(), {"ACME_KEY": "sk-acme", "OTHER": "x"}
    )

    assert environment["PLURAL_AGENT_ENDPOINT"] == "https://a.dev/v1"
    assert environment["PLURAL_AGENT_ENDPOINT_KEY"] == "sk-acme"
    assert "ACME_KEY" not in environment
    assert secrets == {"PLURAL_AGENT_ENDPOINT_KEY": "sk-acme"}
    with pytest.raises(ExecutionFailure, match="needs ACME_KEY") as missing:
        _harness_environment(binding, native_chat_v1(), {})
    assert missing.value.code is ErrorCode.AUTHENTICATION


def test_the_native_runner_calls_the_endpoint_instead_of_the_gateway(
    agent_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PLURAL_GATEWAY_URL", raising=False)
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.setenv("PLURAL_AGENT_ENDPOINT", agent_server)
    monkeypatch.setenv("PLURAL_AGENT_ENDPOINT_KEY", "sk-acme")

    reply, _ = native_runner._model_call(
        model="acme/agent",
        routing={"temperature": 0.2},
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        timeout=5,
    )

    assert reply["choices"][0]["message"]["content"] == "PAID"
    path, authorization, body = _AgentServer.requests[0]
    assert path == "/v1/chat/completions"
    assert authorization == "Bearer sk-acme"
    assert body == {
        "model": "acme/agent",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.2,
    }


def test_a_job_runs_an_endpoint_agent_without_a_plural_key(
    agent_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("PLURAL_GATEWAY_URL", raising=False)
    monkeypatch.setenv("ACME_KEY", "sk-acme")
    monkeypatch.chdir(tmp_path)
    task = Task(
        name="refund-01",
        instructions="Say PAID.",
        environment=Environment(name="support", runtime=Runtime.local()),
        verifiers=[DeterministicVerifier(name="paid", check=answered_paid)],
    )
    agent = Agent(model="acme/agent", endpoint=agent_server, endpoint_key="ACME_KEY")

    result = Job(task, agents=[agent]).run()

    trial = result.trials[0]
    assert trial.score == 1.0, trial.error_message
    assert _AgentServer.requests[0][1] == "Bearer sk-acme"


def test_a_custom_harness_reaches_the_endpoint_through_complete(
    agent_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("PLURAL_GATEWAY_URL", raising=False)
    monkeypatch.setenv("ACME_KEY", "sk-acme")
    monkeypatch.chdir(tmp_path)
    task = Task(
        name="refund-01",
        instructions="Say PAID.",
        environment=Environment(name="support", runtime=Runtime.local()),
        verifiers=[DeterministicVerifier(name="paid", check=answered_paid)],
    )
    agent = Agent(
        model="acme/agent",
        endpoint=agent_server,
        endpoint_key="ACME_KEY",
        harness=AskTheEndpoint(),
    )

    result = Job(task, agents=[agent]).run()

    trial = result.trials[0]
    assert trial.score == 1.0, trial.error_message
    path, authorization, body = _AgentServer.requests[0]
    assert (path, authorization) == ("/v1/chat/completions", "Bearer sk-acme")
    assert body["model"] == "acme/agent"


def test_a_built_in_harness_cannot_use_an_endpoint() -> None:
    codex = Agent(model="openai/gpt-5.6-luna", harness="codex")._definition().harness
    endpoint = Agent(model="acme/agent", endpoint="https://a.dev/v1")._definition()
    binding = AgentBinding(agent=endpoint.model_copy(update={"harness": codex}))

    with pytest.raises(ExecutionFailure, match="cannot use"):
        _harness_environment(binding, native_chat_v1(), {})


def test_a_local_runtime_names_the_packages_it_lacks(
    agent_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("ACME_KEY", "sk-acme")
    monkeypatch.chdir(tmp_path)
    runtime = Runtime.local(packages={"python": ["pydantic>=2", "surely-not-installed-xyz>=1"]})
    task = Task(
        name="refund-01",
        instructions="Say PAID.",
        environment=Environment(name="support", runtime=runtime),
        verifiers=[DeterministicVerifier(name="paid", check=answered_paid)],
    )
    agent = Agent(model="acme/agent", endpoint=agent_server, endpoint_key="ACME_KEY")

    with pytest.raises(ExecutionFailure) as failure:
        Job(task, agents=[agent]).run()

    message = str(failure.value)
    assert "does not have: surely-not-installed-xyz>=1." in message
    assert "pip install 'surely-not-installed-xyz>=1'" in message
