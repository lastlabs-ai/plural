from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from plural import Benchmark, Client, Dataset, Environment, TaskData, Trace
from plural.client import Plural
from plural.environments import TraceFilter
from plural.providers.openai_compatible import OpenAICompatible
from plural.tracing import JSONLSink, TraceContext
from plural.types import (
    ChatRequest,
    ChatResponse,
    Choice,
    Message,
    StreamChunk,
    StreamDelta,
    Usage,
)


class FakeProvider:
    name = "openai"

    def __init__(self, text: str = "ok", tool_calls: list[Any] | None = None) -> None:
        self.text = text
        self.tool_calls = tool_calls
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        msg = Message(role="assistant", content=self.text, tool_calls=self.tool_calls)
        return ChatResponse(
            id=f"id-{self.calls}",
            model=request.model,
            choices=[Choice(message=msg, finish_reason="stop")],
            usage=Usage.from_counts(10, 5, cost=0.001),
            provider=self.name,
            latency_ms=12.0,
        )

    def stream(self, request: ChatRequest) -> Iterator[StreamChunk]:
        yield StreamChunk(
            id="s1",
            model=request.model,
            delta=StreamDelta(content=self.text),
            finish_reason="stop",
            usage=Usage.from_counts(1, 1),
            provider=self.name,
        )

    async def achat(self, request: ChatRequest) -> ChatResponse:
        return self.chat(request)

    async def astream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        for chunk in self.stream(request):
            yield chunk

    def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


def test_client_chat_records_trace(tmp_path: Path) -> None:
    provider = FakeProvider("hello")
    client = Client(
        providers={"openai": provider},
        sink=None,
        trace_dir=tmp_path,
        capture_content=True,
    )
    # Replace default sink path created inside — recreate with explicit sink
    from plural.tracing import JSONLSink

    client.close()
    sink = JSONLSink(tmp_path / "traces.jsonl")
    client = Client(
        providers={"openai": provider},
        sink=sink,
        capture_content=True,
    )
    resp = client.chat(
        model="openai/gpt-4o-mini",
        messages=[Message(role="user", content="Hi")],
    )
    assert resp.text == "hello"
    client.flush()
    traces = sink.read_all()
    assert len(traces) == 1
    assert traces[0].steps[0].type == "llm"
    client.close()


def test_environment_rollout_and_benchmark(tmp_path: Path) -> None:
    from plural.tracing import JSONLSink

    sink = JSONLSink(tmp_path / "traces.jsonl")
    client = Client(providers={"openai": FakeProvider("refund")}, sink=sink, capture_content=True)

    env = Environment(name="support-triage", version="0.1.0", system_prompt="Triage tickets.")

    @env.action
    def lookup_order(order_id: str) -> dict[str, str]:
        """Look up an order."""
        return {"order_id": order_id, "status": "shipped"}

    @env.scorer(weight=1.0)
    def mentions_refund(rollout: Any) -> float:
        text = rollout.response.text or ""
        return 1.0 if "refund" in text.lower() else 0.0

    @env.tasks
    def tasks() -> list[TaskData]:
        return [TaskData(task_id="t1", input="I want a refund for order 1")]

    rollout = env.rollout(next(env.iter_tasks()), client, model="openai/gpt-4o-mini")
    assert rollout.trace.outcome is not None
    assert rollout.trace.outcome.reward == 1.0

    report = Benchmark(env, models=["openai/gpt-4o-mini"], client=client, concurrency=1).run()
    assert report.models["openai/gpt-4o-mini"].mean_reward == 1.0
    assert "openai/gpt-4o-mini" in report.to_markdown()

    ds = Dataset.from_traces("support", [rollout.trace])
    assert len(ds) == 1
    ds.save(tmp_path / "ds.jsonl")
    loaded = Dataset.load(tmp_path / "ds.jsonl")
    assert loaded.content_hash == ds.content_hash
    client.close()


def test_dataset_from_sink(tmp_path: Path) -> None:
    from plural.tracing import JSONLSink

    sink = JSONLSink(tmp_path / "t.jsonl")
    sink.write(Trace(trace_id="1", environment="a"))
    sink.write(Trace(trace_id="2", environment="b"))
    sink.close()
    ds = Dataset.from_sink(tmp_path / "t.jsonl", "prod", where=lambda t: t.environment == "a")
    assert len(ds) == 1


