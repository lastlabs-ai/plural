from __future__ import annotations

import pytest
from pydantic import ValidationError

import plural
from plural import Agent, Benchmark, Environment, Job, Task
from plural.common import HarnessDefinition, HarnessPackage, PackageSource
from plural.verifiers import (
    AgentVerifier,
    DeterministicVerifier,
    HumanVerifier,
    RubricCriterion,
)


def solved(*, weight: float = 1) -> DeterministicVerifier:
    return DeterministicVerifier(
        name="solved",
        check="python verifier.py",
        criteria=(RubricCriterion(name="correct", description="The answer is correct."),),
        weight=weight,
    )


def task(name: str, *, version: str = "0.1.0") -> Task:
    return Task(
        name=name,
        version=version,
        instructions=f"Solve {name}.",
        goals=("Return the correct answer.",),
        environment=Environment(name="world", version="1.0.0"),
        verifiers=(solved(weight=2),),
        initial_state={},
        reset_options={"seed": 7},
    )


def test_public_exports_use_plain_domain_names() -> None:
    for name in ("Agent", "Benchmark", "Environment", "Job", "Runtime", "Task"):
        assert name in plural.__all__
    assert not {
        "AgentDefinition",
        "AgentBinding",
        "BenchmarkDefinition",
        "EnvironmentDefinition",
        "JobSpec",
        "TaskDefinition",
        "VerifierDefinition",
        "WeightedVerifier",
        "native_actions_v1",
        "native_chat_v1",
    } & set(plural.__all__)


def test_agent_catalog_provider_fallback_and_single_harness() -> None:
    agent = Agent(
        model="openai/gpt-5.6-luna",
        provider="openai",
        fallback_models=("anthropic/claude-haiku-4-5",),
    )
    assert agent.name == "gpt-5.6-luna"
    assert agent.routing.provider == "openai"

    with pytest.raises(ValidationError, match="effective ModelCatalog"):
        Agent(model="not-registered/model")
    with pytest.raises(ValidationError, match="not a catalog endpoint"):
        Agent(model="openai/gpt-5.6-luna", provider="not-a-provider")
    with pytest.raises(ValidationError, match="fallback models"):
        Agent(
            model="openai/gpt-5.6-luna",
            fallback_models=("not-registered/fallback",),
        )

    harness = HarnessPackage(
        definition=HarnessDefinition(
            name="custom",
            implementation="runnable",
            command=("python", "harness.py"),
        ),
        source=PackageSource(kind="local", uri=".", unsafe_local=True),
    )
    harness_agent = Agent(model="openai/gpt-5.6-luna", harness=harness)
    planned = Job(task("harness"), agents=(harness_agent,)).spec.agents[0]
    assert planned.harness_package is harness
    assert planned.harness is not None
    with pytest.raises(ValidationError, match="harness_package"):
        Agent(
            model="openai/gpt-5.6-luna",
            harness=harness,
            harness_package=harness,  # type: ignore[call-arg]
        )


def test_verifier_contract_uses_check_criteria_and_catalog_models() -> None:
    deterministic = solved(weight=3)
    assert deterministic.check == ("python", "verifier.py")
    assert deterministic.command == deterministic.check
    assert deterministic.weight == 3

    criterion = RubricCriterion(name="quality", description="Response quality.")
    judge = AgentVerifier(
        name="judge",
        model="openai/gpt-5.6-luna",
        instructions="Judge the response.",
        criteria=(criterion,),
    )
    human = HumanVerifier(name="human", criteria=(criterion,))
    assert judge.rubric == judge.criteria
    assert human.rubric == human.criteria
    with pytest.raises(ValidationError, match="effective ModelCatalog"):
        AgentVerifier(
            name="judge",
            model="not-registered/model",
            instructions="Judge.",
            criteria=(criterion,),
        )


def test_task_compiles_python_environment_and_attaches_verifiers_directly() -> None:
    environment = Environment(name="world", version="1.2.3")
    verifier = solved(weight=2)
    value = Task(
        name="case-1",
        instructions="Solve it.",
        environment=environment,
        verifiers=(verifier,),
    )
    assert value.environment.version == "1.2.3"
    assert value.verifiers == (verifier,)
    assert value.verifiers[0].weight == 2
    planned = Job(value, agents=(Agent(model="openai/gpt-5.6-luna"),)).spec.tasks[0]
    assert planned.verifiers[0].weight == 2


def test_benchmark_requires_semver_and_exports_structured_diff() -> None:
    first = task("first")
    second = task("second")
    original = Benchmark(
        name="suite",
        version="1.0.0",
        tasks=(first, second),
        primary_metric="reward",
    )
    changed = Benchmark(
        name="suite",
        version="1.1.0",
        tasks=(second, task("first", version="0.2.0")),
        primary_metric="accuracy",
    )
    diff = original.diff(changed)
    assert [item.before.name for item in diff.updated] == ["first"]
    assert diff.reordered is True
    assert diff.configuration_changes["primary_metric"] == ("reward", "accuracy")
    assert original.export() == original.dependency_graph()
    assert original.export()["benchmark"]["task_pins"][0]["name"] == "first"
    planned = Job(original, agents=(Agent(model="openai/gpt-5.6-luna"),)).plan
    assert planned.lock.benchmark is not None
    assert planned.lock.benchmark.content_hash == original.content_hash
    assert planned.trials[0].task_pin.content_hash == first.content_hash
    with pytest.raises(ValidationError, match="semantic version"):
        Benchmark(name="suite", version="latest", tasks=(first,))


def test_public_job_plans_and_sync_run_rejects_running_loop() -> None:
    source = task("case")
    job = Job(source, agents=(Agent(model="openai/gpt-5.6-luna"),), attempts=2)
    assert job.plan.trial_count == 2
    assert job.plan().trial_count == 2
    assert job.plan.trials[0].task_pin.content_hash == source.content_hash

    async def call_sync_run() -> None:
        with pytest.raises(RuntimeError, match="run_async"):
            job.run()

    import asyncio

    asyncio.run(call_sync_run())
