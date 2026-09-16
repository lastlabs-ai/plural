"""Class-based implementations for Plural's built-in vendor Harnesses."""

from __future__ import annotations

from plural.harness.interface import (
    HarnessAgent,
    HarnessEnvironment,
    HarnessResult,
    HarnessTask,
)
from plural.harness.models import Harness
from plural.harness.vendor_adapter import run_vendor


class HermesHarness(Harness):
    """Run the pinned Hermes CLI."""

    name = "hermes"

    def run(
        self,
        task: HarnessTask,
        agent: HarnessAgent,
        environment: HarnessEnvironment,
    ) -> HarnessResult:
        return run_vendor(self.name, task, agent, environment)


class ClaudeCodeHarness(Harness):
    """Run the pinned Claude Code CLI."""

    name = "claude-code"

    def run(
        self,
        task: HarnessTask,
        agent: HarnessAgent,
        environment: HarnessEnvironment,
    ) -> HarnessResult:
        return run_vendor(self.name, task, agent, environment)


class CodexHarness(Harness):
    """Run the pinned Codex CLI."""

    name = "codex"

    def run(
        self,
        task: HarnessTask,
        agent: HarnessAgent,
        environment: HarnessEnvironment,
    ) -> HarnessResult:
        return run_vendor(self.name, task, agent, environment)


__all__ = ["ClaudeCodeHarness", "CodexHarness", "HermesHarness"]
