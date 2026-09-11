"""Shared builders for credential-free package execution examples."""

from __future__ import annotations

from pathlib import Path

from plural import (
    AgentBinding,
    AgentDefinition,
    BenchmarkDefinition,
    BenchmarkJobSource,
    DeterministicVerifier,
    EnvironmentDefinition,
    EnvironmentRuntime,
    ExecutionTarget,
    HarnessBinding,
    JobSpec,
    NetworkMode,
    TaskDefinition,
    VerifierRuntime,
    WeightedVerifier,
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
    attempts: int = 1,
    concurrency: int = 1,
) -> JobSpec:
    """Build a complete immutable job around the example harness."""
    loaded = load_harness(HARNESS)
    package = loaded.model_copy(
        update={"source": loaded.source.model_copy(update={"digest": tree_digest(HARNESS)})}
    )
    binding = HarnessBinding.from_package(package)
    isolated = provider != "local"
    environment = EnvironmentDefinition(
        name="offline-example",
        revision="1.0.0",
        overview="A deterministic offline execution runtime.",
        runtime=EnvironmentRuntime(
            provider=provider,
            image="python:3.12-slim" if provider in {"docker", "daytona"} else None,
            network=NetworkMode.NONE if isolated else NetworkMode.FULL,
            targets=frozenset(
                {ExecutionTarget.LOCAL, ExecutionTarget.DOCKER, ExecutionTarget.REMOTE}
                if provider == "local"
                else {ExecutionTarget.DOCKER, ExecutionTarget.REMOTE}
            ),
            allow_unsafe_local=provider == "local",
        ),
    )
    verifier = DeterministicVerifier(
        name="evidence-present",
        command=("python", "-c", VERIFY),
        runtime=VerifierRuntime(
            provider=provider,
            image="python:3.12-slim" if provider in {"docker", "daytona"} else None,
            network=NetworkMode.NONE if isolated else NetworkMode.FULL,
        ),
        required_artifacts=("evidence.txt",),
    )
    tasks = tuple(
        TaskDefinition(
            task_id=task_id,
            instructions=f"Return a deterministic response for {value}.",
            info={"value": value},
            environment=environment,
            verifiers=(WeightedVerifier(verifier=verifier),),
        )
        for task_id, value in (("one", "hello"), ("two", "world"))
    )
    benchmark = BenchmarkDefinition(
        name="offline-smoke",
        tasks=tasks,
    )
    agent = AgentBinding(
        agent=AgentDefinition(
            name="offline-agent",
            model="offline/deterministic",
            harness=binding,
            harness_package=package,
            auth_mode="none",
        )
    )
    return JobSpec(
        source=BenchmarkJobSource(benchmark=benchmark),
        agents=(agent,),
        attempts=attempts,
        concurrency=concurrency,
        per_runtime_concurrency=concurrency,
    )
