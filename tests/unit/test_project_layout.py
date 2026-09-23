"""Project discovery, the standard layout, and scaffolding."""

from __future__ import annotations

from pathlib import Path

import pytest
from project_fixtures import write_project
from typer.testing import CliRunner

from plural.cli.main import app
from plural.project import Project, ProjectError, ResourceRef, Workspace, check_name

runner = CliRunner()

ENVIRONMENT_README_SECTIONS = (
    "Overview",
    "Actions",
    "State",
    "Observations",
    "Rewards",
    "Resources",
    "Runtime",
    "Settings",
)


def invoke(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def test_project_init_creates_the_standard_structure_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    code, output = invoke("project", "init", "support-desk")
    assert code == 0, output
    root = tmp_path / "support-desk"
    for name in ("project.yaml", "plural.lock", "pyproject.toml", "README.md", ".gitignore"):
        assert (root / name).is_file(), name
    assert ".plural/" in (root / ".gitignore").read_text()
    assert Project.at(root).name == "support-desk"

    monkeypatch.chdir(root)
    for command in (
        ("env", "init", "queue"),
        ("verifier", "init", "resolved"),
        ("task", "init", "refund", "--environment", "queue", "--verifier", "resolved"),
        ("harness", "init", "loop"),
        ("agent", "init", "careful", "--model", "openai/gpt-5.6-luna"),
        ("benchmark", "init", "basics"),
    ):
        code, output = invoke(*command)
        assert code == 0, output
    expected = (
        "environments/queue/environment.yaml",
        "environments/queue/environment.py",
        "environments/queue/README.md",
        "tasks/refund/task.yaml",
        "tasks/refund/instruction.md",
        "verifiers/resolved/verifier.yaml",
        "verifiers/resolved/verify.py",
        "harnesses/loop/harness.yaml",
        "agents/careful/agent.yaml",
        "benchmarks/basics/benchmark.yaml",
        "benchmarks/basics/README.md",
    )
    for relative in expected:
        assert (root / relative).is_file(), relative
    readme = (root / "environments/queue/README.md").read_text()
    for section in ENVIRONMENT_README_SECTIONS:
        assert f"## {section}" in readme
    assert not (home / "credentials.json").exists()


def test_every_scaffold_fails_validation_with_a_useful_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    invoke("project", "init", "desk")
    monkeypatch.chdir(tmp_path / "desk")
    invoke("env", "init", "queue")
    invoke("verifier", "init", "resolved")
    invoke("task", "init", "refund")
    invoke("benchmark", "init", "basics")

    code, output = invoke("env", "validate", "queue")
    assert code == 1
    assert "README.md" in output and "unfinished scaffold" in output

    code, output = invoke("task", "validate", "refund")
    assert code == 1
    assert "instruction.md" in output
    assert "--environment" in output or "environment" in output

    code, output = invoke("benchmark", "validate", "basics")
    assert code == 1
    assert "plural benchmark add" in output


def test_commands_find_the_project_from_any_descendant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    write_project(tmp_path / "desk")
    nested = tmp_path / "desk" / "environments" / "queue" / "resources"
    monkeypatch.chdir(nested)
    code, output = invoke("task", "validate", "refund")
    assert code == 0, output
    assert "task/refund is valid" in output

    monkeypatch.chdir(tmp_path / "desk" / "tasks" / "refund")
    code, output = invoke("task", "validate")
    assert code == 0, output
    code, output = invoke("env", "validate")
    assert code == 1
    assert "Name the Environment" in output


def test_resource_commands_outside_a_project_explain_how_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    code, output = invoke("task", "list")
    assert code == 1
    assert "not inside a Plural project" in output
    assert "plural project init" in output


def test_project_init_leaves_an_existing_project_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    project = write_project(tmp_path / "support-desk")
    readme = project.root / "README.md"
    readme.write_text("my notes\n")
    before = {p: p.read_bytes() for p in project.root.rglob("*") if p.is_file()}

    monkeypatch.chdir(project.root / "tasks")
    code, output = invoke("project", "init", "support-desk")
    assert code == 0, output
    assert "already exists" in output
    after = {p: p.read_bytes() for p in project.root.rglob("*") if p.is_file()}
    assert after == before

    code, output = invoke("project", "init", "other")
    assert code == 1
    assert "cannot be nested" in output


@pytest.mark.parametrize("name", ["Support", "support_desk", "-desk", "desk-", "a" * 64, ""])
def test_names_must_already_be_hosted_slugs(name: str) -> None:
    with pytest.raises(ProjectError):
        check_name(name, "project")


def test_resource_init_refuses_to_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    write_project(tmp_path / "desk")
    monkeypatch.chdir(tmp_path / "desk")
    code, output = invoke("task", "init", "refund")
    assert code == 1
    assert "already exists" in output
    assert "Review order A-1" in (tmp_path / "desk/tasks/refund/instruction.md").read_text()


def test_sdk_and_cli_load_the_same_objects(tmp_path: Path, home: Path) -> None:
    project = write_project(tmp_path / "desk")
    workspace = Workspace(project)
    task = workspace.load(ResourceRef("task", "refund"))
    again = Workspace(Project.find(project.root / "tasks")).load(ResourceRef("task", "refund"))
    assert task.content_hash == again.content_hash
    assert [str(item) for item in task.dependencies] == ["environment/queue", "verifier/resolved"]
