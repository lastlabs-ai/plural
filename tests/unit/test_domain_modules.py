from __future__ import annotations

import plural
from plural import Agent, Benchmark, Environment, Job, Runtime, Task
from plural.verifiers import DeterministicVerifier, Verifier


def test_plain_domain_contracts_are_top_level() -> None:
    assert Agent is plural.Agent
    assert Benchmark is plural.Benchmark
    assert Environment is plural.Environment
    assert Job is plural.Job
    assert Runtime is plural.Runtime
    assert Task is plural.Task
    assert Verifier is plural.Verifier


def test_internal_contract_names_are_not_top_level() -> None:
    assert not {
        "AgentBinding",
        "AgentDefinition",
        "BenchmarkDefinition",
        "EnvironmentDefinition",
        "JobSpec",
        "TaskDefinition",
        "VerifierDefinition",
        "WeightedVerifier",
        "native_actions_v1",
        "native_chat_v1",
    } & set(plural.__all__)


def test_job_contract_plans_public_objects() -> None:
    environment = Environment(name="world", runtime=Runtime.docker())
    verifier = DeterministicVerifier(name="exact", check="python verify.py")
    task = Task(
        name="hello",
        instructions="Say hello.",
        environment=environment,
        verifiers=(verifier,),
    )
    agent = Agent(model="openai/gpt-5.6-luna")
    job = Job(task, agents=(agent,))

    assert job.plan.trial_count == 1
    assert job.plan().trial_count == 1