def test_standalone_and_episode_trace_persistence(tmp_path: Path) -> None:
    from plural.tracing import JSONLSink

    sink = JSONLSink(tmp_path / "traces.jsonl")
    client = Client(providers={"openai": FakeProvider("done")}, sink=sink, capture_content=True)

    standalone = client.chat(model="openai/model", messages=[{"role": "user", "content": "hi"}])
    client.flush()
    first = sink.read_all()
    assert len(first) == 1
    assert first[0].trace_kind == "production"
    assert standalone.raw is not None
    assert standalone.raw["plural_trace_id"] == first[0].trace_id

    env = Environment(name="safe", version="1.0.0")
    rollout = env.rollout(
        TaskData(task_id="t", input="secret", expected="label"),
        client,
        model="openai/gpt-4o-mini",
    )
    client.flush()
    traces = sink.read_all()
    episode = traces[-1]
    assert len(traces) == 2
    assert episode.trace_id == rollout.trace.trace_id
    assert episode.trace_kind == "episode"
    assert episode.episode_trace_id == episode.trace_id
    assert episode.metadata["task"] == {
        "task_id": "t",
        "input": "secret",
        "metadata": {},
    }
    assert "expected" not in episode.metadata["task"]
    assert episode.initial_state is None
    assert episode.final_state is None
    assert rollout.response is not None and rollout.response.raw is not None
    assert rollout.response.raw["plural_trace_id"] == episode.trace_id
    client.close()


def test_text_only_episode_persistence_redacts_all_copied_content(tmp_path: Path) -> None:
    from plural.tracing import JSONLSink

    sink = JSONLSink(tmp_path / "redacted.jsonl")
    client = Client(providers={"openai": FakeProvider("private answer")}, sink=sink)
    env = Environment(name="redacted", version="1.0.0")

    env.rollout(
        TaskData(task_id="private", input="private prompt"),
        client,
        model="openai/model",
    )
    client.flush()
    persisted = sink.read_all()

    assert len(persisted) == 1
    trace = persisted[0]
    assert trace.initial_state is None
    assert trace.final_state is None
    assert trace.turns()[0].parsed_action[0].arguments["text"] is None
    assert trace.metadata["redaction"] == {"drop_content": True}
    serialized = trace.model_dump_json()
    assert "private answer" not in serialized
    assert "private prompt" not in serialized
    client.close()


def test_rollout_child_traces_are_opt_in_and_linked(tmp_path: Path) -> None:
    from plural.tracing import JSONLSink

    sink = JSONLSink(tmp_path / "traces.jsonl")
    client = Client(providers={"openai": FakeProvider("done")}, sink=sink, capture_content=True)
    env = Environment(name="linked", version="1.0.0")
    rollout = env.rollout(
        TaskData(task_id="t", input="go"),
        client,
        model="openai/gpt-4o-mini",
        record_llm_traces=True,
    )
    client.flush()
    traces = sink.read_all()
    assert len(traces) == 2
    child = next(trace for trace in traces if trace.trace_kind == "llm_call")
    episode = next(trace for trace in traces if trace.trace_kind == "episode")
    assert episode.trace_id == rollout.trace.trace_id
    assert child.parent_trace_id == episode.trace_id
    assert child.episode_trace_id == episode.trace_id
    assert episode.turns()[0].turn == 0
    client.close()


def test_write_trace_false_uses_episode_trace_id(tmp_path: Path) -> None:
    from plural.tracing import JSONLSink

    sink = JSONLSink(tmp_path / "traces.jsonl")
    client = Client(providers={"openai": FakeProvider()}, sink=sink)
    context = TraceContext(parent_trace_id="parent", episode_trace_id="episode")
    response = client.chat(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        write_trace=False,
        trace_context=context,
    )
    client.flush()
    assert sink.read_all() == []
    assert response.raw is not None
    assert response.raw["plural_trace_id"] == "episode"
    client.close()


@pytest.mark.asyncio
async def test_achat_trace_controls(tmp_path: Path) -> None:
    from plural.tracing import JSONLSink

    sink = JSONLSink(tmp_path / "traces.jsonl")
    client = Client(providers={"openai": FakeProvider()}, sink=sink)
    response = await client.achat(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        write_trace=False,
        trace_context=TraceContext(parent_trace_id="episode", episode_trace_id="episode"),
    )
    client.flush()
    assert sink.read_all() == []
    assert response.raw is not None
    assert response.raw["plural_trace_id"] == "episode"
    await client.aclose()


