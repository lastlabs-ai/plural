"""Credential-free class-based custom Harness example."""

from __future__ import annotations

from plural import Harness, HarnessResult


class ExampleHarness(Harness):
    """Return a deterministic response without calling a model."""

    name = "example-harness"
    auth = ("none",)

    def run(self, task, agent, environment):
        response = f"offline response for {task.id}: {task.instructions}"
        return HarnessResult(
            response=response,
            trajectory=({"type": "response", "text": response},),
            trace_id=f"offline-{task.id}",
        )
