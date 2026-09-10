from pathlib import Path

from plural.tracing import (
    JSONLSink,
    ParsedAction,
    Redactor,
    Sampler,
    SQLiteSink,
    Trace,
    TraceWriter,
)
from plural.tracing.schema import Outcome


def test_jsonl_sink(tmp_path: Path) -> None:
    sink = JSONLSink(tmp_path / "t.jsonl")
    sink.write(Trace(trace_id="a"))
    sink.write(Trace(trace_id="b"))
    sink.close()
    traces = JSONLSink(tmp_path / "t.jsonl").read_all()
    assert [t.trace_id for t in traces] == ["a", "b"]


def test_sqlite_sink_and_label(tmp_path: Path) -> None:
    sink = SQLiteSink(tmp_path / "t.sqlite")
    writer = TraceWriter(sink)
    writer.record(Trace(trace_id="x"))
    writer.flush()
    writer.label("x", reward=1.0, scores={"ok": 1.0})
    writer.close()
    loaded = SQLiteSink(tmp_path / "t.sqlite").get("x")
    assert loaded is not None
    assert loaded.outcome is not None
    assert loaded.outcome.reward == 1.0


def test_redactor_fields() -> None:
    redactor = Redactor(fields={"metadata.email"})
    trace = Trace(trace_id="t", metadata={"email": "a@b.com", "ok": 1})
    out = redactor.apply(trace)
    assert out.metadata["email"] == "[REDACTED]"
    assert out.metadata["ok"] == 1


def test_redactor_never_replaces_dict_typed_state_with_a_string() -> None:
    trace = Trace(initial_state={"secret": "before"}, final_state={"secret": "after"})
    out = Redactor(fields={"initial_state", "final_state"}).apply(trace)

    assert out.initial_state is None
    assert out.final_state is None
    assert out.metadata["redacted_fields"] == ["final_state", "initial_state"]
    assert Trace.model_validate_json(out.model_dump_json()) == out


def test_sampler_always_tags() -> None:
    sampler = Sampler(rate=0.0, always_tags={"keep"})
    assert sampler.accept(Trace(trace_id="t", tags={"keep": "1"}))
    assert not sampler.accept(Trace(trace_id="t2"))


def test_trace_label_helper() -> None:
    t = Trace(trace_id="t")
    t.label(scores={"a": 1.0}, reward=1.0)
    assert t.outcome == Outcome(scores={"a": 1.0}, reward=1.0, labels={}, feedback=None)


def test_drop_content_redacts_task_and_state_without_dropping_keys() -> None:
    trace = Trace(
        initial_state={"secret": "before"},
        final_state={"secret": "after"},
        metadata={"task": {"task_id": "t", "input": "private", "metadata": {}}},
    )
    trace.add_turn(
        observation="private observation",
        parsed_action=[ParsedAction(name="respond", arguments={"text": "private answer"})],
    )
    redacted = Redactor(drop_content=True).apply(trace)
    assert "input" in redacted.metadata["task"]
    assert redacted.metadata["task"]["input"] is None
    assert "initial_state" in redacted.model_fields_set
    assert "final_state" in redacted.model_fields_set
    assert redacted.initial_state is None
    assert redacted.final_state is None
    assert redacted.turns()[0].observation is None
    assert redacted.turns()[0].parsed_action[0].arguments["text"] is None
    assert redacted.metadata["redaction"] == {"drop_content": True}
    assert "initial_state" in redacted.metadata["redacted_fields"]
    assert Trace.model_validate_json(redacted.model_dump_json()) == redacted
