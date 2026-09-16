"""Class-based offline Wordle Harness."""

from __future__ import annotations

from plural import Harness, HarnessResult
from wordle import WORDS


class WordleHarness(Harness):
    """Play a fixed offline word list through the Environment interface."""

    name = "custom-wordle-loop"
    auth = ("none",)

    def run(self, task, agent, environment):
        observation = environment.reset()
        trajectory = [{"turn": 0, "type": "reset", "observation": observation}]
        for turn, word in enumerate(WORDS, start=1):
            observation = environment.step("guess", word=word)
            trajectory.append(
                {
                    "turn": turn,
                    "action": {"name": "guess", "word": word},
                    "observation": observation,
                }
            )
            if isinstance(observation, dict) and observation.get("solved"):
                break
        return HarnessResult(
            response={"task_id": task.id, "observation": observation},
            trajectory=tuple(trajectory),
            trace_id=f"wordle-{task.id}",
        )
