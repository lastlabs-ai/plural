"""Resource validation: required fields, references, and Benchmark rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from project_fixtures import write_project
from typer.testing import CliRunner

from plural import Agent, Harness
from plural.cli.main import app
from plural.project import Project, ProjectError, ResourceRef, Workspace
from plural.project.membership import add_task, remove_task

runner = CliRunner()


def load(project: Project, kind: str, name: str):  # noqa: ANN201
    return Workspace(project).load(ResourceRef(kind, name))


def problems(project: Project, kind: str, name: str) -> str:
    with pytest.raises(ProjectError) as caught:
        load(project, kind, name)
    return str(caught.value)


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new))


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return write_project(tmp_path / "desk")


def test_the_sample_project_is_valid(project: Project) -> None:
    workspace = Workspace(project)
    for kind, name in (
        ("environment", "queue"),
        ("verifier", "resolved"),
        ("task", "refund"),
        ("harness", "scripted"),
        ("agent", "baseline"),
        ("benchmark", "basics"),
    ):
        resource = workspace.load(ResourceRef(kind, name))
        assert resource.version == "0.1.0"
        assert resource.content_hash.startswith("sha256:")


def test_python_sdk_addresses_resources_like_the_cli(project: Project) -> None:
    from plural import Benchmark, Task

    workspace = Workspace(project)
    assert (
        workspace.get("env", "queue") is workspace.load(ResourceRef("environment", "queue")).value
    )
    assert isinstance(workspace.get("task", "refund"), Task)
    assert isinstance(workspace.get("benchmark", "basics"), Benchmark)
    with pytest.raises(ProjectError, match="unknown resource kind"):
        workspace.get("job", "refund")
    with pytest.raises(ProjectError, match="plural task init missing"):
        workspace.get("task", "missing")


def test_a_python_job_with_a_deterministic_verifier_resumes_its_own_store(
    project: Project, tmp_path: Path
) -> None:
    from plural import Job
    from plural.execution.store import JobStore

    workspace = Workspace(project)
    store = JobStore(tmp_path / "jobs")

    def job() -> Job:
        return Job(
            workspace.get("task", "refund"),
            agents=[workspace.get("agent", "baseline")],
            store=store,
        )

    first, second = job().run(), job().run()
    assert first.job_id == second.job_id

    config = store.job_path(first.job_id) / "config.json"
    stored = json.loads(config.read_text())
    stored["source"]["task"]["verifiers"][0]["verifier"]["check"]["digest"] = "sha256:" + "0" * 64
    config.write_text(json.dumps(stored))
    with pytest.raises(ValueError, match="lock_incompatible"):
        job().run()


def test_task_needs_instructions_one_environment_and_a_verifier(project: Project) -> None:
    task = project.root / "tasks/refund"
    (task / "instruction.md").write_text("   \n")
    assert "instruction.md is empty" in problems(project, "task", "refund")

    (task / "instruction.md").write_text("Refund it.\n")
    edit(task / "task.yaml", "environment: queue\n", "")
    message = problems(project, "task", "refund")
    assert "environment" in message and "plural env init" in message

    edit(task / "task.yaml", "verifiers:\n  - resolved\n", "verifiers: []\n")
    (task / "task.yaml").write_text((task / "task.yaml").read_text() + "environment: queue\n")
    assert "verifier" in problems(project, "task", "refund").lower()

    edit(task / "task.yaml", "verifiers: []\n", "verifiers:\n  - missing\n")
    message = problems(project, "task", "refund")
    assert "verifier/missing" in message or "'missing'" in message

    edit(task / "task.yaml", "environment: queue\n", "environment: [queue, other]\n")
    edit(task / "task.yaml", "  - missing\n", "  - resolved\n")
    assert "environment" in problems(project, "task", "refund")


def test_task_resources_cannot_escape_the_task_directory(project: Project) -> None:
    task = project.root / "tasks/refund/task.yaml"
    task.write_text(task.read_text() + "resources:\n  - ../deny/instruction.md\n")
    assert "inside" in problems(project, "task", "refund")


def test_unresolved_references_are_reported_before_any_code_runs(project: Project) -> None:
    environment = project.root / "environments/queue/environment.py"
    environment.write_text("raise RuntimeError('imported')\n")
    edit(project.root / "tasks/deny/task.yaml", "environment: queue", "environment: nowhere")
    workspace = Workspace(project)
    with pytest.raises(ProjectError) as caught:
        workspace.dependency_order([ResourceRef("benchmark", "basics")])
    assert "environment/nowhere" in str(caught.value)
    assert "imported" not in str(caught.value)


def test_dependency_cycles_are_detected(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    def cyclic(kind: str, payload: dict) -> tuple[ResourceRef, ...]:  # type: ignore[type-arg]
        if kind == "task":
            return (ResourceRef("benchmark", "basics"),)
        if kind == "benchmark":
            return (ResourceRef("task", "refund"),)
        return ()

    monkeypatch.setattr("plural.project.resources.declared_dependencies", cyclic)
    with pytest.raises(ProjectError, match="cycle"):
        Workspace(project).dependency_order([ResourceRef("benchmark", "basics")])


def test_benchmark_rules(project: Project) -> None:
    benchmark = project.root / "benchmarks/basics"
    (benchmark / "README.md").unlink()
    edit(benchmark / "benchmark.yaml", "purpose: Measures", "purpose: ''\n# Measures")
    edit(benchmark / "benchmark.yaml", "description: Share of orders", "description: ''\n  # Share")
    message = problems(project, "benchmark", "basics")
    assert "README.md" in message
    assert "purpose" in message
    assert "scoring.description" in message

    (benchmark / "README.md").write_text("# Basics\n")
    edit(benchmark / "benchmark.yaml", "purpose: ''", "purpose: Refund policy")
    edit(benchmark / "benchmark.yaml", "description: ''", "description: Correct share")
    edit(benchmark / "benchmark.yaml", "  - deny\n", "  - refund\n")
    assert "listed once" in problems(project, "benchmark", "basics")

    edit(benchmark / "benchmark.yaml", "  - refund\n  - refund\n", "  - refund\n")
    benchmark_yaml = benchmark / "benchmark.yaml"
    benchmark_yaml.write_text(benchmark_yaml.read_text() + "primary_metric: reward\n")
    assert "primary_metric" in problems(project, "benchmark", "basics")


def test_benchmark_rejects_verifiers_that_score_outside_its_range(project: Project) -> None:
    verifier = project.root / "verifiers/reviewer"
    verifier.mkdir()
    (verifier / "verifier.yaml").write_text(
        "name: reviewer\nversion: 0.1.0\nkind: human\n"
        "rubric:\n  - name: tone\n    description: Polite.\n    max_score: 5\n"
    )
    edit(project.root / "tasks/refund/task.yaml", "  - resolved\n", "  - resolved\n  - reviewer\n")
    load(project, "task", "refund")
    message = problems(project, "benchmark", "basics")
    assert "outside scoring.score_range" in message


def test_benchmark_membership_edits_keep_comments(project: Project) -> None:
    path = project.root / "benchmarks/basics/benchmark.yaml"
    remove_task(project, "basics", "deny")
    text = path.read_text()
    assert "  - deny" not in text
    assert "# Basics benchmark." in text and "# Ranking rules." in text
    assert add_task(project, "basics", "deny") is True
    assert add_task(project, "basics", "deny") is False
    assert path.read_text().count("  - deny") == 1
    with pytest.raises(ProjectError, match="plural task init"):
        add_task(project, "basics", "unknown")
    with pytest.raises(ProjectError, match="does not include"):
        remove_task(project, "basics", "unknown")
    load(project, "benchmark", "basics")


def test_benchmark_add_cli_infers_the_benchmark_and_stays_local(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    remove_task(project, "basics", "deny")
    monkeypatch.chdir(project.root / "benchmarks/basics")
    result = runner.invoke(app, ["benchmark", "add", "deny"])
    assert result.exit_code == 0, result.output
    assert "plural benchmark push basics" in result.output
    assert "  - deny" in (project.root / "benchmarks/basics/benchmark.yaml").read_text()


def test_agent_requires_a_catalog_model_and_resolves_harnesses(project: Project) -> None:
    agent = load(project, "agent", "baseline").value
    assert isinstance(agent, Agent)
    assert isinstance(agent.harness, Harness)

    path = project.root / "agents/baseline/agent.yaml"
    edit(
        path, "harness: scripted", "harness: claude-code\nharness_kwargs:\n  reasoning_effort: high"
    )
    edit(path, "model: openai/gpt-5.6-luna", "model: anthropic/claude-sonnet-5")
    edit(path, "auth_mode: none\n", "")
    builtin = load(project, "agent", "baseline")
    assert builtin.value.harness == "claude-code"
    assert builtin.dependencies == ()
    python_authored = Agent(
        name="baseline",
        version="0.1.0",
        model="anthropic/claude-sonnet-5",
        instructions="Follow the refund policy.",
        harness="claude-code",
        harness_kwargs={"reasoning_effort": "high"},
    )
    assert builtin.content_hash == python_authored.content_hash

    edit(path, "harness: claude-code", "harness: nowhere")
    assert "nowhere" in problems(project, "agent", "baseline")

    edit(path, "harness: nowhere", "harness: claude-code")
    edit(path, "model: anthropic/claude-sonnet-5", "model: nobody/unknown")
    assert "ModelCatalog" in problems(project, "agent", "baseline")


def test_local_harness_cannot_shadow_a_builtin(project: Project) -> None:
    source = project.root / "harnesses/scripted"
    source.rename(project.root / "harnesses/codex")
    edit(project.root / "harnesses/codex/harness.yaml", "name: scripted", "name: codex")
    assert "built-in Harness" in problems(project, "harness", "codex")


def test_invalid_local_resource_is_an_error_not_a_hosted_fallback(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    (project.root / "tasks/refund/instruction.md").write_text("")
    monkeypatch.chdir(project.root)
    result = runner.invoke(app, ["task", "show", "refund"])
    assert result.exit_code == 1
    assert "instruction.md is empty" in result.output
    assert "hosted" not in result.output.lower()


def test_show_and_list_label_local_resources(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(project.root)
    shown = runner.invoke(app, ["task", "show", "refund", "--json"])
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.output)
    assert payload["location"] == "local"
    assert payload["depends_on"] == ["environment/queue", "verifier/resolved"]
    assert payload["hosted"] == "not pushed"

    listed = runner.invoke(app, ["harness", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    locations = {(item["name"], item["location"]) for item in json.loads(listed.output)}
    assert ("scripted", "local") in locations
    assert ("claude-code", "built-in") in locations

    builtin = runner.invoke(app, ["harness", "show", "codex", "--json"])
    assert builtin.exit_code == 0, builtin.output
    assert json.loads(builtin.output)["location"] == "built-in"


def test_agent_serve_is_reserved(home: Path) -> None:
    result = runner.invoke(app, ["agent", "serve"])
    assert result.exit_code != 0
    assert "not available yet" in result.output
