from __future__ import annotations

import pytest

from plural import App, Environment, Runtime, action
from plural.common import described, raised_at
from plural.verifiers import DeterministicVerifier, Episode, Step


def _call(fn, *args):
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001
        return exc
    raise AssertionError("expected an error")


def test_an_error_names_the_line_of_user_code_that_raised() -> None:
    def check(state):
        return state["done"]

    error = _call(check, {})
    assert raised_at(error) == f"test_verifier_errors.py:{check.__code__.co_firstlineno + 1}"
    assert described(error).startswith("KeyError: 'done' (at test_verifier_errors.py:")
    assert raised_at(_call(check)) is None


def test_a_check_that_raises_names_its_verifier_and_line() -> None:
    def solved(episode: Episode) -> float:
        return episode.state["done"]

    episode = Episode(state={})
    with pytest.raises(ValueError, match=r"'solved' check raised KeyError: 'done' \(at test_"):
        DeterministicVerifier(name="solved", check=solved).invoke(episode)


def test_a_reward_that_raises_says_where_and_never_fails_the_action() -> None:
    class Counter(App):
        @action
        def bump(self) -> str:
            return "bumped"

    def flaky(step: Step) -> float:
        return step.current_state["missing"]

    environment = Environment(name="counter", apps=[Counter()], runtime=Runtime.local())
    verifier = DeterministicVerifier(name="flaky", check="total_reward", reward=flaky)
    environment.reset(verifiers=[verifier])
    observation, reward, _, _, info = environment.step("bump")
    assert observation == {"text": "bumped"} and reward == 0.0
    [signal] = info["rewards"]
    assert signal["error"].startswith("KeyError: 'missing' (at test_verifier_errors.py:")
