from plural import Episode, VerifierOutput


def verify(episode: Episode) -> VerifierOutput:
    """Score 1 when the puzzle is solved and 0 otherwise; report the guesses used."""
    guesses = episode.state.get("guesses") or []
    solved = bool(episode.state.get("solved"))
    detail = f"solved in {len(guesses)}" if solved else f"unsolved after {len(guesses)}"
    return VerifierOutput(
        score=float(solved),
        scores={"guesses": float(len(guesses))},
        evidence=[detail],
    )
