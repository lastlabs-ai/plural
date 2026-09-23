"""A Harness that triages by keyword instead of calling a model."""

from plural import Harness, HarnessResult


class ScriptedTriageHarness(Harness):
    auth = ("none",)

    def run(self, task, agent, environment):
        """Drive one episode using only what the Environment observes."""
        environment.reset()
        ticket = environment.step("inspect_ticket").observation
        category = self._category(str(ticket.get("issue", "")))
        steps = [
            environment.step("categorize", category=category),
            environment.step(
                "draft_response",
                message=f"Thanks for reaching out. We have routed this to {category} support.",
            ),
            environment.step("resolve"),
        ]
        return HarnessResult(
            response=steps[-1].observation,
            trajectory=tuple({"type": "action", "observation": step.observation} for step in steps),
        )

    def _category(self, issue: str) -> str:
        text = issue.lower()
        for category, words in self.config.get("keywords", {}).items():
            if any(word in text for word in words):
                return category
        return "account"
