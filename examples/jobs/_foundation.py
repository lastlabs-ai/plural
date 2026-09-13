"""Shared builders for credential-free public Job examples."""

from __future__ import annotations

from pathlib import Path

from plural import (
    Benchmark,
    CatalogContext,
    Environment,
    EvidenceContract,
    ExecutionTarget,
    Job,
    JobStore,
    ModelCatalog,
    ModelSpec,
    NetworkMode,
    Runtime,
    Task,
)
from plural.cli.scaffold import load_harness
from plural.verifiers import DeterministicVerifier, VerifierRuntime

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
    store: JobStore | None = None,
) -> Job:
    """Build a complete public Job around the example Harness.

    Returns:
        A planned Job ready for local execution.
    """
    harness = load_harness(HARNESS)
    isolated = provider != "local"
    environment = Environment(
        name="offline-example",
        version="1.0.0",
        overview="A deterministic offline execution runtime.",
        runtime=Runtime(
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
        check=("python", "-c", VERIFY),
        runtime=VerifierRuntime(
            provider=provider,
            image="python:3.12-slim" if provider in {"docker", "daytona"} else None,
            network=NetworkMode.NONE if isolated else NetworkMode.FULL,
        ),
        evidence=EvidenceContract(artifacts=("evidence.txt",)),
    )
    tasks = tuple(
        Task(
            name=task_id,
            instructions=f"Return a deterministic response for {value}.",
            info={"value": value},
            environment=environment,
            verifiers=(verifier,),
        )
        for task_id, value in (("one", "hello"), ("two", "world"))
    )
    benchmark = Benchmark(name="offline-smoke", version="1.0.0", tasks=tasks)
    context = CatalogContext(ModelCatalog(entries=[ModelSpec(id="offline/deterministic")]))
    agent = context.agent(
        name="offline-agent",
        model="offline/deterministic",
        harness=harness,
        auth_mode="none",
    )
    return Job(
        benchmark,
        agents=(agent,),
        attempts=attempts,
        concurrency=concurrency,
        per_runtime_concurrency=concurrency,
        catalog=context.catalog,
        store=store,
    )
