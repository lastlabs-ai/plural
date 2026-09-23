"""A support queue authored with Plural's typed Environment API."""

from plural import Environment, Observation, State, action, initial

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
CATEGORIES = ("billing", "technical", "account")


class QueueState(State):
    ticket_id: str = initial("", description="Which ticket this Task opens.")
    customer_tier: str = ""
    issue: str = ""
    expected: str = ""
    policy: str = ""
    category: str = ""
    draft_reply: str = ""
    status: str = "open"
    done: bool = False


class QueueObservation(Observation):
    ticket_id: str = ""
    customer_tier: str = ""
    issue: str = ""
    policy: str = ""
    category: str = ""
    draft_reply: str = ""
    status: str = "open"
    done: bool = False


class SupportQueue(Environment[QueueObservation, QueueState]):
    def reset(self, *, seed=None, options=None):
        """Open the Task's ticket. Called by the Job, not the Agent."""
        _, info = super().reset(seed=seed, options=options)
        ticket = TICKETS.get(self.state.ticket_id)
        if ticket is None:
            raise ValueError(
                f"Unknown ticket {self.state.ticket_id!r}; set initial_state.ticket_id"
            )
        self.state.customer_tier = ticket["customer_tier"]
        self.state.issue = ticket["issue"]
        self.state.expected = ticket["expected"]
        self.state.policy = ticket["policy"]
        self._observe()
        return self.observation, info

    def _observe(self) -> QueueObservation:
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
        return self.observation

    @action
    def inspect_ticket(self) -> dict:
        """Read the ticket and the support policy that applies to it."""
        return self._observe().model_dump()

    @action
    def categorize(self, category: str) -> dict:
        """Assign billing, technical, or account to the open ticket."""
        if self.state.done:
            raise ValueError("The ticket has already been resolved")
        if category not in CATEGORIES:
            raise ValueError("Choose billing, technical, or account")
        self.state.category = category
        self.state.status = "triaged"
        return self._observe().model_dump()

    @action
    def draft_response(self, message: str) -> dict:
        """Draft a concise customer-facing response."""
        if not self.state.category:
            raise ValueError("Categorize the ticket before drafting a response")
        if not message.strip():
            raise ValueError("The response must not be empty")
        self.state.draft_reply = message.strip()
        self.state.status = "drafted"
        return self._observe().model_dump()

    @action
    def resolve(self) -> dict:
        """Resolve the ticket after categorization and response drafting."""
        if not self.state.category or not self.state.draft_reply:
            raise ValueError("Categorize the ticket and draft a response before resolving")
        self.state.done = True
        self.state.status = "resolved"
        return self._observe().model_dump()

    def terminated(self) -> bool:
        """End the episode once the ticket is resolved."""
        return self.state.done

    def reward(self, previous_state, current_state, action, result) -> float:
        """Credit each step that moves the ticket forward. Never part of the score."""
        order = ("open", "triaged", "drafted", "resolved")
        before = order.index(previous_state["status"])
        after = order.index(current_state["status"])
        return 0.25 * max(after - before, 0)
