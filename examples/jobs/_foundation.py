"""Shared builders for credential-free package execution examples."""

from __future__ import annotations

from pathlib import Path

from plural import (
    AgentSpec,
    BenchmarkDefinition,
    EnvironmentManifest,
    HarnessBinding,
    JobSpec,
    NetworkMode,
    RuntimeSpec,
    TaskDefinition,
    VerifierManifest,
)
from plural.cli.scaffold import load_harness
from plural.harness import tree_digest

ROOT = Path(__file__).parent
HARNESS = ROOT / "minimal_harness"
VERIFY = (
    "import json,pathlib; "
    "p=pathlib.Path('artifacts/evidence.txt'); "
    "pathlib.Path('verifier-result.json').write_text("
    "json.dumps({'reward':1.0,'scores':{'present':1.0},'evidence':[p.read_text()]})+'\\n')"
)


def build_job(
    *,
    provider: str = "local",
    n_attempts: int = 1,
    concurrency: int = 1,
    with_verifier: bool | None = None,
) -> JobSpec:
    """Build a complete immutable job around the example harness."""
    loaded = load_harness(HARNESS)
    package = loaded.model_copy(
        update={"source": loaded.source.model_copy(update={"digest": tree_digest(HARNESS)})}
    )
    binding = HarnessBinding.from_package(package)
    verifier_enabled = provider != "local" if with_verifier is None else with_verifier
    environment = EnvironmentManifest(
        name="offline-example",
        revision="1.0.0",
        instructions="Return a deterministic response for the task.",
        tasks=(
            TaskDefinition(task_id="one", input="hello", expected="hello"),
            TaskDefinition(task_id="two", input="world", expected="world"),
        ),
        allowed_harnesses=(binding,),
        verifier=(
            VerifierManifest(
                command=("python", "-c", VERIFY),
                required_artifacts=("evidence.txt",),
            )
            if verifier_enabled
            else None
        ),
    )
    benchmark = BenchmarkDefinition(
        name="offline-smoke",
        environment=environment.identity,
        task_ids=("one", "two"),
    )
    agent = AgentSpec(
        name="offline-agent",
        model="offline/deterministic",
        environment=environment.identity,
        harness=binding,
        harness_package=package,
        auth_mode="none",
    )
    runtime = RuntimeSpec(
        provider=provider,
        image="python:3.12-slim" if provider in {"docker", "daytona"} else None,
        network=NetworkMode.NONE if provider != "local" else NetworkMode.FULL,
        unsafe_local=provider == "local",
    )
    return JobSpec(
        environment=environment,
        benchmark=benchmark,
        agents=(agent,),
        n_attempts=n_attempts,
        concurrency=concurrency,
        per_agent_concurrency=concurrency,
        runtime=runtime,
    )
