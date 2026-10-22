"""Tracing an agent that runs elsewhere: the config, the tracer, the adapters, and serve."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
import yaml
from pydantic import ValidationError

from plural import Agent, DeterministicVerifier, Environment, Job, Runtime, Task, VerifierOutput
from plural.atif import validate_atif
from plural.errors import ConfigurationError
from plural.external import (
    AgentConfig,
    Episode,
    FlushPolicy,
    Run,
    ToolCall,
    Tracer,
    current_run,
    new_signing_key,
)
from plural.external.config import render_template
from plural.tracing import Trace

KEY = new_signing_key()
API_KEY = "plural_test-api-key-value"


class _Traces:
    def __init__(self) -> None:
        self.sent: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def create(self, trace: dict[str, Any], **links: Any) -> dict[str, Any]:
        self.sent.append((trace, links))
        return {}


class _Agents:
    def __init__(self) -> None:
        self.pushed: list[Agent] = []

    def find(self, slug: str) -> dict[str, Any] | None:
        return {"id": "ag_takeoff"} if slug == "takeoff" else None

    def push(self, agent: Agent) -> dict[str, Any]:
        self.pushed.append(agent)
        return {"id": "agr_1", "agent_id": "ag_takeoff"}


class _Studio:
    def __init__(self) -> None:
        self.traces = _Traces()
        self.agents = _Agents()


def _config(**tracing: Any) -> AgentConfig:
    return AgentConfig.model_validate(
        {
            "agent": {"name": "takeoff", "version": "2026.10.3", "model": "acme/v3"},
            "tracing": tracing,
        }
    )


def _tracer(studio: _Studio, **tracing: Any) -> Tracer:
    return Tracer(_config(**tracing), environ={"PLURAL_API_KEY": API_KEY}, studio=studio)


def _work(run: Run) -> None:
    run.llm(
        messages=[
            {"role": "system", "content": "Count exactly."},
            {"role": "user", "content": "Count the doors on A-201."},
        ],
        output="",
        tool_calls=[ToolCall(id="c1", name="count_doors", arguments={"sheet": "A-201"})],
        usage={"prompt_tokens": 40, "completion_tokens": 8, "cost_usd": 0.0002},
    )
    run.tool("count_doors", {"sheet": "A-201"}, {"doors": 12}, call_id="c1")
    run.llm(messages=[], output="12 doors", usage={"prompt_tokens": 60, "completion_tokens": 3})


def test_the_generated_config_explains_every_field_and_loads(tmp_path: Path) -> None:
    text = render_template(name="takeoff", model="acme/v3", url="https://agents.acme.dev/plural")
    path = tmp_path / "plural-agent.yaml"
    path.write_text(text)

    config = AgentConfig.load(path, environ={})

    assert (config.agent.name, config.agent.url) == ("takeoff", "https://agents.acme.dev/plural")
    assert config.tracing.flush == FlushPolicy(mode="end")
    assert "Always written: trace_id, agent.name" in text
    for field in ("messages", "system_prompt", "reasoning", "tool_arguments", "tool_results"):
        assert f"    {field}: true" in text
    overridden = AgentConfig.load(
        path,
        environ={
            "PLURAL_TRACE_FLUSH": "interval:5",
            "PLURAL_TRACE_PRODUCTION": "false",
            "PLURAL_AGENT_VERSION": "2026.11.0",
        },
    )
    assert overridden.tracing.flush == FlushPolicy(mode="interval", interval_seconds=5)
    assert overridden.tracing.production is False
    assert overridden.agent.version == "2026.11.0"
    with pytest.raises(ConfigurationError, match="not one of end"):
        AgentConfig.load(path, environ={"PLURAL_TRACE_FLUSH": "sometimes"})
    with pytest.raises(ConfigurationError, match="plural external init"):
        AgentConfig.load(tmp_path / "missing.yaml", environ={})


def test_production_tracing_needs_an_api_key_and_jobs_alone_do_not() -> None:
    with pytest.raises(ConfigurationError, match="PLURAL_API_KEY"):
        Tracer(_config(), environ={})

    jobs_only = Tracer(_config(production=False), environ={})
    with jobs_only.run(input="hello") as run:
        run.finish("hi")
    assert not run.recording


def test_a_run_becomes_one_production_trace_of_the_agent() -> None:
    studio = _Studio()
    tracer = _tracer(studio)

    with tracer.run(input="Count the doors on A-201.", metadata={"customer": "acme"}) as run:
        assert current_run() is run
        _work(run)
        run.finish("12 doors")
    assert current_run() is None
    assert tracer.flush()

    [(payload, links)] = studio.traces.sent
    assert links == {"in_progress": False, "agent_id": "ag_takeoff"}
    trace = Trace.model_validate(payload)
    assert trace.trace_kind == "production"
    assert [step.type for step in trace.steps] == ["event", "llm", "action", "llm"]
    assert trace.tags["agent_version"] == "2026.10.3"
    assert trace.metadata["metadata"] == {"customer": "acme"}
    assert trace.metadata["answer"] == "12 doors"
    first = payload["steps"][1]
    assert first["request"]["messages"][0] == {"role": "system", "content": "Count exactly."}
    assert first["response"]["choices"][0]["message"]["tool_calls"][0]["function"] == {
        "name": "count_doors",
        "arguments": '{"sheet": "A-201"}',
    }
    document = run.atif()
    assert validate_atif(document) == []
    sources = [(step["source"], step["message"]) for step in document["steps"]]
    assert sources[:2] == [("system", "Count exactly."), ("user", "Count the doors on A-201.")]
    assert document["steps"][2]["observation"]["results"][0]["source_call_id"] == "c1"
    assert document["steps"][-1]["message"] == "12 doors"
    assert document["final_metrics"]["total_prompt_tokens"] == 100


def test_what_is_not_captured_never_leaves_the_service() -> None:
    studio = _Studio()
    tracer = _tracer(
        studio,
        capture={"messages": False, "tool_arguments": False, "tool_results": False},
        redact=[r"\b\d{3}-\d{2}-\d{4}\b"],
    )

    with tracer.run(input="SSN 123-45-6789, count the doors") as run:
        _work(run)
        run.tool("lookup", {"q": "x"}, {"token": API_KEY})
        run.finish("12 doors")
    tracer.flush()

    sent = json.dumps(studio.traces.sent)
    assert "123-45-6789" not in sent and "count the doors" not in sent
    assert "A-201" not in sent and '"doors": 12' not in sent
    assert API_KEY not in sent and API_KEY not in json.dumps(run.atif())
    assert "Count exactly." in sent  # the system prompt is still captured


def test_a_long_run_is_written_while_it_goes_and_the_final_write_wins() -> None:
    studio = _Studio()
    tracer = _tracer(studio, flush="steps:2")

    with tracer.run() as run:
        for index in range(5):
            run.tool("step", {"n": index}, index)
        tracer.flush()
        partial = list(studio.traces.sent)
        run.finish("done")
    tracer.flush()

    assert partial and all(links["in_progress"] for _, links in partial)
    final, links = studio.traces.sent[-1]
    assert links["in_progress"] is False
    assert len([step for step in final["steps"] if step["type"] == "action"]) == 5
    run.tool("late", {}, None)
    tracer.flush()
    assert studio.traces.sent[-1][1]["in_progress"] is False


def test_interval_flushing_writes_an_idle_run() -> None:
    studio = _Studio()
    tracer = _tracer(studio, flush={"mode": "interval", "interval_seconds": 1})

    with tracer.run() as run:
        run.tool("step", {}, 1)
        deadline = time.monotonic() + 5
        while not studio.traces.sent and time.monotonic() < deadline:
            time.sleep(0.05)
        assert studio.traces.sent and studio.traces.sent[0][1]["in_progress"] is True
    tracer.flush()
    assert studio.traces.sent[-1][1]["in_progress"] is False


def test_a_trace_past_its_size_limit_drops_steps_and_says_so() -> None:
    studio = _Studio()
    tracer = _tracer(studio, max_trace_bytes=20_000)

    with tracer.run() as run:
        for index in range(200):
            run.tool("read", {"page": index}, "x" * 400)
    tracer.flush()

    payload, _ = studio.traces.sent[-1]
    assert len(json.dumps(payload)) <= 20_000
    assert payload["metadata"]["dropped_steps"] > 0
    assert run.atif()["extra"]["dropped_steps"] > 0


def test_sampling_keeps_no_production_run_at_rate_zero() -> None:
    studio = _Studio()
    tracer = _tracer(studio, sample_rate=0.0)

    with tracer.run() as run:
        _work(run)
    tracer.flush()

    assert not run.recording and studio.traces.sent == []


def test_a_failed_run_is_marked_failed() -> None:
    studio = _Studio()
    tracer = _tracer(studio)

    with pytest.raises(RuntimeError), tracer.run() as run:
        run.tool("step", {}, 1)
        raise RuntimeError("model down")
    tracer.flush()

    payload, _ = studio.traces.sent[-1]
    assert payload["failed"] is True
    assert payload["metadata"]["error"] == "RuntimeError: model down"


def test_opentelemetry_spans_from_any_framework_become_one_run() -> None:
    from opentelemetry.sdk.trace import TracerProvider

    from plural.external.otel import instrument

    studio = _Studio()
    provider = TracerProvider()
    instrument(_tracer(studio), provider=provider)
    spans = provider.get_tracer("crewai")

    output = [{"role": "assistant", "parts": [{"type": "text", "content": "12 doors"}]}]
    with spans.start_as_current_span(
        "invoke_agent takeoff",
        attributes={
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.output.messages": json.dumps(output),
        },
    ):
        with spans.start_as_current_span(
            "chat acme/v3",
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "acme/v3",
                "gen_ai.usage.input_tokens": 40,
                "gen_ai.usage.output_tokens": 8,
                "gen_ai.input.messages": json.dumps(
                    [{"role": "user", "parts": [{"type": "text", "content": "Count the doors."}]}]
                ),
                "gen_ai.output.messages": json.dumps(
                    [
                        {
                            "role": "assistant",
                            "parts": [
                                {
                                    "type": "tool_call",
                                    "id": "c1",
                                    "name": "count_doors",
                                    "arguments": {"sheet": "A-201"},
                                }
                            ],
                        }
                    ]
                ),
            },
        ):
            pass
        with spans.start_as_current_span(
            "execute_tool count_doors",
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": "count_doors",
                "gen_ai.tool.call.id": "c1",
                "gen_ai.tool.call.arguments": '{"sheet": "A-201"}',
                "gen_ai.tool.call.result": '{"doors": 12}',
            },
        ):
            pass
        with spans.start_as_current_span(
            "openinference llm",
            attributes={
                "openinference.span.kind": "LLM",
                "llm.model_name": "acme/v3",
                "llm.input_messages.0.message.role": "tool",
                "llm.input_messages.0.message.content": '{"doors": 12}',
                "llm.output_messages.0.message.role": "assistant",
                "llm.output_messages.0.message.content": "12 doors",
                "llm.token_count.prompt": 60,
            },
        ):
            pass
    _tracer_flush(studio)

    [(payload, _)] = studio.traces.sent
    assert [step["type"] for step in payload["steps"]] == ["llm", "action", "llm"]
    call = payload["steps"][0]["response"]["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "count_doors"
    assert payload["steps"][1]["result"] == {"doors": 12}
    assert payload["steps"][2]["usage"]["prompt_tokens"] == 60
    assert payload["metadata"]["answer"] == "12 doors"


def _tracer_flush(studio: _Studio, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not studio.traces.sent and time.monotonic() < deadline:
        time.sleep(0.02)


def test_a_langchain_run_records_its_model_and_tool_calls() -> None:
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.runnables import RunnableLambda
    from langchain_core.tools import tool

    from plural.external.langchain import PluralCallbackHandler

    @tool
    def count_doors(sheet: str) -> int:
        """Count the doors on a sheet."""
        return 12

    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "count_doors", "args": {"sheet": "A-201"}}],
            ),
            AIMessage(content="12 doors"),
        ]
    )

    def agent(question: str) -> dict[str, Any]:
        messages: list[Any] = [HumanMessage(content=question)]
        reply = model.invoke(messages)
        messages.append(reply)
        for call in reply.tool_calls:
            result = count_doors.invoke(call)
            messages.append(
                result
                if isinstance(result, ToolMessage)
                else ToolMessage(str(result), tool_call_id="c1")
            )
        messages.append(model.invoke(messages))
        return {"messages": messages}

    studio = _Studio()
    tracer = _tracer(studio)
    RunnableLambda(agent).invoke(
        "Count the doors on A-201.", config={"callbacks": [PluralCallbackHandler(tracer)]}
    )
    tracer.flush()

    [(payload, _)] = studio.traces.sent
    kinds = [step["type"] for step in payload["steps"]]
    assert kinds == ["llm", "action", "llm"]
    assert payload["steps"][1]["name"] == "count_doors"
    assert payload["steps"][1]["tool_call_id"] == "c1"
    assert payload["metadata"]["answer"] == "12 doors"
    assert payload["steps"][0]["request"]["messages"][0]["content"] == "Count the doors on A-201."


def test_an_openai_agents_run_records_its_generations_and_functions() -> None:
    import agents
    from agents.tracing import function_span, generation_span

    from plural.external.openai_agents import PluralTracingProcessor

    studio = _Studio()
    tracer = _tracer(studio)
    agents.set_trace_processors([PluralTracingProcessor(tracer)])
    try:
        with agents.trace("takeoff"):
            with generation_span(
                input=[{"role": "user", "content": "Count the doors on A-201."}],
                output=[
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "count_doors",
                                    "arguments": '{"sheet": "A-201"}',
                                },
                            }
                        ],
                    }
                ],
                model="acme/v3",
                usage={"input_tokens": 40, "output_tokens": 8},
            ):
                pass
            with function_span("count_doors", input='{"sheet": "A-201"}', output="12"):
                pass
            with generation_span(
                input=[], output=[{"role": "assistant", "content": "12 doors"}], model="acme/v3"
            ):
                pass
    finally:
        agents.set_trace_processors([])
    tracer.flush()

    [(payload, _)] = studio.traces.sent
    assert [step["type"] for step in payload["steps"]] == ["llm", "action", "llm"]
    assert payload["steps"][1]["arguments"] == {"sheet": "A-201"}
    assert payload["steps"][0]["usage"]["prompt_tokens"] == 40
    assert payload["metadata"]["answer"] == "12 doors"


@pytest.fixture
def agent_service(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, list[Episode]]]:
    from plural.external import serve

    monkeypatch.setenv("ACME_SIGNING_KEY", KEY)
    monkeypatch.setenv("PLURAL_SIGNING_KEY", KEY)
    seen: list[Episode] = []

    def work(episode: Episode, run: Run) -> str:
        seen.append(episode)
        with tracer.run(metadata={"thread": "t-1"}) as inner:
            assert inner is run  # a framework's own run joins the episode
            _work(run)
        assert run.snapshot()[1]["thread"] == "t-1"
        assert not run.finished
        return "12 doors"

    tracer = Tracer(_config(production=False), environ={})
    app = serve.app(work, tracer_=tracer, key=KEY)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/plural", seen
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_a_served_agent_in_a_bare_environment_is_scored_on_its_answer(
    agent_service: tuple[str, list[Episode]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, seen = agent_service
    monkeypatch.chdir(tmp_path)

    def matches(episode: Any) -> VerifierOutput:
        return VerifierOutput(score=float(episode.answer == episode.expected))

    task = Task(
        name="count-doors",
        instructions="Count the doors on A-201.",
        environment=Environment(name="bare", runtime=Runtime.local(), limits={"max_seconds": 20}),
        verifiers=[DeterministicVerifier(name="doors", check=matches)],
        expected="12 doors",
    )
    agent = Agent(
        model="acme/takeoff-v3",
        external={"url": url, "signing_key": "ACME_SIGNING_KEY", "version": "2026.10.3"},
    )

    trial = Job(task, agents=[agent]).run().trials[0]

    assert trial.status == "succeeded", trial.error_message
    assert trial.score == 1.0
    assert trial.integrity == ()
    assert len(seen) == 1
    assert "12 doors" not in seen[0].start.model_dump_json()
    [stored] = (tmp_path / ".plural" / "jobs").rglob("agent-trace.json")
    trace = json.loads(stored.read_text())
    assert validate_atif(trace) == []
    assert trace["session_id"] == seen[0].start.episode_id
    assert [(step["source"], step["message"]) for step in trace["steps"][:2]] == [
        ("system", "Count exactly."),
        ("user", "Count the doors on A-201."),
    ]
    assert [step.get("model_name") for step in trace["steps"] if step.get("llm_call_count")] == [
        "acme/v3",
        "acme/v3",
    ]


def test_a_served_agent_refuses_unsigned_starts(agent_service: tuple[str, list[Episode]]) -> None:
    import httpx

    url, seen = agent_service
    refused = httpx.post(url, json={"protocol": "plural-episode-v1", "type": "ping"})
    assert refused.status_code == 401
    assert seen == []


def test_the_cli_writes_registers_and_checks_an_external_agent(
    agent_service: tuple[str, list[Episode]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from plural.cli import external_commands
    from plural.cli.main import app

    url, _ = agent_service
    studio = _Studio()
    monkeypatch.setattr(external_commands, "_studio", lambda config: studio)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    made = runner.invoke(app, ["external", "init", "takeoff", "--model", "acme/v3", "--url", url])
    assert made.exit_code == 0, made.output
    assert yaml.safe_load((tmp_path / "plural-agent.yaml").read_text())["agent"]["url"] == url
    again = runner.invoke(app, ["external", "init", "takeoff"])
    assert again.exit_code != 0 and "--force" in again.output
    assert "TAKEOFF_SIGNING_KEY" in made.output

    registered = runner.invoke(app, ["external", "register", "--json"])
    assert registered.exit_code == 0, registered.output
    assert json.loads(registered.output)["agent_id"] == "ag_takeoff"
    [pushed] = studio.agents.pushed
    assert pushed.external is not None
    assert (pushed.external.url, pushed.external.signing_key) == (url, "TAKEOFF_SIGNING_KEY")

    checked = runner.invoke(app, ["external", "check", "--json"])
    assert checked.exit_code == 0, checked.output
    assert {item["check"]: item["ok"] for item in json.loads(checked.output)["checks"]} == {
        "config": True,
        "api key": True,
        "registered": True,
        "signed ping": True,
    }


def test_the_signing_key_secret_defaults_from_the_name_and_is_never_reserved() -> None:
    config = AgentConfig.model_validate(
        {"agent": {"name": "support-bot", "version": "1", "model": "acme/v3"}}
    )
    assert config.agent.signing_key == "SUPPORT_BOT_SIGNING_KEY"
    with pytest.raises(ValidationError, match="PLURAL_SIGNING_KEY"):
        AgentConfig.model_validate(
            {
                "agent": {
                    "name": "a",
                    "version": "1",
                    "model": "m",
                    "signing_key": "PLURAL_SIGNING_KEY",
                }
            }
        )


def test_serving_without_a_signing_key_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from plural.external import serve

    monkeypatch.delenv("PLURAL_SIGNING_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="plural agent key"):
        serve.app(lambda episode, run: "", tracer_=Tracer(_config(production=False), environ={}))
