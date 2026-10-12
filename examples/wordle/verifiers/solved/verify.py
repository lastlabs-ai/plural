"""Verify a Wordle episode.

check scores the finished game, reward rewards each guess, and fewer_guesses credits
the solving guess once the game is over.
"""

from plural import Episode, HindsightTrial, Step, VerifierOutput


def check(episode: Episode) -> VerifierOutput:
    """Score 1 when the secret was guessed and 0 otherwise. Report guesses used."""
    guesses = episode.state.get("guesses") or []
    solved = bool(episode.state.get("solved"))
    detail = f"solved in {len(guesses)}" if solved else f"unsolved after {len(guesses)}"
    return VerifierOutput(
        score=float(solved),
        scores={"guesses": float(len(guesses))},
        evidence=[detail],
    )


def reward(step: Step) -> float:
    """One point for the guess that solves the word, minus a little for an invalid one."""
    if step.error:
        return -0.1
    solved = step.current_state["solved"] and not step.previous_state["solved"]
    return 1.0 if solved else 0.0


def fewer_guesses(trial: HindsightTrial):
    """Credit the solving guess more when it took fewer guesses."""
    guesses = trial.steps("guess")
    if trial.score and guesses:
        yield trial.credit(guesses[-1]["event_id"], 1.0 - 0.1 * (len(guesses) - 1))
