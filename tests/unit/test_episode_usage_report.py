"""Usage normalization, episode recording, and their mapping to hosted events."""

from __future__ import annotations

import json
from pathlib import Path

from plural.execution.report import agent_usage, episode_events
from plural.harness.episode import EPISODE_SCHEMA, EpisodeRecorder
from plural.usage import TokenUsage, UsageTotals, normalize_usage


def test_openai_usage_keeps_cached_tokens_inside_input() -> None:
    usage = normalize_usage(
        {
            "prompt_tokens": 1200,
            "completion_tokens": 80,
            "prompt_tokens_details": {"cached_tokens": 1000},
            "completion_tokens_details": {"reasoning_tokens": 30},
            "cost": 0.004,
        }
    )
    assert usage == TokenUsage(
        input_tokens=1200,
        output_tokens=80,
        cached_input_tokens=1000,
        reasoning_tokens=30,
        cost_usd=0.004,
    )


def test_anthropic_cache_reads_fold_into_input_without_double_counting() -> None:
    usage = normalize_usage(
        {
            "input_tokens": 50,
            "cache_read_input_tokens": 900,
            "cache_creation_input_tokens": 100,
            "output_tokens": 40,
        }
    )
    assert usage.input_tokens == 1050
    assert usage.cached_input_tokens == 900
    assert usage.cost_usd is None


def test_unreported_usage_stays_unknown_and_totals_count_the_gaps() -> None:
    assert normalize_usage(None) == TokenUsage()
    assert not normalize_usage({"prompt_tokens": "many"}).reported
    totals = (
        UsageTotals()
        .add(TokenUsage(input_tokens=10, output_tokens=2, cost_usd=0.01))
        .add(TokenUsage())
    )
    assert totals.calls == 2
    assert totals.input_tokens == 10
    assert totals.cost_usd == 0.01
    assert totals.calls_missing_tokens == 1
    assert totals.calls_missing_cost == 1
    assert not totals.complete


def _recorded(tmp_path: Path) -> list[dict]:
    recorder = EpisodeRecorder(tmp_path / "episode.jsonl")
    recorder.reset(recorder.start(), observation="Guess a word", view={"kind": "marks-grid"})
    first = [{"role": "user", "content": "Guess a word"}]
    recorder.model_call(
        recorder.start(),
        model="openai/gpt-5.6-luna",
        messages=first,
        tools=[{"function": {"name": "guess"}}],
        text="crane",
        usage=TokenUsage(input_tokens=12, output_tokens=3, cost_usd=0.001),
    )
    recorder.step(
        recorder.start(),
        action="guess",
        arguments={"word": "crane"},
        observation="C_A__",
        reward=0.2,
        view={"kind": "marks-grid", "rows": []},
    )
    recorder.model_call(
        recorder.start(),
        model="openai/gpt-5.6-luna",
        messages=[*first, {"role": "tool", "content": "C_A__"}],
        tools=None,
        text="done",
    )
    return [json.loads(line) for line in (tmp_path / "episode.jsonl").read_text().splitlines()]


def test_episode_records_turns_and_only_new_messages(tmp_path: Path) -> None:
    records = _recorded(tmp_path)
    assert [record["kind"] for record in records] == [
        "environment.reset",
        "model.call",
        "environment.step",
        "model.call",
    ]
    assert {record["schema"] for record in records} == {EPISODE_SCHEMA}
    assert [record["sequence"] for record in records] == [1, 2, 3, 4]
    assert [record["turn"] for record in records] == [None, 1, 1, 2]
    assert records[1]["tools"] == ["guess"]
    assert records[3]["messages_offset"] == 1
    assert records[3]["messages"] == [{"role": "tool", "content": "C_A__"}]
    assert records[3]["usage"]["input_tokens"] is None


def test_episode_events_link_steps_to_the_call_that_opened_their_turn(
    tmp_path: Path,
) -> None:
    records = _recorded(tmp_path)
    events = episode_events(records, stream_id="trial-1", execution_id="exec-1")
    assert [event["kind"] for event in events] == [
        "observation",
        "model_call",
        "action",
        "model_call",
    ]
    assert [event["ingest_key"] for event in events] == [
        f"exec-1:episode:{n}" for n in (1, 2, 3, 4)
    ]
    step = events[2]
    assert step["parent_key"] == "exec-1:episode:2"
    assert step["component"] == "environment"
    assert step["payload"]["observation"] == "C_A__"
    assert "schema" not in step["payload"]

    usage = agent_usage(records)
    assert usage is not None
    assert usage["calls"] == 2
    assert usage["input_tokens"] == 12
    assert usage["calls_missing_cost"] == 1
    assert agent_usage(records[:1]) is None
