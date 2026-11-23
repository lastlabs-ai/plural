"""An Agent's context policy: how the native loop compacts, and how it is rebuilt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plural import Agent
from plural.atif import episode_to_atif, validate_atif
from plural.harness import native_runner
from plural.transcript import episode_to_messages


def _turns(count: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You run a vending machine."},
        {"role": "user", "content": "Reorder whenever stock drops below 5."},
    ]
    for index in range(count):
        call = {
            "id": f"c{index}",
            "type": "function",
            "function": {"name": "check", "arguments": "{}"},
        }
        messages.append({"role": "assistant", "content": "x" * 400, "tool_calls": [call]})
        messages.append({"role": "tool", "tool_call_id": f"c{index}", "content": "y" * 400})
    return messages


def test_the_policy_validates_and_leaves_old_agents_alone() -> None:
    plain = Agent(model="openai/gpt-5.6-luna", name="vend")
    assert "context" not in plain._definition().model_dump(mode="json")
    with_policy = Agent(
        model="openai/gpt-5.6-luna",
        name="vend",
        context={"strategy": "summarize", "max_tokens": 4000},
    )
    assert with_policy.content_hash != plain.content_hash
    with pytest.raises(ValueError, match="max_tokens"):
        Agent(model="openai/gpt-5.6-luna", name="vend", context={"strategy": "window"})


def test_the_policy_is_a_harness_setting_and_old_agents_keep_their_hash() -> None:
    policy = {"strategy": "summarize", "max_tokens": 4000}
    old = Agent(model="openai/gpt-5.6-luna", name="vend", context=policy)
    new = Agent(model="openai/gpt-5.6-luna", name="vend", harness_config={"context": policy})
    assert old.content_hash == new.content_hash
    assert old.harness_config["context"]["strategy"] == "summarize"
    assert "context" not in old.model_dump(mode="json")
    assert Agent.model_validate(old.model_dump(mode="json")).content_hash == old.content_hash
    definition = new._definition()
    assert definition.harness_config == {}
    assert definition.context is not None and definition.context.max_tokens == 4000
    with pytest.raises(ValueError, match="context twice"):
        Agent(
            model="openai/gpt-5.6-luna",
            context=policy,
            harness_config={"context": {"strategy": "window", "max_tokens": 4000}},
        )
    with pytest.raises(ValueError, match="takes only context"):
        Agent(model="openai/gpt-5.6-luna", harness_config={"context": policy, "x": 1})


def test_a_harness_refuses_a_strategy_it_does_not_carry_out() -> None:
    from plural import Harness, HarnessResult
    from plural.harness.builtins import BUILTIN_HARNESSES, package_context_strategies
    from plural.harness.packages import native_workspace_v1

    window = {"strategy": "window", "max_tokens": 4000}
    assert package_context_strategies(native_workspace_v1()) == ("window", "summarize", "none")
    for name, spec in BUILTIN_HARNESSES.items():
        assert spec.context_strategies == ("none",), name
    claude = "anthropic/claude-haiku-4-5"
    with pytest.raises(ValueError, match="'claude-code' supports none"):
        Agent(model=claude, harness="claude-code", harness_config={"context": window})
    vendor = Agent(
        model=claude,
        harness="claude-code",
        harness_config={"context": {"strategy": "none"}, "reasoning_effort": "low"},
    )
    assert "context" not in vendor._definition().harness_config
    assert vendor._definition().context is not None

    class Plain(Harness):
        def run(self, task: Any, agent: Any, environment: Any) -> HarnessResult:
            return HarnessResult(response="")

    class Windowed(Plain):
        @classmethod
        def context_strategies(cls) -> tuple[Any, ...]:
            return ("window",)

    with pytest.raises(ValueError, match="supports no context policy"):
        Agent(model="openai/gpt-5.6-luna", harness=Plain(), context=window)
    assert Plain()._package().content_hash == Plain()._package().content_hash
    assert "context_strategies" not in Plain()._package().definition.model_dump(
        exclude_defaults=True
    )
    windowed = Agent(model="openai/gpt-5.6-luna", harness=Windowed(), context=window)
    assert windowed.context is not None and windowed.context.strategy == "window"
    assert Windowed()._package().definition.context_strategies == ("window",)
    with pytest.raises(ValueError, match="supports window"):
        Agent(
            model="openai/gpt-5.6-luna",
            harness=Windowed(),
            harness_config={"context": {"strategy": "summarize", "max_tokens": 4000}},
        )


def test_harness_yaml_declares_the_strategies(tmp_path: Path) -> None:
    from plural.project.resources import load_harness_directory

    source = tmp_path / "loop"
    source.mkdir()
    (source / "harness.yaml").write_text(
        "name: loop\npython: harness.py:Loop\ncontext_strategies: [window, none]\n",
        encoding="utf-8",
    )
    (source / "harness.py").write_text(
        "from plural import Harness\n\n"
        "class Loop(Harness):\n"
        "    def run(self, task, agent, environment):\n"
        "        return ''\n",
        encoding="utf-8",
    )
    harness = load_harness_directory(source, name="loop")
    assert type(harness).context_strategies() == ("window", "none")
    assert harness._package().definition.context_strategies == ("window", "none")
    Agent(
        model="openai/gpt-5.6-luna",
        harness=harness,
        harness_config={"context": {"strategy": "window", "max_tokens": 4000}},
    )


def test_window_keeps_the_task_and_the_last_turns(tmp_path: Path) -> None:
    episode = native_runner._Episode(stream=tmp_path / "episode.jsonl")
    episode.messages = _turns(20)
    policy = {"strategy": "window", "max_tokens": 1000, "keep_last_turns": 3}
    cost, _ = native_runner._compact(episode, policy, model="m", routing={}, timeout=10, turn=21)
    assert cost is None
    roles = [item["role"] for item in episode.messages]
    assert roles[:2] == ["system", "user"]
    assert episode.messages[1]["content"].startswith("Reorder")
    # Each kept turn still has its tool result after its call.
    assert roles[2:] == ["assistant", "tool"] * 3
    record = json.loads((tmp_path / "episode.jsonl").read_text().splitlines()[-1])
    assert record["kind"] == "context.compaction"
    assert record["dropped_messages"] == 34
    assert record["messages"] == episode.messages


def test_summarize_replaces_the_task_with_a_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def summary(**_: Any) -> tuple[dict[str, Any], float]:
        return {
            "model": "m",
            "choices": [{"message": {"role": "assistant", "content": "Sold snacks."}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.001},
        }, 0.0

    monkeypatch.setattr(native_runner, "_model_call", summary)
    episode = native_runner._Episode(stream=tmp_path / "episode.jsonl")
    episode.messages = _turns(20)
    policy = {"strategy": "summarize", "max_tokens": 1000, "keep_last_turns": 2}
    cost, _ = native_runner._compact(episode, policy, model="m", routing={}, timeout=10, turn=21)
    assert cost == 0.001
    assert episode.messages[1]["content"] == "Summary of the conversation so far:\nSold snacks."
    assert not any("Reorder" in str(item.get("content")) for item in episode.messages)


def test_the_context_after_a_compaction_is_what_the_records_rebuild(tmp_path: Path) -> None:
    episode = native_runner._Episode(stream=tmp_path / "episode.jsonl")
    episode.messages = _turns(10)
    started = native_runner._started()
    episode.model_call(
        started,
        turn=10,
        model="m",
        tools=[],
        response={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        message={"role": "assistant", "content": "ok"},
    )
    native_runner._compact(
        episode,
        {"strategy": "window", "max_tokens": 1000, "keep_last_turns": 2},
        model="m",
        routing={},
        timeout=10,
        turn=11,
    )
    compacted = list(episode.messages)
    implicit = {
        "schema": native_runner.EPISODE_SCHEMA,
        "sequence": len(episode.records) + 1,
        "kind": "environment.step",
        "turn": 11,
        "tool_call_id": "",
        "action": "wait",
        "content": "[Day 3] Sold 2.",
        "implicit": True,
    }
    rebuilt = episode_to_messages([*episode.records, implicit])["messages"]
    # The transcript names each tool result after its call; nothing else changes.
    assert [
        {key: value for key, value in item.items() if key != "name"}
        for item in rebuilt[: len(compacted)]
    ] == compacted
    assert rebuilt[-1] == {"role": "user", "content": "(You waited.)\n[Day 3] Sold 2."}
    document = episode_to_atif(episode.records, agent_name="vend", agent_version="1")
    assert validate_atif(document) == []
