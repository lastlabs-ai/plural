"""A Harness that guesses a fixed word list instead of calling a model."""

from plural import Harness, HarnessResult


class WordListHarness(Harness):
    auth = ("none",)

    def run(self, task, agent, environment):
        """Guess each configured word until the board is solved or guesses run out."""
        environment.reset()
        steps = []
        for word in self.config.get("words", []):
            step = environment.step("guess", word=word)
            steps.append(step)
            if step.terminated or step.truncated:
                break
        return HarnessResult(
            response=steps[-1].observation if steps else {},
            trajectory=tuple({"type": "action", "observation": step.observation} for step in steps),
        )
