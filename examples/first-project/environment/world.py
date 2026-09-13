"""A tiny support queue authored with Plural's typed Environment API."""

from typing import Any

from plural import Environment, Observation, State, action, hidden


class QueueObservation(Observation):
    ticket: str = ""
    category: str = ""
    done: bool = False


class QueueState(State):
    ticket_id: str = ""
    ticket: str = ""
    expected: str = hidden(default="")
    category: str = ""
    done: bool = False


TICKETS = {
    "ticket-1": ("I was charged twice for my subscription.", "billing"),
    "ticket-2": ("The desktop application crashes when I open it.", "technical"),
    "ticket-3": ("Where can I change my display name?", "account"),
}


class SupportQueue(Environment[QueueObservation, QueueState]):
    name = "support-queue"
    revision = "0.1.0"
    overview = "Read a ticket, then assign billing, technical, or account."
    reset_command = ("python", "commands.py", "reset")

    def __init__(self, *, ticket_id: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        info = self.info if isinstance(self.info, dict) else {}
        self._ticket_id = ticket_id or info.get("ticket_id")

    def observe(self) -> dict:
        self.observation = QueueObservation(
            ticket=self.state.ticket, category=self.state.category, done=self.state.done
        )
        return self.observation_snapshot()

    def reset(self, *, seed=None, options=None):
        """Load the Task-bound ticket. Called by the Job, not the Agent."""
        del options
        super().reset(seed=seed)
        ticket_id = self._ticket_id
        if ticket_id not in TICKETS:
            raise ValueError("SupportQueue must be constructed for a Task ticket")
        ticket, expected = TICKETS[ticket_id]
        self.state = QueueState(
            ticket_id=ticket_id, ticket=ticket, expected=expected, seed=self.state.seed
        )
        self.observe()
        return self.observation, {}

    @action
    def categorize(self, category: str) -> dict:
        """Assign billing, technical, or account to the open ticket, then finish."""
        if not self.state.ticket_id:
            raise ValueError("Episode has not been reset")
        if self.state.done:
            raise ValueError("The ticket has already been categorized")
        if category not in {"billing", "technical", "account"}:
            raise ValueError("Choose billing, technical, or account")
        self.state.category = category
        self.state.done = True
        return self.observe()
