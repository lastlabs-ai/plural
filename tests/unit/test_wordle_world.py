from __future__ import annotations

import sys
from pathlib import Path

import pytest

from plural import TaskData
from plural.environments import verify_replay
from plural.tracing import ParsedAction

_WORDLE = Path(__file__).resolve().parents[2] / "examples" / "environment" / "wordle"
sys.path.insert(0, str(_WORDLE))
for _name in ("env", "words"):
    sys.modules.pop(_name, None)
from env import MAX_GUESSES, make_env  # noqa: E402
from words import is_allowed, pattern, pick_answer  # noqa: E402

sys.modules.pop("env", None)
sys.modules.pop("words", None)
sys.path.remove(str(_WORDLE))


def _task(secret: str = "crane") -> TaskData:
    return TaskData(task_id=secret, input="play", expected=secret, metadata={"seed": 0})


def test_pattern_duplicate_letters_and_seed() -> None:
    assert pattern("crane", "crane") == "GGGGG"
    assert pattern("abide", "speed") == "...YY"
    assert pattern("erase", "speed") == "Y..YY"
    assert is_allowed(pick_answer(42))


def test_valid_step_records_reward_result_and_decision() -> None:
    env = make_env()
    env.reset(_task())

    result = env.step(ParsedAction(name="guess", arguments={"word": "slate"}))

    assert result.reward == pytest.approx(0.2)
    assert result.observation.guesses_left == 5
    decision = env.episode_trace.decisions()[0]
    assert decision.parsed_action[0].name == "guess"
    assert decision.tool_calls[0].result["pattern"] == "..G.G"
    assert "SLATE" in decision.tool_calls[0].result["board"]


def test_invalid_step_preserves_guess_slot_but_uses_episode_turn() -> None:
    env = make_env()
    env.reset(_task())

    result = env.step(ParsedAction(name="guess", arguments={"word": "hi"}))

    assert result.reward == pytest.approx(-0.05)
    assert result.info["turn"] == 1
    assert result.observation.guesses_left == MAX_GUESSES
    assert env.rows == []
    assert "error" in env.episode_trace.decisions()[0].tool_calls[0].result


def test_missing_word_is_recorded_as_tool_error() -> None:
    env = make_env()
    env.reset(_task())

    result = env.step(ParsedAction(name="guess", arguments={}))

    tool_call = env.episode_trace.decisions()[0].tool_calls[0]
    assert result.info["tool_errors"]
    assert result.reward == pytest.approx(-0.05)
    assert tool_call.error is not None
    assert env.guesses_left == MAX_GUESSES


def test_loss_after_six_valid_misses() -> None:
    env = make_env()
    env.reset(_task())
    misses = ["audio", "wordy", "aback", "abase", "abate", "abbey"]

    for word in misses:
        result = env.step(ParsedAction(name="guess", arguments={"word": word}))

    assert result.terminated is True
    assert result.truncated is False
    assert env.solved is False
    assert env.guesses_left == 0
    assert env.score() == 0.0


def test_solved_trace_replays() -> None:
    task = _task()
    env = make_env()
    env.reset(task)
    env.step(ParsedAction(name="guess", arguments={"word": "slate"}))
    env.step(ParsedAction(name="guess", arguments={"word": "crane"}))
    rollout = env.close_episode()

    replay = verify_replay(make_env(), rollout.trace, task=task)

    assert replay.ok, replay.mismatches
    assert rollout.trace.terminated is True
    assert rollout.trace.outcome is not None
    assert rollout.trace.outcome.reward == pytest.approx(5 / 6)


def test_make_env_is_tool_only_and_versioned() -> None:
    env = make_env()
    assert env.version == "0.3.0"
    assert env.max_turns == MAX_GUESSES * 4
    assert {item.function.name for item in env.tool_defs} == {"guess"}
