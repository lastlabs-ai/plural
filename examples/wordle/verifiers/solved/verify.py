"""Verify a Wordle episode: score the finished game with check, and reward each guess with reward."""

from plural import Episode, Step, VerifierOutput


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
