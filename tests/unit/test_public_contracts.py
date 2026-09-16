from __future__ import annotations

import pytest
from pydantic import ValidationError

from plural.agents import AgentBinding, AgentDefinition
from plural.common import (
    ExecutionTarget,
    HarnessBinding,
    HarnessCapability,
    HarnessDefinition,
    HarnessPackage,
    PackageSource,
)
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.jobs import (
    BenchmarkJobSource,
    JobMode,
    JobSpec,
    TaskJobSource,
    TITORecord,
    resolve_trial_harness_grant,
)
from plural.sandbox import NetworkMode
from plural.tasks import BenchmarkDefinition, TaskDefinition
from plural.verifiers import DeterministicVerifier, WeightedVerifier


def verifier(name: str = "exact") -> DeterministicVerifier:
    return DeterministicVerifier(name=name, command=("python", "verify.py"))


def task(name: str, environment: EnvironmentDefinition) -> TaskDefinition:
    return TaskDefinition(
        task_id=name,
        instructions=f"Solve {name}.",
        environment=environment,
        verifiers=(WeightedVerifier(verifier=verifier(f"verify-{name}")),),
        info={"value": name},
    )


def test_v2_environment_rejects_v1_owned_fields() -> None:
    for field in ("tasks", "verifier", "mode"):
        with pytest.raises(ValidationError, match="cannot own"):
            EnvironmentDefinition.model_validate(
                {"schema_version": "2", "name": "world", field: []}
            )
    with pytest.raises(ValidationError, match="schema-v1 Environment"):
        EnvironmentDefinition.model_validate({"schema_version": "1", "name": "world"})


def test_task_state_is_validated_and_kept_off_the_public_payload() -> None:
    environment = EnvironmentDefinition(
        name="wordle",
        state_schema={
            "type": "object",
            "properties": {
                "secret": {"type": "string", "x-plural-hidden": True},
                "remaining": {"type": "integer", "default": 6},
            },
        },
    )
    with pytest.raises(ValidationError, match="expected string, got integer"):
        TaskDefinition(
            task_id="hard-01",
            instructions="Guess.",
            environment=environment,
            verifiers=(WeightedVerifier(verifier=verifier()),),
            state={"secret": 1},
        )
    with pytest.raises(ValidationError, match="does not define: 'leftover'"):
        TaskDefinition(
            task_id="hard-01",
            instructions="Guess.",
            environment=environment,
            verifiers=(WeightedVerifier(verifier=verifier()),),
            state={"leftover": True},
        )
    value = TaskDefinition(
        task_id="hard-01",
        instructions="Guess.",
        environment=environment,
        verifiers=(WeightedVerifier(verifier=verifier()),),
        state={"secret": "heart"},
    )
    assert value.state == {"secret": "heart"}
    assert "secret" not in value.public_payload


def test_task_pins_environment_and_weighted_verifiers() -> None:
    environment = EnvironmentDefinition(name="world")
    value = task("one", environment)
    assert value.environment.identity == environment.identity
    assert value.verifiers[0].weight == 1
    assert "environment" in value.model_dump()


def test_agent_is_not_environment_bound_and_stamp_is_per_trial() -> None:
    package = HarnessPackage(
        definition=HarnessDefinition(
            name="web",
            implementation="runnable",
            command=("python", "run.py"),
            capabilities=frozenset({HarnessCapability.SHELL, HarnessCapability.WEB_SEARCH}),
        ),
        source=PackageSource(kind="local", uri=".", unsafe_local=True),
    )
    agent = AgentDefinition(
        name="candidate",
        model="test/model",
        harness=HarnessBinding.from_package(package),
        harness_package=package,
    )
    isolated = EnvironmentDefinition(
        name="isolated",
        runtime=EnvironmentRuntime(network=NetworkMode.NO_NETWORK),
    )
    open_environment = EnvironmentDefinition(
        name="open",
        runtime=EnvironmentRuntime(network=NetworkMode.FULL),
    )
    isolated_grant = resolve_trial_harness_grant(isolated, agent)
    open_grant = resolve_trial_harness_grant(open_environment, agent)
    assert isolated_grant is not None
    assert open_grant is not None
    assert HarnessCapability.WEB_SEARCH in isolated_grant.denied
    assert HarnessCapability.WEB_SEARCH in open_grant.granted
    assert "environment" not in AgentDefinition.model_json_schema()["properties"]


def test_cross_environment_benchmark_plans_agent_task_attempts() -> None:
    first = EnvironmentDefinition(name="first")
    second = EnvironmentDefinition(
        name="second",
        runtime=EnvironmentRuntime(
            provider="daytona",
            targets=frozenset({ExecutionTarget.REMOTE}),
        ),
    )
    benchmark = BenchmarkDefinition(
        name="mixed",
        tasks=(task("a", first), task("b", second)),
    )
    spec = JobSpec(
        source=BenchmarkJobSource(benchmark=benchmark),
        agents=(
            AgentBinding(agent=AgentDefinition(name="one", model="test/one")),
            AgentBinding(agent=AgentDefinition(name="two", model="test/two")),
        ),
        attempts=2,
        concurrency=4,
        per_runtime_concurrency=1,
    )
    plan = spec.plan()
    assert plan.trial_count == 8
    assert [item.runtime_provider for item in plan.trials[:4]] == [
        "docker",
        "docker",
        "daytona",
        "daytona",
    ]
    assert len(plan.lock.environment_digests) == 2
    assert plan.lock.mode is JobMode.EVAL


def test_task_job_and_retry_do_not_change_trial_identity() -> None:
    selected = task("one", EnvironmentDefinition(name="world"))
    base = JobSpec(
        source=TaskJobSource(task=selected),
        agents=(AgentBinding(agent=AgentDefinition(name="one", model="test/one")),),
    )
    retried = base.model_copy(update={"retry": base.retry.model_copy(update={"max_retries": 5})})
    assert base.plan().trials[0].trial_id == retried.plan().trials[0].trial_id
    assert base.content_hash != retried.content_hash


def test_tito_record_validates_exact_output_lengths() -> None:
    valid = TITORecord(
        step=0,
        tokenizer="tok",
        model="model",
        input_token_ids=(1, 2),
        output_token_ids=(3,),
        observation_token_ids=(4,),
        output_logprobs=(-0.1,),
        output_top_logprobs=({"x": -0.1},),
        output_text="x",
        assistant_message={"role": "assistant", "content": "x"},
        input_len=2,
        output_len=1,
        observation_len=1,
    )
    assert valid.output_token_ids == (3,)
    with pytest.raises(ValidationError, match="lengths must match"):
        valid.model_copy(update={"output_logprobs": ()}).model_validate(
            {**valid.model_dump(), "output_logprobs": []}
        )
