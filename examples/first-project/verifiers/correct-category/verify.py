from plural import Episode, VerifierOutput


def verify(episode: Episode) -> VerifierOutput:
    """Score 1 when the ticket was resolved with the expected category and a reply."""
    state = episode.state
    drafted = bool(str(state.get("draft_reply") or "").strip())
    correct = bool(state.get("done") and state.get("category") == state.get("expected") and drafted)
    score = float(correct)
    return VerifierOutput(
        score=score,
        scores={"correct_category": score, "response_drafted": float(drafted)},
        evidence=[
            f"status={state.get('status')}",
            f"category={state.get('category')}",
            f"correct={correct}",
        ],
        feedback=(
            "Correct category and a response was drafted."
            if correct
            else "The ticket was not resolved with the correct category and a response."
        ),
    )
