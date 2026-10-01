"""The episode contract: who ends an episode, and where reward is recorded."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plural.environments.runner import PROTOCOL
from plural.harness import native_runner
from plural.harness.protocol import HarnessRunRequest


def _request(tmp_path: Path, **limits: object) -> dict[str, object]:
    request = HarnessRunRequest(
        request_id="test",
        task={"task_id": "one", "input": "hello", "metadata": {}},
        agent={"name": "agent", "model": "test/model", "routing": {}},
        environment={
            "name": "test",
            "instructions": "Solve the task.",
            "actions": [],
            "limits": {"max_turns": 4, "max_seconds": 10, **limits},
            "guardrails": [],
            "workspace": str(tmp_path),
        },
    ).model_dump(mode="json")
    request["environment"]["workspace"] = str(tmp_path)
    request["environment"]["limits"] = {"max_turns": 4, "max_seconds": 10, **limits}
    return request


def _action(tmp_path: Path, body: str, *, name: str = "act") -> dict[str, object]:
    """Write an action command that emits a step envelope."""
    script = tmp_path / f"{name}.py"
    script.write_text(body, encoding="utf-8")
    return {
        "name": name,
        "description": f"Run {name}",
        "command": ["python", str(script)],
        "parameters": {"type": "object"},
        "timeout_seconds": 5,
    }


def _emitter(payload: dict[str, object], *, read_stdin: bool = True) -> str:
    """Return a script that prints one fixed envelope."""
    prelude = "import sys\nsys.stdin.read()\n" if read_stdin else ""
    return f"{prelude}print({json.dumps(payload)!r})\n"


def _envelope(**fields: object) -> str:
    return _emitter(
        {
            "protocol": PROTOCOL,
            "kind": "step",
            "observation": {"text": "ok"},
            "reward": 0.0,
            "terminated": False,
            "truncated": False,
            "info": {},
            **fields,
        }
    )


def _call(name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call-{name}",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments or {}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"cost_usd": 0.0},
    }


def _text(content: str) -> dict[str, object]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"cost_usd": 0.0},
    }


def _responses(monkeypatch: pytest.MonkeyPatch, *responses: dict[str, object]) -> list[int]:
    """Serve canned model responses and count how many the loop consumed."""
    calls = iter(responses)
    consumed: list[int] = []

    def model_call(**_kwargs: object) -> dict[str, object]:
        consumed.append(1)
        return next(calls)

    monkeypatch.setattr(native_runner, "_model_call", model_call)
    return consumed


def test_step_protocol_matches_everywhere_it_is_duplicated() -> None:
    # These modules run as standalone scripts and cannot import the package.
    from plural.harness import mcp_bridge

    assert native_runner.STEP_PROTOCOL == PROTOCOL
    assert mcp_bridge.STEP_PROTOCOL == PROTOCOL


def test_stop_reason_vocabulary_is_declared_once() -> None:
    import typing

    from plural.verifiers import STOP_REASONS, EpisodeOutcome

    declared = typing.get_args(EpisodeOutcome.model_fields["stop_reason"].annotation)
    assert set(declared) == {*STOP_REASONS, ""}
    # Every reason the native loop can emit must be part of the vocabulary.
    assert set(STOP_REASONS) >= native_runner._BUDGET_STOPS


def test_mcp_bridge_hides_reward_from_the_agent(tmp_path: Path) -> None:
    from plural.harness import mcp_bridge

    script = tmp_path / "act.py"
    script.write_text(
        _emitter(
            {
                "protocol": PROTOCOL,
                "kind": "step",
                "observation": {"text": "closer"},
                "reward": 0.9,
                "terminated": False,
                "truncated": False,
                "info": {"rewards": [{"name": "progress", "value": 0.9, "weight": 1.0}]},
            }
        ),
        encoding="utf-8",
    )
    environment = {
        "workspace": str(tmp_path),
        "actions": [{"name": "act", "command": ["python", str(script)]}],
    }

    visible = mcp_bridge._call_action(environment, "act", {})

    assert visible == {"text": "closer"}


def test_environment_termination_ends_the_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request["environment"]["actions"] = [
        _action(tmp_path, _envelope(terminated=True, observation={"text": "solved"}))
    ]
    # Two responses are offered; the Environment should stop the loop after one.
    consumed = _responses(monkeypatch, _call("act"), _text("never reached"))

    result, episode, _trace = native_runner._run("native.actions.v1", request)

    assert result["stop_reason"] == "environment_terminated"
    assert result["terminated"] is True
    assert len(consumed) == 1
    assert episode.transitions[-1]["terminated"] is True


def test_agent_can_finish_the_episode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(tmp_path)
    request["environment"]["actions"] = [_action(tmp_path, _envelope())]
    consumed = _responses(
        monkeypatch,
        _call("finish", {"summary": "I could not solve this."}),
        _text("never reached"),
    )

    result, episode, _trace = native_runner._run("native.actions.v1", request)

    assert result["stop_reason"] == "agent_finished"
    assert result["response"] == "I could not solve this."
    assert result["terminated"] is False
    assert len(consumed) == 1
    assert episode.transitions[-1]["type"] == "finish"


def test_exhausting_turns_truncates_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path, max_turns=2)
    request["environment"]["actions"] = [_action(tmp_path, _envelope())]
    _responses(monkeypatch, _call("act"), _call("act"))

    result, _episode, _trace = native_runner._run("native.actions.v1", request)

    assert result["stop_reason"] == "max_turns"
    assert result["truncated"] is True
    assert result["terminated"] is False


def test_reward_is_recorded_but_never_shown_to_the_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request["environment"]["actions"] = [
        _action(
            tmp_path,
            _envelope(
                reward=0.75,
                observation={"text": "closer"},
                info={"rewards": [{"name": "progress", "value": 0.75, "weight": 1.0}]},
            ),
        )
    ]
    _responses(monkeypatch, _call("act"), _text("done"))

    result, episode, _trace = native_runner._run("native.actions.v1", request)

    assert episode.rewards == [
        {
            "type": "reward",
            "turn": 1,
            "action": "act",
            "value": 0.75,
            "signals": [{"name": "progress", "value": 0.75, "weight": 1.0}],
        }
    ]
    assert result["total_reward"] == 0.75
    tool = next(item for item in episode.messages if item.get("role") == "tool")
    assert "closer" in tool["content"]
    assert "0.75" not in tool["content"]
    assert "reward" not in tool["content"]


def test_action_errors_reach_the_agent_and_the_episode_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request["environment"]["actions"] = [
        _action(tmp_path, _envelope(info={"error": "not in the dictionary"}))
    ]
    _responses(monkeypatch, _call("act"), _text("giving up"))

    result, episode, _trace = native_runner._run("native.actions.v1", request)

    tool = next(item for item in episode.messages if item.get("role") == "tool")
    assert "not in the dictionary" in tool["content"]
    assert result["stop_reason"] == "agent_response"


def test_trajectory_document_keeps_the_reset_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request["environment"]["actions"] = [_action(tmp_path, _envelope())]
    request["environment"]["reset_command"] = [
        "python",
        str(tmp_path / "reset.py"),
    ]
    (tmp_path / "reset.py").write_text(
        _emitter(
            {
                "protocol": PROTOCOL,
                "kind": "reset",
                "observation": {"text": "start here"},
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
                "info": {},
            },
            read_stdin=False,
        ),
        encoding="utf-8",
    )
    _responses(monkeypatch, _text("done"))

    _result, episode, _trace = native_runner._run("native.actions.v1", request)

    document = episode.document()
    assert document["transitions"][0] == {
        "type": "reset",
        "turn": 0,
        "observation": {"text": "start here"},
        "terminated": False,
        "truncated": False,
        "info": {},
    }
    # The opening observation reaches the Agent's first prompt.
    assert "start here" in document["messages"][1]["content"]


def test_the_agent_sees_rendered_text_not_the_observation_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request["task"]["instructions"] = "Guess the word."
    request["environment"]["actions"] = [
        _action(
            tmp_path,
            _envelope(
                observation={"text": "", "history": ["no"], "metadata": {}},
                rendered="1. no -> Is it alive?",
            ),
        )
    ]
    request["environment"]["reset_command"] = ["python", str(tmp_path / "reset.py")]
    (tmp_path / "reset.py").write_text(
        _emitter(
            {
                "protocol": PROTOCOL,
                "kind": "reset",
                "observation": {"text": "", "history": [], "metadata": {}},
                "rendered": "No questions yet.",
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
                "info": {},
            },
            read_stdin=False,
        ),
        encoding="utf-8",
    )
    _responses(monkeypatch, _call("act"), _text("done"))

    _result, episode, _trace = native_runner._run("native.actions.v1", request)

    assert episode.messages[1]["content"] == "Guess the word.\n\nNo questions yet."
    tool = next(item for item in episode.messages if item.get("role") == "tool")
    assert tool["content"] == "1. no -> Is it alive?"


def test_an_unrendered_observation_sends_only_its_populated_fields() -> None:
    assert native_runner._observation_text({"text": "", "left": 3, "metadata": {}}) == (
        '{"left": 3}'
    )
    assert native_runner._observation_text({"text": "board", "left": 3}) == "board"


def test_trajectory_reads_as_chat_turns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from plural.transcript import episode_to_messages

    request = _request(tmp_path)
    request["task"]["instructions"] = "Solve it."
    request["environment"]["actions"] = [
        _action(tmp_path, _envelope(reward=0.75, observation={"text": "closer"}))
    ]
    first = _call("act", {"guess": "crane"})
    first["choices"][0]["message"]["reasoning"] = "Start broad."
    _responses(monkeypatch, first, _text("done"))

    _result, episode, _trace = native_runner._run("native.actions.v1", request)
    document = episode_to_messages(episode.records)

    assert list(document) == ["messages", "status", "time_elapsed", "finalized"]
    assert document["status"] == "completed"
    assert document["finalized"] is True
    assert [message["role"] for message in document["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assistant = document["messages"][2]
    assert assistant == {
        "role": "assistant",
        "content": "",
        "reasoning_content": "Start broad.",
        "tool_calls": [
            {
                "id": "call-act",
                "type": "function",
                "function": {"name": "act", "arguments": '{"guess": "crane"}'},
            }
        ],
    }
    assert document["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call-act",
        "name": "act",
        "content": "closer",
    }
    assert document["messages"][4] == {"role": "assistant", "content": "done"}
    assert "0.75" not in json.dumps(document)


def test_native_episode_matches_the_recorded_contract() -> None:
    from plural.harness import episode
    from plural.usage import normalize_usage

    assert native_runner.EPISODE_SCHEMA == episode.EPISODE_SCHEMA
    assert native_runner.EPISODE_FILE == episode.EPISODE_FILE
    for raw in (
        {"prompt_tokens": 12, "completion_tokens": 3, "cost": 0.5},
        {
            "input_tokens": 7,
            "output_tokens": 2,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 1},
            "cost_usd": 0.25,
        },
        {},
    ):
        assert native_runner._usage(raw) == normalize_usage(raw).model_dump(mode="json")


def test_native_loop_records_model_calls_and_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.atif import episode_to_atif, validate_atif

    request = _request(tmp_path)
    request["environment"]["actions"] = [
        _action(tmp_path, _envelope(reward=0.75, observation={"text": "closer"}))
    ]
    first = _call("act", {"guess": "crane"})
    first["usage"] = {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0003}
    first["plural_request_id"] = "req-1"
    second = _text("done")
    second["usage"] = {"prompt_tokens": 140, "completion_tokens": 5, "cost": 0.0002}
    second["plural_request_id"] = "req-2"
    _responses(monkeypatch, first, second)

    result, episode, _trace = native_runner._run("native.actions.v1", request)

    kinds = [record["kind"] for record in episode.records]
    assert kinds == ["environment.reset", "model.call", "environment.step", "model.call"]
    assert [record["sequence"] for record in episode.records] == [1, 2, 3, 4]
    call = episode.records[1]
    assert call["usage"]["input_tokens"] == 100
    assert call["usage"]["cost_usd"] == 0.0003
    assert call["request_id"] == "req-1"
    assert call["started_at"] <= call["ended_at"]
    # The second call sends only the messages appended since the first.
    assert episode.records[3]["messages_offset"] == call["message_count"]
    step = episode.records[2]
    assert step["action"] == "act"
    assert step["reward"] == 0.75
    assert step["tool_call_id"] == "call-act"
    assert result["cost_usd"] == pytest.approx(0.0005)

    trajectory = episode_to_atif(episode.records, agent_name="agent")
    assert validate_atif(trajectory) == []
    assert [step["source"] for step in trajectory["steps"]] == ["system", "user", "agent", "agent"]
    agent = trajectory["steps"][2]
    assert agent["tool_calls"][0]["arguments"] == {"guess": "crane"}
    assert agent["observation"]["results"][0]["source_call_id"] == "call-act"
    assert "closer" in agent["observation"]["results"][0]["content"]
    assert agent["metrics"]["cost_usd"] == 0.0003
    assert agent["metrics"]["extra"]["request_id"] == "req-1"
    totals = trajectory["final_metrics"]
    assert totals["total_prompt_tokens"] == 240
    assert totals["total_completion_tokens"] == 25
    assert totals["total_cost_usd"] == pytest.approx(0.0005)
    assert totals["extra"]["calls_missing_cost"] == 0
    # Reward is episode bookkeeping and never part of what the Agent saw.
    assert "0.75" not in json.dumps(trajectory["steps"])
    assert "reward" not in json.dumps(trajectory["steps"])
