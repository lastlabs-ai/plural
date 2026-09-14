from plural import Episode, VerifierOutput


def solved(episode: Episode) -> VerifierOutput:
    guesses = episode.state.get("guesses") or []
    return VerifierOutput(
        reward=float(bool(episode.observation.get("solved"))),
        scores={
            "guesses": float(len(guesses)),
            "tokens": float(episode.usage.total_tokens or 0),
        },
        evidence=[f"{len(guesses)} guesses"],
    )
