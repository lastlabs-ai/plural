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
    "Apps",
    "Actions",
    "State",
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
        "environments/queue/server.py",
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


def test_a_new_environment_runs_at_once_with_a_starter_task_and_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    invoke("project", "init", "desk")
    root = tmp_path / "desk"
    monkeypatch.chdir(root)

    code, output = invoke("env", "init", "queue")

    assert code == 0, output
    assert "plural run --task queue-first --model" in output
    for relative in (
        "environments/queue/resources/policy.md",
        "tasks/queue-first/instruction.md",
        "verifiers/queue-check/verify.py",
    ):
        assert (root / relative).is_file(), relative
    environment = (root / "environments/queue/environment.yaml").read_text()
    assert "provider: local" in environment and "resources/policy.md" in environment

    code, output = invoke("task", "validate", "queue-first")
    assert code == 0, output
    assert "unfinished" in output
    assert "environments/queue/server.py:" in output
    assert "tasks/queue-first/instruction.md:" in output
    workspace = Workspace(Project.at(root))
    task = workspace.load(ResourceRef("task", "queue-first")).value
    assert task.initial_state == {"expected": "store credit"}

    code, output = invoke("env", "init", "bare", "--bare")
    assert code == 0, output
    assert not (root / "tasks/bare-first").exists()


def test_unfinished_work_runs_locally_but_is_never_pushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    from plural.project.sync import plan_project_push

    monkeypatch.chdir(tmp_path)
    invoke("project", "init", "desk")
    root = tmp_path / "desk"
    monkeypatch.chdir(root)
    invoke("env", "init", "queue")
    workspace = Workspace(Project.at(root))

    with pytest.raises(ProjectError) as raised:
        plan_project_push(workspace, None, None, roots=[ResourceRef("task", "queue-first")])
    assert any("server.py:" in item and "unfinished" in item for item in raised.value.problems)

    for directory in ("environments/queue", "tasks/queue-first", "verifiers/queue-check"):
        for path in (root / directory).rglob("*"):
            if path.suffix in {".py", ".md", ".yaml"}:
                lines = path.read_text().splitlines(keepends=True)
                path.write_text("".join(line for line in lines if "PLURAL-TODO" not in line))
    plan = plan_project_push(
        Workspace(Project.at(root)), None, None, roots=[ResourceRef("task", "queue-first")]
    )
    assert {step.action for step in plan.steps} == {"new"}


def test_a_tracked_run_refuses_unfinished_work_before_it_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    invoke("project", "init", "desk")
    monkeypatch.chdir(tmp_path / "desk")
    invoke("env", "init", "queue")

    code, output = invoke(
        "run", "--task", "queue-first", "--model", "openai/gpt-5.6-luna", "--track"
    )

    assert code != 0
    assert "--track" in output and "unfinished" in output
    assert "server.py:" in output
    assert not (tmp_path / "desk/.plural/jobs").exists()


def test_a_broken_dependency_lists_its_problems_beneath_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    invoke("project", "init", "desk")
    root = tmp_path / "desk"
    monkeypatch.chdir(root)
    invoke("env", "init", "queue")
    invoke("benchmark", "init", "basics")
    invoke("benchmark", "add", "queue-first", "--benchmark", "basics")
    (root / "environments/queue/environment.yaml").write_text("name: queue\napps: 3\n")

    code, output = invoke("benchmark", "validate", "basics")

    assert code == 1
    assert (
        "  - depends on task 'queue-first', which is not valid:\n"
        "    - depends on environment 'queue', which is not valid:\n"
        "        - apps:"
    ) in output


def test_an_unfinished_benchmark_still_explains_what_it_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    invoke("project", "init", "desk")
    monkeypatch.chdir(tmp_path / "desk")
    invoke("benchmark", "init", "basics")

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
