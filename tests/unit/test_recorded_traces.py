from __future__ import annotations

import json
from pathlib import Path

import pytest

from plural.recorded import read_traces, recordings_by_app

REFUND = [
    {"role": "system", "content": "You are a support agent."},
    {"role": "user", "content": "Refund order 7."},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "get_order", "arguments": '{"id": 7}'},
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "cost": 0.001},
    },
    {"role": "tool", "tool_call_id": "c1", "content": '{"id": 7, "status": "paid"}'},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c2",
                "type": "function",
                "function": {"name": "refund", "arguments": '{"id": 7}'},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "c2", "content": '{"refunded": true}'},
    {"role": "assistant", "content": "Order 7 is refunded."},
]


def test_read_traces_accepts_chat_logs_and_plural_traces() -> None:
    trace = {
        "trace_id": "t1",
        "model": "acme/support",
        "steps": [
            {
                "type": "llm",
                "model": "acme/support",
                "request": {"messages": REFUND[:2]},
                "response": {"choices": [{"message": REFUND[2]}]},
            }
        ],
    }

    chat, plural = read_traces([{"messages": REFUND}, trace])

    assert chat.trace_id.startswith("trace-")
    assert read_traces([{"messages": REFUND}])[0].trace_id == chat.trace_id
    assert chat.instructions == "Refund order 7."
    assert [call["action"] for call in chat.tool_calls] == ["get_order", "refund"]
    assert plural.messages[-1]["tool_calls"][0]["id"] == "c1"
    with pytest.raises(ValueError, match="has no conversation"):
        read_traces([{"trace_id": "t2", "steps": []}])


def test_recorded_calls_group_by_the_app_their_names_carry() -> None:
    [trace] = read_traces(
        [
            {
                "messages": [
                    {"role": "user", "content": "Close ticket 3."},
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {"id": "a", "function": {"name": "crm__get", "arguments": "{}"}},
                            {"id": "b", "function": {"name": "search", "arguments": "{}"}},
                        ],
                    },
                    {"role": "tool", "tool_call_id": "a", "content": '{"id": 3}'},
                    {"role": "tool", "tool_call_id": "b", "content": "[]"},
                ]
            }
        ]
    )

    grouped = recordings_by_app([trace], default_app="tools")

    origin = trace.trace_id
    assert grouped == {
        "crm": [{"action": "get", "arguments": {}, "result": {"id": 3}, "trace_id": origin}],
        "tools": [{"action": "search", "arguments": {}, "result": [], "trace_id": origin}],
    }


def test_a_file_may_hold_pretty_printed_traces_and_the_tools_offered(tmp_path: Path) -> None:
    offered = [
        {
            "type": "function",
            "function": {
                "name": "get_order",
                "description": "Look up an order.",
                "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
        },
        {"name": "refund", "description": "Refund an order.", "input_schema": {"type": "object"}},
    ]
    one = {"id": "a", "messages": REFUND, "tools": offered}
    two = {"id": "b", "messages": REFUND}
    pretty = tmp_path / "traces.jsonl"
    pretty.write_text(json.dumps(one, indent=2) + "\n" + json.dumps(two, indent=2) + "\n")
    array = tmp_path / "traces.json"
    array.write_text(json.dumps([one, two], indent=2))

    for path in (pretty, array):
        first, second = read_traces(path)
        assert [first.trace_id, second.trace_id] == ["a", "b"]
        assert first.tools == (
            {
                "name": "get_order",
                "description": "Look up an order.",
                "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
            {"name": "refund", "description": "Refund an order.", "parameters": {"type": "object"}},
        )
    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"messages": []}\n{"messages": [\n')
    with pytest.raises(ValueError, match="starting on line 2 is not valid JSON"):
        read_traces(broken)
