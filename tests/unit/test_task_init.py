from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from plural.cli import resources as task_commands
from plural.cli.main import app
from plural.cli.scaffold import (
    init_task,
    load_task,
    load_task_for_push,
    scaffold_environment,
    scaffold_verifier,
    task_push_needs_remote,
)
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.errors import InvalidRequestError, NotFoundError
from plural.verifiers import DeterministicVerifier


class _FakeTasks:
    def __init__(self, *, existing: bool = False) -> None:
        self.existing = existing
        self.pushed: list[dict[str, Any]] = []

    def get(self, name: str) -> dict[str, Any]:
        if not self.existing:
            raise NotFoundError(f"task {name} not found", status_code=404)
        return {"id": "task-parent", "slug": name}

    def push(self, value: Any, **references: Any) -> dict[str, Any]:
        self.pushed.append({"value": value, "references": references})
        return {"id": "task-revision", "status": "draft"}


class _FakeRevisionAPI:
    def __init__(self, definition: dict[str, Any]) -> None:
        self.definition = definition

    def get(self, reference: str) -> dict[str, Any]:
        return {
            "id": f"{reference}-parent",
            "slug": reference,
            "current_revision_id": f"{reference}-revision",
        }

    def revision(self, parent_id: str, revision_id: str) -> dict[str, Any]:
        return {"id": revision_id, "parent": parent_id, "definition": self.definition}


class _FakeClient:
    def __init__(self, *, task_exists: bool = False) -> None:
        environment = EnvironmentDefinition(
            name="World", overview="World", runtime=EnvironmentRuntime()
        )
        verifier = DeterministicVerifier(name="correct", check=("python", "verify.py"))
        self.environments = _FakeRevisionAPI(environment.model_dump(mode="json"))
        self.verifiers = _FakeRevisionAPI(verifier.model_dump(mode="json"))
        self.tasks = _FakeTasks(existing=task_exists)

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _local_task_package(tmp_path: Path) -> Path:
    scaffold_environment(tmp_path / "environment", "world")
    scaffold_verifier(tmp_path / "verifier.yaml", name="correct")
    directory = tmp_path / "demo"
    created = init_task(
        "demo",
        environment=tmp_path / "environment",
        verifiers=[tmp_path / "verifier.yaml"],
        directory=directory,
    )
    assert [item.name for item in created] == ["instruction.md", "task.yaml", "resources"]
    (directory / "resources" / "notes.md").write_text("# notes\n", encoding="utf-8")
    return directory


def test_init_task_writes_bare_package(tmp_path: Path) -> None:
    directory = tmp_path / "bare"

    created = init_task("bare", bare=True, directory=directory)

    assert (directory / "instruction.md").read_text(encoding="utf-8") == ""
    assert list((directory / "resources").iterdir()) == []
    payload = yaml.safe_load((directory / "task.yaml").read_text(encoding="utf-8"))
    assert payload == {"kind": "task", "name": "bare", "version": "0.1.0"}
    assert [item.name for item in created] == ["instruction.md", "task.yaml", "resources"]


def test_task_directory_inlines_instructions_and_resources(tmp_path: Path) -> None:
    directory = _local_task_package(tmp_path)

    task = load_task(directory)

    assert "Replace this with what the agent should accomplish." in task.instructions
    assert task.state == {}
    assert task.info == {}
    assert len(task.resources) == 1
    resource = task.resources[0]
    assert resource.path == "resources/notes.md"
    assert resource.delivery == "inline"
    assert resource.content == "# notes\n"


