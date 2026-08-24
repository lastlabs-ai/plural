"""Episode lifecycle and stop-state types."""

from __future__ import annotations

from enum import Enum


class StopReason(str, Enum):
    """Why an environment episode stopped."""

    TERMINATED = "terminated"
    TRUNCATED = "truncated"
    POLICY_STOP = "policy_stop"
    FAILURE = "failure"


class EpisodeState(str, Enum):
    """Lifecycle state of an environment instance."""

    IDLE = "idle"
    OPEN = "open"
    STOPPED = "stopped"
    CLOSED = "closed"


def is_stopped(reason: StopReason | str | None) -> bool:
    """Return whether a value is one of the defined episode stop reasons."""
    if reason is None:
        return False
    try:
        StopReason(reason)
    except ValueError:
        return False
    return True


class EpisodeError(RuntimeError):
    """Raised when an operation is invalid for the current episode state."""

    def __init__(self, message: str, state: EpisodeState) -> None:
        self.state = state
        super().__init__(f"{message} (episode state: {state.value})")
