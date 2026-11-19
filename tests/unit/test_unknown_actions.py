"""Calls to tools that don't exist are recorded; tool_overrides change what the model is told."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_apps import Wordle
from test_forks import GUESSES, _plural, _steps, _WordleModel, wordle

from plural import Environment, Runtime
from plural.agents import Agent
from plural.agents.tool_overrides import ToolOverride, apply_tool_overrides
from plural.apps.host import AppHost

__all__ = ["wordle"]


def _reply(handler: Any, name: str, arguments: dict[str, Any], replies: int) -> None:
    message: dict[str, Any] = {"role": "assistant", "content": "Out of words."}
    if name:
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_{replies}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        }
    payload = json.dumps(
        {"choices": [{"message": message}], "usage": {"prompt_tokens": 9, "completion_tokens": 3}}
    ).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class _Hallucinating(_WordleModel):
    """Asks for a tool the Environment never offered, then plays."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        replies = sum(message["role"] == "tool" for message in body["messages"])
        if replies == 0:
            _reply(self, "reveal_answer", {}, replies)
        elif replies <= len(GUESSES):
            _reply(self, "guess", {"word": GUESSES[replies - 1]}, replies)
        else:
            _reply(self, "", {}, replies)


class _GuessOnce(_WordleModel):
    """Guesses once, whatever it was offered, then stops."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        replies = sum(message["role"] == "tool" for message in body["messages"])
        _reply(self, "guess" if replies == 0 else "", {"word": "crane"}, replies)


def _told(name: str) -> list[str]:
    return [
        str(tool["function"].get("description"))
        for request in _WordleModel.seen
        for tool in request.get("tools") or ()
        if tool["function"]["name"] == name
    ]


def _override(project: Path, text: str) -> None:
    path = project / "agents" / "scripted" / "agent.yaml"
    path.write_text(path.read_text("utf-8") + text, encoding="utf-8")


def test_the_native_loop_records_a_call_to_a_tool_that_does_not_exist(
    wordle: tuple[Path, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_WordleModel, "do_POST", _Hallucinating.do_POST)
    project, env = wordle
    run = _plural(project, env, "run", "-t", "storm", "-a", "scripted", "--yes")
    steps = _steps(project, run["trials"][0]["trial_id"])
    first = steps[0]
    assert first["action"] == "reveal_answer"
    assert first["info"]["unknown_action"] is True
    assert "unknown action 'reveal_answer'" in first["info"]["error"]
    assert [step["action"] for step in steps[1:]] == ["guess"] * (len(steps) - 1)
    # The model was told, so it could recover.
    told = [
        str(message["content"])
        for request in _WordleModel.seen
        for message in request["messages"]
        if message["role"] == "tool"
    ]
    assert any("unknown action 'reveal_answer'" in item for item in told)


def test_a_tool_override_rewrites_the_description_the_model_reads(
    wordle: tuple[Path, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_WordleModel, "do_POST", _GuessOnce.do_POST)
    project, env = wordle
    _override(project, "tool_overrides:\n  guess: Guess one five-letter word. Overridden.\n")
    _plural(project, env, "run", "-t", "storm", "-a", "scripted", "--yes")
    assert _told("guess") and set(_told("guess")) == {"Guess one five-letter word. Overridden."}


def test_a_call_the_harness_never_offered_is_unknown_even_when_an_app_has_it(
    tmp_path: Path,
) -> None:
    host = AppHost(Environment(apps=[Wordle()], runtime=Runtime.local()), workspace=tmp_path)
    host.reset(initial_state={"wordle": {"secret": "slate"}})
    hidden = host.step("guess", {"word": "slate"}, unknown=True)
    missing = host.step("reveal", {})
    # A hidden tool doesn't run, and the reply names no action the Agent wasn't offered.
    assert hidden["info"] == {
        "step": 1,
        "error": "unknown action 'guess'",
        "unknown_action": True,
    }
    assert missing["info"]["unknown_action"] is True
    assert "available actions: guess" in missing["info"]["error"]
    lines = [
        json.loads(line)
        for line in (tmp_path / ".plural/apps/states.jsonl").read_text().splitlines()
    ]
    assert [(line["step"], line.get("error")) for line in lines[1:]] == [
        (1, "unknown action"),
        (2, "unknown action"),
    ]
    assert host.query("wordle", "remaining", {}) == 6


def test_tool_overrides_change_the_agent_only_when_set() -> None:
    plain = Agent(model="openai/gpt-5.6-luna", name="bot", instructions="Quote.")
    same = Agent(model="openai/gpt-5.6-luna", name="bot", instructions="Quote.", tool_overrides={})
    told = Agent(
        model="openai/gpt-5.6-luna",
        name="bot",
        instructions="Quote.",
        tool_overrides={"check_schedule": "Required before any date."},
    )
    assert plain.content_hash == same.content_hash
    assert told.content_hash != plain.content_hash
    assert "tool_overrides" not in plain.model_dump(mode="json")
    assert told.tool_overrides["check_schedule"].description == "Required before any date."


def test_an_override_is_a_description_or_hidden() -> None:
    with pytest.raises(ValueError, match="needs a description"):
        ToolOverride()
    with pytest.raises(ValueError, match="one or the other"):
        ToolOverride(description="x", hidden=True)
    actions = [{"name": "a", "description": "old"}, {"name": "b", "description": "kept"}]
    assert apply_tool_overrides(actions, {}) == actions
