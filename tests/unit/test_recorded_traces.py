from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plural import (
    DeterministicVerifier,
    Episode,
    HindsightTrial,
    Job,
    RewardTarget,
    VerifierOutput,
    hindsight_rewarder,
)
from plural.execution.store import JobStore
from plural.recorded import read_traces, recordings_by_app
from plural.rewards import LEDGER_FILE, read_ledger, training_export

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
CUT_OFF = [
    {"role": "user", "content": "Refund order 8."},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "get_order", "arguments": '{"id": 8}'},
            }
        ],
    },
]


def refunded(episode: Episode) -> VerifierOutput:
    steps = [item for item in episode.trajectory if item.get("kind") == "environment.step"]
    done = any(step["action"] == "refund" and step["observation"] for step in steps)
    return VerifierOutput(score=1.0 if done else 0.0)


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "traces.jsonl"
    path.write_text(
        json.dumps({"id": "ticket/7", "model": "acme/support", "messages": REFUND})
        + "\n"
        + json.dumps({"id": "ticket/8", "model": "acme/support", "messages": CUT_OFF})
        + "\n"
    )
    return path


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

    assert chat.trace_id == "trace-1"
    assert chat.instructions == "Refund order 7."
    assert [call["action"] for call in chat.tool_calls] == ["get_order", "refund"]
    assert plural.messages[-1]["tool_calls"][0]["id"] == "c1"
    with pytest.raises(ValueError, match="has no conversation"):
        read_traces([{"trace_id": "t2", "steps": []}])


def test_from_traces_scores_recorded_conversations_without_a_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    @hindsight_rewarder
    def lookup_first(trial: HindsightTrial) -> Any:
        steps = trial.steps()
        if steps and steps[0]["action"] == "get_order":
            yield trial.credit(RewardTarget.event(steps[0]["event_id"]), 0.5)

    store = JobStore(tmp_path / "jobs")
    job = Job.from_traces(
        _write(tmp_path),
        verifiers=[DeterministicVerifier(name="refunded", check=refunded)],
        name="support-tickets",
        hindsight=[lookup_first],
        store=store,
    )
    result = job.run()

    assert [task.name for task in job.source.tasks] == ["ticket-7", "ticket-8"]
    assert job.agents[0].model == "acme/support"
    by_task = {trial.receipt.task_pin.name: trial for trial in result.trials}
    assert by_task["ticket-7"].score == 1.0
    assert by_task["ticket-8"].score == 0.0
    plan = {trial.task_pin.name: trial for trial in job.plan.trials}
    artifacts = store.trial_path(plan["ticket-7"]) / "executions/0/artifacts"
    events = [json.loads(line) for line in (artifacts / "episode.jsonl").read_text().splitlines()]
    assert [item["kind"] for item in events] == [
        "environment.reset",
        "model.call",
        "environment.step",
        "model.call",
        "environment.step",
        "model.call",
    ]
    assert events[1]["usage"]["cost_usd"] == 0.001
    ledger = read_ledger(artifacts / LEDGER_FILE)
    assert [(item.rewarder, item.target.event_id) for item in ledger] == [("lookup_first", "e3")]
    exported = training_export(events, ledger)
    assert [turn["reward"] for turn in exported["turns"]] == [0.5, 0.0, 0.0]

    cut = store.trial_path(plan["ticket-8"]) / "executions/0/artifacts"
    final = [json.loads(line) for line in (cut / "episode.jsonl").read_text().splitlines()]
    assert final[-1]["error"] == "the recording has no result for this call"
    assert json.loads((cut / "result.json").read_text())["stop_reason"] == "recording_ended"


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

    assert grouped == {
        "crm": [{"action": "get", "arguments": {}, "result": {"id": 3}}],
        "tools": [{"action": "search", "arguments": {}, "result": []}],
    }