def test_dataset_hash_filter_and_corruption_detection(tmp_path: Path) -> None:
    first = Trace(trace_id="1", trace_kind="episode", environment="a", model="m")
    first.add_turn(observation="before")
    second = first.model_copy(deep=True)
    second.steps[0].observation = "after"
    assert (
        Dataset.from_traces("a", [first]).content_hash
        != Dataset.from_traces("b", [second]).content_hash
    )

    sink_path = tmp_path / "source.jsonl"
    sink_path.write_text(
        "\n".join(
            [
                first.model_dump_json(),
                Trace(trace_id="2", trace_kind="production", environment="b").model_dump_json(),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    filtered = Dataset.from_sink(
        sink_path,
        "episodes",
        filter=TraceFilter(trace_kind="episode", environment="a", model="m"),
    )
    assert [trace.trace_id for trace in filtered.traces] == ["1"]

    dataset_path = tmp_path / "dataset.jsonl"
    filtered.save(dataset_path)
    manifest = json.loads(
        dataset_path.with_suffix(".jsonl.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["hash_algorithm"] == "sha256"
    dataset_path.write_text(
        dataset_path.read_text(encoding="utf-8").replace('"before"', '"tampered"'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="content hash mismatch"):
        Dataset.load(dataset_path)


def test_dataset_loads_legacy_manifest(tmp_path: Path) -> None:
    trace = Trace(trace_id="legacy", environment="old")
    dataset_path = tmp_path / "legacy.jsonl"
    dataset_path.write_text(trace.model_dump_json() + "\n", encoding="utf-8")
    legacy_payload = {
        "trace_id": trace.trace_id,
        "outcome": None,
        "task_id": None,
        "environment": "old",
    }
    legacy_hash = hashlib.sha256(
        json.dumps(legacy_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    dataset_path.with_suffix(".jsonl.manifest.json").write_text(
        json.dumps(
            {
                "name": "legacy",
                "version": "0.1.0",
                "content_hash": legacy_hash,
                "count": 1,
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    loaded = Dataset.load(dataset_path)
    assert loaded.content_hash == legacy_hash


def test_legacy_jsonl_traces_are_rejected() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures/legacy_traces_v0_4.jsonl"
    with pytest.raises(Exception):
        Dataset.from_sink(fixture, "legacy")


def test_plural_is_client_alias() -> None:
    assert Plural is Client


def test_is_authenticated_in_process_provider(tmp_path: Path) -> None:
    client = Client(
        providers={"openai": FakeProvider()},
        sink=JSONLSink(tmp_path / "traces.jsonl"),
    )
    assert client.is_authenticated() is True
    client.close()


@respx.mock
def test_is_authenticated_accepts_valid_credentials(tmp_path: Path) -> None:
    respx.get("https://api.example.test/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = Client(
        providers={
            "custom": OpenAICompatible(
                api_key="sk-test",
                base_url="https://api.example.test/v1",
                name="custom",
            )
        },
        sink=JSONLSink(tmp_path / "traces.jsonl"),
    )
    assert client.is_authenticated() is True
    client.close()


@respx.mock
def test_is_authenticated_rejects_unauthorized(tmp_path: Path) -> None:
    respx.get("https://api.example.test/v1/models").mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid api key"}})
    )
    client = Client(
        providers={
            "custom": OpenAICompatible(
                api_key="sk-bad",
                base_url="https://api.example.test/v1",
                name="custom",
            )
        },
        sink=JSONLSink(tmp_path / "traces.jsonl"),
    )
    assert client.is_authenticated() is False
    client.close()


@respx.mock
def test_is_authenticated_rejects_forbidden(tmp_path: Path) -> None:
    respx.get("https://api.example.test/v1/models").mock(return_value=httpx.Response(403))
    client = Client(
        providers={
            "custom": OpenAICompatible(
                api_key="sk-bad",
                base_url="https://api.example.test/v1",
                name="custom",
            )
        },
        sink=JSONLSink(tmp_path / "traces.jsonl"),
    )
    assert client.is_authenticated() is False
    client.close()
