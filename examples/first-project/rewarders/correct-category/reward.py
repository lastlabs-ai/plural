"""Reward a support episode: each step that moves the ticket on, and the outcome."""

from plural import Episode, RewarderOutput, Step

ORDER = ("open", "triaged", "drafted", "resolved")


def final(episode: Episode) -> RewarderOutput:
    """Score 1 when the ticket was resolved with the expected category and a reply."""
    state = episode.state
    drafted = bool(str(state.get("draft_reply") or "").strip())
    correct = bool(state.get("done") and state.get("category") == state.get("expected") and drafted)
    score = float(correct)
    return RewarderOutput(
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


def step(step: Step) -> float:
    """Credit each action that moves the ticket forward."""
    if step.error:
        return 0.0
    before = ORDER.index(step.previous_state["status"])
    after = ORDER.index(step.current_state["status"])
    return 0.25 * max(after - before, 0)
