from plural import Episode, VerifierOutput


def solved(episode: Episode) -> VerifierOutput:
    """Score is 1 when the puzzle is solved and 0 otherwise."""
    guesses = episode.state.get("guesses") or []
    solved_flag = bool(episode.observation.get("solved"))
    return VerifierOutput(
        score=float(solved_flag),
        scores={
            "guesses": float(len(guesses)),
            "tokens": float(episode.usage.total_tokens or 0),
        },
        evidence=[f"{len(guesses)} guesses"],
    )


def turns(episode: Episode) -> VerifierOutput:
    """Score is how many guesses it took to solve. An unsolved episode scores 0."""
    guesses = episode.state.get("guesses") or []
    count = len(guesses)
    solved_flag = bool(episode.observation.get("solved"))
    detail = f"{count} guesses" if solved_flag else f"unsolved after {count} guesses"
    return VerifierOutput(
        score=float(count if solved_flag else 0),
        scores={"guesses": float(count)},
        evidence=[detail],
    )
