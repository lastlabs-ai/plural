"""ATIF export: which tool calls the model made, and which steps a Harness tool ran."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plural.atif import episode_to_atif, validate_atif
from plural.harness.episode import EpisodeRecorder
from plural.harness.interface import HarnessEnvironment, HarnessStep
from plural.harness.tools import tool


def _call(sequence: int, turn: int, *calls: tuple[str, str], messages=()) -> dict[str, Any]:
    return {
        "kind": "model.call",
        "sequence": sequence,
        "turn": turn,
        "messages": list(messages),
        "messages_offset": 0 if sequence == 1 else 100,
        "message_count": 100 if sequence == 1 else 200,
        "tool_calls": [
            {"id": call_id, "function": {"name": name, "arguments": "{}"}}
            for call_id, name in calls
        ],
    }


def _step(sequence: int, turn: int, action: str, tool_run: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "kind": "environment.step",
        "sequence": sequence,
        "event_id": f"e{sequence}",
        "turn": turn,
        "action": action,
        "arguments": {"n": sequence},
        "observation": {"from": action},
    }
    if tool_run:
        record.update(harness_tool="find_options", harness_tool_id=tool_run)
    return record


def _tool(sequence: int, turn: int, name: str, tool_run: str) -> dict[str, Any]:
    return {
        "kind": "harness.tool",
        "sequence": sequence,
        "event_id": f"e{sequence}",
        "turn": turn,
        "action": name,
        "harness_tool_id": tool_run,
        "arguments": {},
        "observation": {"best": "CRW"},
    }


def _calls(step: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["function_name"]: item for item in step["tool_calls"]}


def test_a_harness_tools_steps_are_nested_in_the_call_as_atif_tool_calls() -> None:
    records = [
        _call(1, 1, ("c1", "find_options"), ("c2", "get_stock")),
        _step(2, 1, "get_stock", tool_run="t1"),
        _step(3, 1, "get_freight_quote", tool_run="t1"),
        _tool(4, 1, "find_options", "t1"),
        _step(5, 1, "get_stock"),
    ]

    document = episode_to_atif(records, agent_name="agent")

    assert validate_atif(document) == []
    step = document["steps"][0]
    calls = _calls(step)
    nested = calls["find_options"]["extra"]
    assert nested["harness_tool"] is True
    assert nested["tool_calls"] == [
        {"tool_call_id": "e2", "function_name": "get_stock", "arguments": {"n": 2}},
        {"tool_call_id": "e3", "function_name": "get_freight_quote", "arguments": {"n": 3}},
    ]
    assert [item["source_call_id"] for item in nested["observation"]["results"]] == ["e2", "e3"]
    assert nested["observation"]["results"][0]["content"] == '{"from": "get_stock"}'
    # The tool's own get_stock is not mistaken for the model's.
    assert "extra" not in calls["get_stock"]
    assert step["observation"]["results"] == [
        {"content": '{"best": "CRW"}', "source_call_id": "c1", "extra": {"action": "find_options"}},
        {
            "content": '{"from": "get_stock"}',
            "source_call_id": "c2",
            "extra": {"action": "get_stock"},
        },
    ]


def test_a_tool_that_wraps_an_action_nests_the_real_action() -> None:
    records = [
        _call(1, 1, ("c1", "submit")),
        _step(2, 1, "get_customer", tool_run="t1"),
        _step(3, 1, "submit", tool_run="t1"),
        _tool(4, 1, "submit", "t1"),
    ]

    step = episode_to_atif(records, agent_name="agent")["steps"][0]

    nested = step["tool_calls"][0]["extra"]
    assert [item["function_name"] for item in nested["tool_calls"]] == ["get_customer", "submit"]
    assert [item["source_call_id"] for item in step["observation"]["results"]] == ["c1"]


def test_steps_recorded_before_harness_tools_are_nested_only_when_one_call_is_open() -> None:
    records = [
        _call(1, 1, ("c1", "find_options")),
        _step(2, 1, "get_stock"),
        _call(
            3,
            2,
            ("c2", "find_options"),
            ("c3", "find_options"),
            messages=[{"role": "tool", "tool_call_id": "c1", "content": '{"best": "CRW"}'}],
        ),
        _step(4, 2, "get_customer"),
    ]

    document = episode_to_atif(records, agent_name="agent")

    first, second = document["steps"][0], document["steps"][1]
    inferred = first["tool_calls"][0]["extra"]
    assert inferred["harness_tool"] is True and inferred["inferred"] is True
    assert [item["function_name"] for item in inferred["tool_calls"]] == ["get_stock"]
    # The Harness's answer is recovered from the next call's messages.
    assert first["observation"]["results"] == [
        {"content": '{"best": "CRW"}', "source_call_id": "c1", "extra": {"action": "find_options"}}
    ]
    assert [item["function_name"] for item in second["extra"]["unlinked"]["tool_calls"]] == [
        "get_customer"
    ]


class _Sourcing:
    @tool
    def find_options(self, environment, material: str, tons: float = 1.0) -> dict:
        """Every way to fill one line."""
        environment.step("get_stock", material=material)
        return {"best": "CRW", "tons": tons}

    @tool(wraps="submit")
    def check_then_submit(self, environment, **quote: Any) -> Any:
        if not quote.get("lines"):
            return {"error": "no lines"}
        return environment.step("submit", **quote)


def _environment(tmp_path: Path, monkeypatch, harness: object) -> HarnessEnvironment:
    environment = HarnessEnvironment(
        {
            "actions": [
                {"name": "get_stock", "command": ["true"], "description": "Stock."},
                {"name": "submit", "command": ["true"], "description": "Submit a quote."},
            ]
        },
        recorder=EpisodeRecorder(tmp_path / "episode.jsonl"),
        harness=harness,
    )
    monkeypatch.setattr(
        environment,
        "_exec",
        lambda *_, **__: (HarnessStep(observation={"ok": True}, terminated=True), None, []),
    )
    return environment


def test_harness_tools_are_offered_like_actions(tmp_path: Path, monkeypatch) -> None:
    environment = _environment(tmp_path, monkeypatch, _Sourcing())

    tools = {item["function"]["name"]: item["function"] for item in environment.tools()}

    assert list(tools) == ["get_stock", "submit", "find_options"]
    assert tools["submit"]["description"] == "Submit a quote."
    assert tools["find_options"] == {
        "name": "find_options",
        "description": "Every way to fill one line.",
        "parameters": {
            "type": "object",
            "properties": {
                "material": {"type": "string"},
                "tons": {"type": "number"},
            },
            "required": ["material"],
        },
    }


def test_a_tools_steps_are_recorded_inside_it(tmp_path: Path, monkeypatch) -> None:
    environment = _environment(tmp_path, monkeypatch, _Sourcing())

    found = environment.step("find_options", material="A36")
    refused = environment.step("submit", lines=[])
    submitted = environment.step("submit", lines=[1])

    assert found.observation == {"best": "CRW", "tons": 1.0}
    assert refused.observation == {"error": "no lines"}
    assert submitted.observation == {"ok": True} and submitted.terminated
    records = [json.loads(line) for line in (tmp_path / "episode.jsonl").read_text().splitlines()]
    assert [
        (item["kind"], item["action"], item.get("harness_tool"), item.get("harness_tool_id"))
        for item in records
    ] == [
        ("environment.step", "get_stock", "find_options", "t1"),
        ("harness.tool", "find_options", None, "t1"),
        ("harness.tool", "submit", None, "t2"),
        ("environment.step", "submit", "submit", "t3"),
        ("harness.tool", "submit", None, "t3"),
    ]
    # A tool and the steps it runs are one turn.
    assert {item["turn"] for item in records[:2]} == {1}


def test_a_tool_may_not_take_an_actions_name_without_wrapping_it() -> None:
    class Clash:
        @tool
        def get_stock(self, environment) -> None:
            """Shadows an action."""

    with pytest.raises(ValueError, match="wraps="):
        HarnessEnvironment({"actions": [{"name": "get_stock"}]}, harness=Clash())

    class Missing:
        @tool(wraps="nope")
        def anything(self, environment) -> None:
            """Wraps nothing."""

    with pytest.raises(ValueError, match="wraps no Environment action"):
        HarnessEnvironment({"actions": [{"name": "get_stock"}]}, harness=Missing())


def test_the_host_merge_keeps_which_tool_run_a_step_belongs_to() -> None:
    from plural.execution.steps import merge_host_steps

    recorded = {**_step(1, 1, "get_stock", tool_run="t1"), "info": {"step": 1}}
    host = {"step": 1, "action": "get_stock", "harness_tool": "find_options", "info": {"step": 1}}

    (merged,) = merge_host_steps([recorded], [host])

    assert merged["harness_tool"] == "find_options"
    assert merged["harness_tool_id"] == "t1"


def test_the_chat_transcript_ends_with_only_what_answered_the_last_calls() -> None:
    from plural.transcript import episode_to_messages

    records = [
        _call(1, 1, ("c1", "find_options"), ("c2", "submit")),
        _step(2, 1, "get_stock", tool_run="t1"),
        _tool(3, 1, "find_options", "t1"),
        _step(4, 1, "get_customer"),
        _step(5, 1, "submit"),
    ]

    tools = [item for item in episode_to_messages(records)["messages"] if item["role"] == "tool"]

    assert [(item["tool_call_id"], item["name"]) for item in tools] == [
        ("c1", "find_options"),
        ("c2", "submit"),
    ]
    assert tools[0]["content"] == '{"best": "CRW"}'
