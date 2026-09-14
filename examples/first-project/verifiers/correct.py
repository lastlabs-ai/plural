from plural import Episode, VerifierOutput


def correct_category(episode: Episode) -> VerifierOutput:
    observation = episode.observation
    expected = episode.state.get("expected")
    drafted = bool(str(observation.get("draft_reply") or "").strip())
    correct = bool(observation.get("done") and observation.get("category") == expected and drafted)
    reward = float(correct)
    return VerifierOutput(
        reward=reward,
        scores={
            "correct_category": reward,
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
