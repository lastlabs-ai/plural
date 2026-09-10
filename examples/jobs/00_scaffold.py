"""Scaffold Environment, Verifier, Task, Harness, Agent, Benchmark, and Job."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from plural.cli.main import app


def call(*args: str) -> str:
    """Invoke one CLI command and fail with its captured diagnostics."""
    result = CliRunner().invoke(app, list(args), color=False)
    if result.exit_code != 0:
        raise RuntimeError(result.output) from result.exception
    return result.output


with tempfile.TemporaryDirectory(prefix="plural-scaffold-") as temporary:
    root = Path(temporary)
    environment = root / "environment"
    verifier = root / "verifier.yaml"
    task = root / "task.yaml"
    harness = root / "harness"
    benchmark = root / "benchmark.yaml"
    agent = root / "agent.yaml"
    job = root / "job.yaml"
    call("env", "init", str(environment), "--name", "offline")
    call("verifier", "init", str(verifier), "--name", "offline-check")
    call(
        "task",
        "init",
        str(task),
        "--id",
        "offline-task",
        "--environment",
        str(environment),
        "--verifier",
        str(verifier),
    )
    call("harness", "init", str(harness), "--name", "offline-loop")
    call("benchmark", "init", str(benchmark), "--task", str(task))
    call(
        "agent",
        "init",
        str(agent),
        "--model",
        "offline/model",
        "--harness",
        str(harness),
    )
    call(
        "job",
        "init",
        str(job),
        "--source",
        str(benchmark),
        "--agent",
        str(agent),
    )
    plan = json.loads(call("run", str(job), "--dry-run"))
    assert plan["trial_count"] == 1
    print(f"scaffolded and planned {plan['job_id']}")