def test_explicit_source_file_in_task_package_is_self_contained(tmp_path: Path) -> None:
    directory = _local_task_package(tmp_path)
    payload = yaml.safe_load((directory / "task.yaml").read_text(encoding="utf-8"))
    payload["resources"] = [
        {
            "kind": "file",
            "name": "notes",
            "path": "resources/notes.md",
            "delivery": "source",
        }
    ]
    (directory / "task.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    task = load_task(directory)

    assert task.resources[0].delivery == "inline"
    assert task.resources[0].content == "# notes\n"


def test_init_task_warns_when_slug_exists_without_prompt(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="already exists in the current project"):
        created = init_task(
            "demo",
            environment="test-env",
            client=_FakeClient(task_exists=True),  # type: ignore[arg-type]
            directory=tmp_path / "demo",
        )

    assert (tmp_path / "demo" / "task.yaml").is_file()
    assert len(created) == 3


def test_task_init_without_api_key_creates_locally(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["task", "init", "demo", "--bare"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "demo" / "task.yaml").is_file()
    assert "Remote task name was not checked" in result.output


def test_task_init_surfaces_missing_project_for_account_keys(
    tmp_path: Path, monkeypatch: Any
) -> None:
    class _MissingProjectTasks(_FakeTasks):
        def get(self, name: str) -> dict[str, Any]:
            raise InvalidRequestError("Project is required for account API keys")

    class _MissingProjectClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.tasks = _MissingProjectTasks()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLURAL_API_KEY", "account-key")
    monkeypatch.setattr(task_commands, "Client", lambda **_: _MissingProjectClient())

    result = CliRunner().invoke(app, ["task", "init", "demo"])

    assert result.exit_code == 2
    assert "Project is required for account API keys" in result.stderr
    assert not (tmp_path / "demo").exists()


def test_task_init_accepts_repeatable_verifier_slugs(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "task",
            "init",
            "demo",
            "--environment",
            "test-env",
            "--verifier",
            "first-check",
            "--verifier",
            "second-check",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load((tmp_path / "demo" / "task.yaml").read_text(encoding="utf-8"))
    assert payload["environment"] == "test-env"
    assert payload["verifiers"] == ["first-check", "second-check"]


def test_task_init_prompts_and_cancels_on_remote_collision(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLURAL_API_KEY", "test-key")
    monkeypatch.setattr(task_commands, "Client", lambda **_: _FakeClient(task_exists=True))

    result = CliRunner().invoke(app, ["task", "init", "demo"], input="n\n")

    assert result.exit_code == 0, result.output
    assert "already exists in the current project" in result.output
    assert not (tmp_path / "demo").exists()


def test_task_init_proceeds_after_confirming_remote_collision(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLURAL_API_KEY", "test-key")
    monkeypatch.setattr(task_commands, "Client", lambda **_: _FakeClient(task_exists=True))

    result = CliRunner().invoke(
        app, ["task", "init", "demo", "--environment", "test-env"], input="y\n"
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load((tmp_path / "demo" / "task.yaml").read_text(encoding="utf-8"))
    assert payload["environment"] == "test-env"


def test_task_push_resolves_slugs_to_current_revisions(tmp_path: Path, monkeypatch: Any) -> None:
    directory = tmp_path / "demo"
    init_task("demo", environment="test-env", verifiers=["test-verifier"], directory=directory)
    client = _FakeClient()
    monkeypatch.setattr(task_commands, "_client", lambda: client)

    result = CliRunner().invoke(app, ["task", "push", str(directory)])

    assert result.exit_code == 0, result.output
    assert task_push_needs_remote(directory)
    assert client.tasks.pushed[0]["references"] == {
        "environment_revision_id": "test-env-revision",
        "verifier_revision_ids": ["test-verifier-revision"],
    }


def test_task_push_accepts_explicit_revision_overrides(tmp_path: Path, monkeypatch: Any) -> None:
    directory = tmp_path / "demo"
    init_task("demo", environment="test-env", verifiers=["test-verifier"], directory=directory)
    client = _FakeClient()
    monkeypatch.setattr(task_commands, "_client", lambda: client)

    result = CliRunner().invoke(
        app,
        [
            "task",
            "push",
            str(directory),
            "--environment-revision-id",
            "env-explicit",
            "--verifier-revision-id",
            "verifier-explicit",
        ],
    )

    assert result.exit_code == 0, result.output
    assert client.tasks.pushed[0]["references"] == {
        "environment_revision_id": "env-explicit",
        "verifier_revision_ids": ["verifier-explicit"],
    }


def test_task_push_supports_local_files_with_explicit_revisions(tmp_path: Path) -> None:
    directory = _local_task_package(tmp_path)

    task, environment_revision_id, verifier_revision_ids = load_task_for_push(
        directory,
        environment_revision_id="env-explicit",
        verifier_revision_ids=["verifier-explicit"],
    )

    assert task.task_id == "demo"
    assert environment_revision_id == "env-explicit"
    assert verifier_revision_ids == ["verifier-explicit"]
    assert not task_push_needs_remote(directory)


def test_task_push_rejects_bare_package_without_bindings(tmp_path: Path, monkeypatch: Any) -> None:
    directory = tmp_path / "bare"
    init_task("bare", bare=True, directory=directory)
    client = _FakeClient()
    monkeypatch.setattr(task_commands, "_client", lambda: client)

    result = CliRunner().invoke(app, ["task", "push", str(directory)])

    assert result.exit_code == 2
    assert "must name an environment" in result.stderr
    assert client.tasks.pushed == []
