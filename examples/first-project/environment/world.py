"""A support queue authored with Plural's typed Environment API."""

from typing import Any

from plural import Environment, Observation, State, action, hidden


class QueueObservation(Observation):
    ticket_id: str = ""
    customer_tier: str = ""
    issue: str = ""
    policy: str = ""
    category: str = ""
    draft_reply: str = ""
    status: str = "open"
    done: bool = False


class QueueState(State):
    ticket_id: str = ""
    customer_tier: str = ""
    issue: str = ""
    expected: str = hidden(default="")
    policy: str = ""
    category: str = ""
    draft_reply: str = ""
    status: str = "open"
    done: bool = False


TICKETS = {
    "ticket-1": {
        "customer_tier": "business",
        "issue": "I was charged twice for my annual subscription.",
        "expected": "billing",
        "policy": "Acknowledge the duplicate charge and route it to billing for refund review.",
    },
    "ticket-2": {
        "customer_tier": "free",
        "issue": "The desktop application crashes whenever I open an exported report.",
        "expected": "technical",
        "policy": "Ask for the app version and route reproducible crashes to technical support.",
    },
    "ticket-3": {
        "customer_tier": "pro",
        "issue": "Where can I change the display name shown to my team?",
        "expected": "account",
        "policy": "Explain that profile settings control the display name.",
    },
}


class SupportQueue(Environment[QueueObservation, QueueState]):
    name = "support-queue"
    version = "1.0.0"
    overview = "Inspect a customer ticket, categorize it, draft a reply, and resolve it."
    reset_command = ("python", "commands.py", "reset")

    def __init__(self, *, ticket_id: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        info = self.info if isinstance(self.info, dict) else {}
        self._ticket_id = ticket_id or info.get("ticket_id")

    def observe(self) -> dict:
        self.observation = QueueObservation(
            ticket_id=self.state.ticket_id,
            customer_tier=self.state.customer_tier,
            issue=self.state.issue,
            policy=self.state.policy,
            category=self.state.category,
            draft_reply=self.state.draft_reply,
            status=self.state.status,
            done=self.state.done,
        )
        return self.observation_snapshot()

    def reset(self, *, seed=None, options=None):
        """Load the Task-bound ticket. Called by the Job, not the Agent."""
        del options
        super().reset(seed=seed)
        ticket_id = self._ticket_id
        if ticket_id not in TICKETS:
            raise ValueError("SupportQueue must be constructed for a Task ticket")
        ticket = TICKETS[ticket_id]
        self.state = QueueState(
            ticket_id=ticket_id,
            customer_tier=ticket["customer_tier"],
            issue=ticket["issue"],
            expected=ticket["expected"],
            policy=ticket["policy"],
            seed=self.state.seed,
        )
        self.observe()
        return self.observation, {}

    @action
    def inspect_ticket(self) -> dict:
        """Read the ticket and the support policy that applies to it."""
        if not self.state.ticket_id:
            raise ValueError("Episode has not been reset")
        return self.observe()

    @action
    def categorize(self, category: str) -> dict:
        """Assign billing, technical, or account to the open ticket."""
        if not self.state.ticket_id:
            raise ValueError("Episode has not been reset")
        if self.state.done:
            raise ValueError("The ticket has already been resolved")
        if category not in {"billing", "technical", "account"}:
            raise ValueError("Choose billing, technical, or account")
        self.state.category = category
        self.state.status = "triaged"
        return self.observe()

    @action
    def draft_response(self, message: str) -> dict:
        """Draft a concise customer-facing response."""
        if not self.state.category:
            raise ValueError("Categorize the ticket before drafting a response")
        if not message.strip():
            raise ValueError("The response must not be empty")
        self.state.draft_reply = message.strip()
        self.state.status = "drafted"
        return self.observe()

    @action
    def resolve(self) -> dict:
        """Resolve the ticket after categorization and response drafting."""
        if not self.state.category or not self.state.draft_reply:
            raise ValueError("Categorize the ticket and draft a response before resolving")
        self.state.done = True
        self.state.status = "resolved"
        return self.observe()

    def view(self) -> dict[str, str]:
        """Render a compact operator view for inspection UIs."""
        return {
            "title": self.state.ticket_id or "support ticket",
            "status": self.state.status,
            "summary": self.state.issue,
            "category": self.state.category or "unassigned",
        }
