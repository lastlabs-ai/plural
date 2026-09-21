from plural import Episode, VerifierOutput


def correct_category(episode: Episode) -> VerifierOutput:
    observation = episode.observation
    expected = episode.state.get("expected")
    drafted = bool(str(observation.get("draft_reply") or "").strip())
    correct = bool(observation.get("done") and observation.get("category") == expected and drafted)
    score = float(correct)
    return VerifierOutput(
        score=score,
        scores={
            "correct_category": score,
            "response_drafted": float(drafted),
        },
        evidence=[
            f"status={observation.get('status')}",
            f"category={observation.get('category')}",
            f"correct={correct}",
        ],
        feedback=(
            "Correct category and a response was drafted."
            if correct
            else "The ticket was not resolved with the correct category and a response."
        ),
    )
