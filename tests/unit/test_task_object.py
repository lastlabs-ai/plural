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
        return {"id": "task-revision", "status": "draft"}

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


def test_push_resolves_current_revisions_by_name() -> None:
    client = _FakeClient()

    record = _task().push(client)  # type: ignore[arg-type]

    assert record == {"id": "task-revision", "status": "draft"}
    assert client.environments.get_calls == ["world"]
    assert client.verifiers.get_calls == ["correct"]
    assert client.tasks.pushed[0]["references"] == {
        "environment_revision_id": "world-revision",
        "verifier_revision_ids": ["correct-revision"],
    }


def test_push_honors_explicit_revision_ids() -> None:
    client = _FakeClient()

    _task().push(
        client,  # type: ignore[arg-type]
        environment_revision_id="env-explicit",
        verifier_revision_ids=["verifier-explicit"],
    )

    assert client.environments.get_calls == []
    assert client.verifiers.get_calls == []
    assert client.tasks.pushed[0]["references"] == {
        "environment_revision_id": "env-explicit",
        "verifier_revision_ids": ["verifier-explicit"],
    }


def test_delete_removes_hosted_parent_by_slug() -> None:
    client = _FakeClient()

    _task().delete(client)  # type: ignore[arg-type]

    assert client.tasks.deleted == ["demo-task"]
