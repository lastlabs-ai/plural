"""Score a finished Wordle episode from its final State."""

from plural import Episode, VerifierOutput


def verify(episode: Episode) -> VerifierOutput:
    """Score 1 when the secret was guessed and 0 otherwise. Report guesses used."""
    guesses = episode.state.get("guesses") or []
    solved = bool(episode.state.get("solved"))
    detail = f"solved in {len(guesses)}" if solved else f"unsolved after {len(guesses)}"
    return VerifierOutput(
        score=float(solved),
        scores={"guesses": float(len(guesses))},
        evidence=[detail],
    )
