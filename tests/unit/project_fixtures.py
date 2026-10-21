"""A small, complete Plural project written to disk for tests."""

from __future__ import annotations

import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from plural.auth import FileCredentialStore
from plural.project import Project, ResourceRef, Workspace

FILES = {
    "project.yaml": """
        schema_version: 1
        name: support-desk
        description: Refund handling.
    """,
    "plural.lock": "lock_version: 1\n",
    "README.md": "# support-desk\n\nRefund decisions for a support queue.\n",
    "environments/queue/environment.yaml": """
        # Queue environment.
        name: queue
        version: 0.1.0
        description: A refund queue.
        overview: Tickets arrive; the Agent resolves them.
        python: environment.py:Queue
        readme: README.md
        resources:
          - resources/policy.md
        runtime:
          provider: local
        harness_policy:
          mode: allow_all
    """,
    "environments/queue/environment.py": '''
        from plural import App, State, action, initial


        class QueueState(State):
            order: str = initial("", description="Order under review.")
            refundable: bool = initial(False)
            answer: str = ""
            done: bool = False


        class Queue(App[QueueState]):
            """A refund queue."""

            def reset(self, initial_state):
                super().reset(initial_state)
                return f"Order {self.state.order} is waiting."

            @action
            def submit(self, answer: str) -> str:
                """Submit the resolution: refunded or denied."""
                self.state.answer = answer
                self.state.done = True
                return "Submitted."

            def terminated(self) -> bool:
                return self.state.done
    ''',
    "environments/queue/README.md": """
        # Queue

        ## Overview

        Tickets arrive in a queue and the Agent resolves each one.
    """,
    "environments/queue/resources/policy.md": "Refund orders marked refundable.\n",
    "verifiers/resolved/verifier.yaml": """
        name: resolved
        version: 0.1.0
        kind: deterministic
        check: verify.py:check
        reward: verify.py:reward
    """,
    "verifiers/resolved/verify.py": """
        from plural import Episode, VerifierOutput, Step


        def check(episode: Episode) -> VerifierOutput:
            expected = "refunded" if episode.state.get("refundable") else "denied"
            correct = episode.state.get("answer") == expected
            return VerifierOutput(score=float(correct), evidence=[f"expected={expected}"])


        def reward(step: Step) -> float:
            return 1.0 if step.current_state["done"] else 0.0
    """,
    "tasks/refund/task.yaml": """
        name: refund
        version: 0.1.0
        instructions: instruction.md
        environment: queue
        verifiers:
          - resolved
        initial_state:
          order: A-1
          refundable: true
    """,
    "tasks/refund/instruction.md": "Review order A-1 and submit refunded or denied.\n",
    "tasks/deny/task.yaml": """
        name: deny
        version: 0.1.0
        instructions: instruction.md
        environment: queue
        verifiers:
          - resolved
        initial_state:
          order: B-2
          refundable: false
    """,
    "tasks/deny/instruction.md": "Review order B-2 and submit refunded or denied.\n",
    "harnesses/scripted/harness.yaml": """
        name: scripted
        version: 0.1.0
        description: Always submits refunded, without a model.
        python: harness.py:ScriptedHarness
        config:
          answer: refunded
    """,
    "harnesses/scripted/harness.py": """
        from plural import Harness, HarnessResult


        class ScriptedHarness(Harness):
            auth = ("none",)

            def run(self, task, agent, environment):
                environment.reset()
                step = environment.step("submit", answer=self.config.get("answer", "refunded"))
                return HarnessResult(
                    response=step.observation,
                    trajectory=({"type": "action", "observation": step.observation},),
                )
    """,
    "agents/baseline/agent.yaml": """
        name: baseline
        version: 0.1.0
        model: openai/gpt-5.6-luna
        instructions: Follow the refund policy.
        harness: scripted
        auth: none
    """,
    "benchmarks/basics/benchmark.yaml": """
        # Basics benchmark.
        name: basics
        version: 0.1.0
        description: Refund decisions.
        purpose: Measures whether an Agent applies the refund policy.
        tasks:
          - refund
          - deny
        # Ranking rules.
        scoring:
          metric: Correct decisions
          description: Share of orders resolved per policy.
          aggregation: weighted_mean
          score_range: [0.0, 1.0]
          success_threshold: 1.0
          agent_failure: zero
          infrastructure_error: exclude
    """,
    "benchmarks/basics/README.md": "# Basics\n\nMeasures refund decisions.\n",
}


def write_project(root: Path) -> Project:
    """Write the sample project into ``root`` and load it.

    Returns:
        The project.
    """
    for relative, text in FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return Project.at(root)


def hasher_for(root: Path):  # noqa: ANN201
    """Content hashes as the real server computes them: from the resource itself."""
    kinds = {
        "environments": "environment",
        "verifiers": "verifier",
        "harnesses": "harness",
        "tasks": "task",
        "agents": "agent",
        "benchmarks": "benchmark",
    }

    def compute(collection: str, slug: str, payload: dict) -> str:  # type: ignore[type-arg]
        workspace = Workspace(Project.at(root))
        ref = ResourceRef(kinds[collection], slug)
        if not workspace.project.has(ref):
            return "sha256:" + "0" * 64
        return workspace.load(ref).content_hash

    return compute


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated user config directory with no ambient credentials."""
    config = tmp_path / "config-home"
    monkeypatch.setenv("PLURAL_CONFIG_HOME", str(config))
    for name in ("PLURAL_API_KEY", "PLURAL_PROJECT", "PLURAL_ACCOUNT", "PLURAL_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PLURAL_API_URL", "https://plural.test")
    store = FileCredentialStore(config / "credentials.json")
    monkeypatch.setattr("plural.auth.default_credential_store", lambda path=None: store)
    yield config
