"""Check the vault: opened or not, the same for both partners."""

from plural import Episode, Step, VerifierOutput

SEATS = ("seat_1", "seat_2")


def measure(step: Step) -> dict[str, dict[str, float]]:
    """Each partner's posts so far."""
    board = step.apps["vault"].state.board
    return {
        "posts": {seat: float(sum(line.startswith(f"{seat}:") for line in board)) for seat in SEATS}
    }


def check(episode: Episode) -> VerifierOutput:
    """1 when the vault opened, fewer tries scoring no higher; both seats share it."""
    state = episode.apps["vault"].final
    opened = bool(state["opened"])
    return VerifierOutput(
        score=1.0 if opened else 0.0,
        metrics={"opened": float(opened)},
        evidence=[
            f"{'opened' if opened else 'stayed shut'} after {state['tries']} tries and {state['moves']} moves"
        ],
    )
