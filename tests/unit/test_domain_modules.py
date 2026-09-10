from __future__ import annotations

import plural
from plural.agents import AgentBinding, AgentDefinition
from plural.agents.models import AgentDefinition as ModelAgentDefinition
from plural.environments.manifest import EnvironmentManifest
from plural.jobs import JobSpec, TaskJobSource
from plural.tasks import TaskDefinition
from plural.verifiers import DeterministicVerifier, WeightedVerifier


def test_task_contract_is_available_from_focused_module() -> None:
    assert TaskDefinition is plural.TaskDefinition
    assert TaskDefinition.__module__ == "plural.tasks"


def test_verifier_contract_is_available_from_focused_module() -> None:
    assert WeightedVerifier is plural.WeightedVerifier
    assert WeightedVerifier.__module__ == "plural.verifiers"


def test_agent_contract_preserves_package_and_models_imports() -> None:
    assert AgentDefinition is plural.AgentDefinition
    assert AgentDefinition is ModelAgentDefinition
    assert AgentDefinition.__module__ == "plural.agents.models"


def test_job_contract_consumes_focused_domain_modules() -> None:
    environment = EnvironmentManifest(name="world")
    verifier = DeterministicVerifier(name="exact", command=("python", "verify.py"))
    task = TaskDefinition(
        task_id="hello",
        instructions="Say hello.",
        environment=environment,
        verifiers=(WeightedVerifier(verifier=verifier),),
    )
    spec = JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="candidate", model="test/model")),),
    )

    assert JobSpec is plural.JobSpec
    assert JobSpec.__module__ == "plural.jobs"
    assert spec.plan().trial_count == 1
