from __future__ import annotations

from typing import Any

from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.tasks import Task
from plural.verifiers import DeterministicVerifier


class _FakeRevisionAPI:
    def __init__(self) -> None:
        self.get_calls: list[str] = []

    def get(self, reference: str) -> dict[str, Any]:
        self.get_calls.append(reference)
        return {
            "id": f"{reference}-parent",
            "slug": reference,
            "current_revision_id": f"{reference}-revision",
        }

    def revision(self, parent_id: str, revision_id: str) -> dict[str, Any]:
        return {"id": revision_id, "parent": parent_id, "definition": {}}


class _FakeTasksAPI(_FakeRevisionAPI):
    def __init__(self) -> None:
        super().__init__()
        self.pushed: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def push(self, value: Any, **references: Any) -> dict[str, Any]:
        self.pushed.append({"value": value, "references": references})
        return {"id": "task-revision", "status": "published"}

    def delete(self, resource_id: str) -> None:
        self.deleted.append(resource_id)


class _FakeClient:
    def __init__(self) -> None:
        self.environments = _FakeRevisionAPI()
        self.verifiers = _FakeRevisionAPI()
        self.tasks = _FakeTasksAPI()


def _task() -> Task:
    environment = EnvironmentDefinition(
        name="World", overview="World", runtime=EnvironmentRuntime()
    )
    verifier = DeterministicVerifier(name="correct", check=("python", "verify.py"))
    return Task(
        name="demo-task",
        instructions="Do the thing.",
        environment=environment,
        verifiers=[verifier],
    )


def test_definition_matches_internal_contract() -> None:
    task = _task()

    assert task.definition() == task._definition()


def test_tasks_are_pushed_from_projects_not_objects() -> None:
    task = _task()
    assert not hasattr(task, "push")
    assert not hasattr(task, "delete")


def test_an_answer_key_changes_the_task_but_never_reaches_the_agent() -> None:
    from plural.execution.apps import host_inputs

    plain = _task()
    keyed = plain.model_copy(update={"expected": "billing"})

    assert "expected" not in plain.model_dump()
    assert "expected" not in plain.definition().model_dump()
    assert keyed.content_hash != plain.content_hash
    assert keyed.definition().content_hash != plain.definition().content_hash
    assert keyed.definition().expected == "billing"
    assert "billing" not in str(keyed.public_payload)
    assert "billing" not in str(keyed.definition().public_payload)
    assert host_inputs(keyed.definition(), seed=1)["expected"] == "billing"
