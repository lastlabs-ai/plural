"""Resource validation: required fields, references, and Benchmark rules."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from project_fixtures import write_project
from typer.testing import CliRunner

from plural import Agent, Harness
from plural.cli.main import app
from plural.project import Project, ProjectError, ResourceRef, Workspace
from plural.project.membership import add_tasks, remove_tasks

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


def test_verifiers_hash_the_same_on_every_load_and_location(
    project: Project, tmp_path: Path
) -> None:
    source = project.root / "environments/queue/environment.py"
    edit(
        source,
        "    def terminated(self) -> bool:",
        "    @action(read_only=True)\n"
        "    def status(self) -> str:\n"
        '        """Report the answer so far."""\n'
        "        return self.state.answer\n"
        "\n"
        "    def terminated(self) -> bool:",
    )
    copy = Project.at(shutil.copytree(project.root, tmp_path / "copy" / project.root.name))
    for kind, name in (("environment", "queue"), ("task", "refund")):
        ref = ResourceRef(kind, name)
        hashes = {Workspace(where).load(ref).content_hash for where in (project, project, copy)}
        assert len(hashes) == 1, ref


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


def test_a_title_is_a_display_name_and_the_folder_stays_the_name(project: Project) -> None:
    edit(project.root / "tasks/refund/task.yaml", "name: refund", "name: refund\ntitle: Refunds")
    agent_yaml = project.root / "agents/baseline/agent.yaml"
    edit(agent_yaml, "name: baseline", "name: baseline\ntitle: Base")
    benchmark_yaml = project.root / "benchmarks/basics/benchmark.yaml"
    edit(benchmark_yaml, "name: basics", "name: basics\ntitle: Refund basics")
    edit(
        benchmark_yaml,
        "  infrastructure_error: exclude\n",
        "  infrastructure_error: exclude\n  task_weights:\n    refund: 3\n",
    )
    benchmark_yaml.write_text(
        benchmark_yaml.read_text()
        + "categories:\n  - id: money\n    name: Money\n    tasks: [refund, deny]\n"
    )

    task = load(project, "task", "refund").value
    assert (task.name, task.title) == ("refund", "Refunds")
    agent = load(project, "agent", "baseline").value
    assert (agent.name, agent.title) == ("baseline", "Base")
    benchmark = load(project, "benchmark", "basics").value
    assert (benchmark.name, benchmark.title) == ("basics", "Refund basics")
    assert [item.name for item in benchmark.tasks] == ["refund", "deny"]
    assert benchmark.scoring.task_weights == {"refund": 3}

    edit(benchmark_yaml, "    refund: 3\n", "    Refunds: 3\n")
    assert "Refunds" in problems(project, "benchmark", "basics")


def test_an_unset_title_leaves_serialized_resources_as_before(project: Project) -> None:
    for kind, name in (("task", "refund"), ("agent", "baseline"), ("benchmark", "basics")):
        assert "title" not in load(project, kind, name).value.model_dump()


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
    assert remove_tasks(project, "basics", ["deny"]) == ["deny"]
    text = path.read_text()
    assert "  - deny" not in text
    assert "# Basics benchmark." in text and "# Ranking rules." in text
    assert add_tasks(project, "basics", ["deny"]) == ["deny"]
    assert add_tasks(project, "basics", ["deny"]) == []
    assert path.read_text().count("  - deny") == 1
    with pytest.raises(ProjectError, match="plural task init"):
        add_tasks(project, "basics", ["unknown"])
    with pytest.raises(ProjectError, match="No Task 'unknown' in Benchmark 'basics'"):
        remove_tasks(project, "basics", ["unknown"])
    load(project, "benchmark", "basics")


def test_benchmark_membership_takes_several_tasks_and_patterns(project: Project) -> None:
    remove_tasks(project, "basics", ["*"])
    assert add_tasks(project, "basics", ["re*", "deny", "refund"]) == ["refund", "deny"]
    assert remove_tasks(project, "basics", ["d?ny"]) == ["deny"]
    with pytest.raises(ProjectError, match="No Task 'zz-\\*' in this project.$"):
        add_tasks(project, "basics", ["zz-*"])


def test_cases_write_one_task_each_that_loads_and_joins_a_benchmark(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    cases = project.root / "refunds.jsonl"
    cases.write_text(
        json.dumps({"name": "refund-c3", "initial_state": {"order": "C-3", "refundable": True}})
        + "\n"
        + json.dumps(
            {
                "name": "refund-d4",
                "instructions": "Review order D-4.",
                "initial_state": {"order": "D-4", "refundable": False},
            }
        )
        + "\n"
    )
    monkeypatch.chdir(project.root)
    result = runner.invoke(app, ["task", "cases", "refund", str(cases), "-b", "basics"])
    assert result.exit_code == 0, result.output
    assert "refund-c3, refund-d4" in result.output
    task = load(project, "task", "refund-d4").value
    assert task.name == "refund-d4"
    assert task.initial_state == {"order": "D-4", "refundable": False}
    assert task.instructions == "Review order D-4.\n"
    assert load(project, "task", "refund-c3").value.instructions.startswith("Review order A-1")
    text = (project.root / "benchmarks/basics/benchmark.yaml").read_text()
    assert "  - refund-c3" in text and "  - refund-d4" in text

    again = runner.invoke(app, ["task", "cases", "refund", str(cases)])
    assert again.exit_code != 0 and "--replace" in again.output
    assert runner.invoke(app, ["task", "cases", "refund", str(cases), "--replace"]).exit_code == 0


def test_cases_are_checked_before_any_task_is_written(project: Project) -> None:
    from plural.project.cases import write_cases

    with pytest.raises(ProjectError, match="sets verifiers"):
        write_cases(project, "refund", [{"name": "ok-1"}, {"name": "bad", "verifiers": []}])
    with pytest.raises(ProjectError, match="More than one case is named 'twice'"):
        write_cases(project, "refund", [{"name": "twice"}, {"name": "twice"}])
    with pytest.raises(ProjectError, match="Case 1 has no name"):
        write_cases(project, "refund", [{"info": {}}])
    assert not (project.root / "tasks/ok-1").exists()


def test_benchmark_add_cli_infers_the_benchmark_and_stays_local(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    remove_tasks(project, "basics", ["deny"])
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
        path, "harness: scripted", "harness: claude-code\nharness_config:\n  reasoning_effort: high"
    )
    edit(path, "model: openai/gpt-5.6-luna", "model: anthropic/claude-sonnet-5")
    edit(path, "auth: none\n", "")
    builtin = load(project, "agent", "baseline")
    assert builtin.value.harness == "claude-code"
    assert builtin.dependencies == ()
    python_authored = Agent(
        name="baseline",
        version="0.1.0",
        model="anthropic/claude-sonnet-5",
        instructions="Follow the refund policy.",
        harness="claude-code",
        harness_config={"reasoning_effort": "high"},
    )
    assert builtin.content_hash == python_authored.content_hash

    edit(path, "harness: claude-code", "harness: nowhere")
    assert "nowhere" in problems(project, "agent", "baseline")

    edit(path, "harness: nowhere", "harness: claude-code")
    edit(path, "model: anthropic/claude-sonnet-5", "model: nobody/unknown")
    assert "Unknown model" in problems(project, "agent", "baseline")


def test_local_harness_cannot_shadow_a_builtin(project: Project) -> None:
    source = project.root / "harnesses/scripted"
    source.rename(project.root / "harnesses/codex")
    edit(project.root / "harnesses/codex/harness.yaml", "name: scripted", "name: codex")
    assert "built-in Harness" in problems(project, "harness", "codex")


def test_invalid_local_resource_shows_its_problems_not_a_hosted_fallback(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    (project.root / "tasks/refund/instruction.md").write_text("")
    monkeypatch.chdir(project.root)
    result = runner.invoke(app, ["task", "show", "refund"])
    assert result.exit_code == 0, result.output
    assert "not valid yet" in result.output
    assert "instruction.md is empty" in result.output
    assert "hosted" not in result.output.lower()
    shown = json.loads(runner.invoke(app, ["task", "show", "refund", "--json"]).stdout)
    assert shown["valid"] is False
    assert shown["depends_on"] == ["environment/queue", "verifier/resolved"]


def test_a_new_benchmark_shows_what_it_still_needs(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(project.root)
    assert runner.invoke(app, ["benchmark", "init", "b1"]).exit_code == 0
    result = runner.invoke(app, ["benchmark", "show", "b1"])
    assert result.exit_code == 0, result.output
    assert "Benchmark b1 (local, benchmarks/b1): not valid yet" in result.output
    assert "Problems:" in result.output


def test_delete_refuses_while_other_resources_use_it_then_deletes(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(project.root)
    refused = runner.invoke(app, ["verifier", "delete", "resolved", "-y"])
    assert refused.exit_code == 1
    assert "task/refund" in refused.output
    assert (project.root / "verifiers/resolved").is_dir()

    asked = runner.invoke(app, ["benchmark", "delete", "basics"])
    assert asked.exit_code == 1 and "--yes" in asked.output

    deleted = runner.invoke(app, ["benchmark", "delete", "basics", "--yes", "--json"])
    assert deleted.exit_code == 0, deleted.output
    assert json.loads(deleted.stdout) == {
        "resource": "benchmark/basics",
        "local": "benchmarks/basics",
        "hosted": None,
    }
    assert not (project.root / "benchmarks/basics").exists()
    missing = runner.invoke(app, ["benchmark", "delete", "basics", "-y"])
    assert missing.exit_code == 1 and "--hosted" in missing.output


def test_agent_init_needs_a_model(
    project: Project, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(project.root)
    result = runner.invoke(app, ["agent", "init", "helper"])
    assert result.exit_code == 1
    assert "--model" in result.output
    assert not (project.root / "agents/helper").exists()
    made = runner.invoke(app, ["agent", "init", "helper", "--model", "openai/gpt-5.6-luna"])
    assert made.exit_code == 0, made.output


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


def test_a_task_carries_files_of_any_type(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.execution.inputs import resource_uploads

    monkeypatch.setenv("PLURAL_BLOB_CACHE", str(tmp_path / "blobs"))
    folder = project.root / "tasks/refund/resources"
    folder.mkdir()
    (folder / "notes.md").write_text("# Notes\n")
    text_only = load(project, "task", "refund").content_hash
    (folder / "A-201.pdf").write_bytes(b"%PDF-1.7\n\xff\xfe\0sheet")
    (folder / "spec.docx").write_bytes(b"PK\x03\x04\xff\0word")

    task = load(project, "task", "refund").value
    by_name = {item.name: item for item in task.resources}
    assert by_name["resources/notes.md"].delivery == "inline"
    drawing = by_name["resources/A-201.pdf"]
    assert (drawing.delivery, drawing.content_type) == ("blob", "application/pdf")
    assert by_name["resources/spec.docx"].content_type.endswith("wordprocessingml.document")
    with_files = load(project, "task", "refund").content_hash
    assert with_files != text_only

    (folder / "A-201.pdf").write_bytes(b"%PDF-1.7\n\xff\xfe\0revised")
    assert load(project, "task", "refund").content_hash != with_files

    staged = {
        upload.path: upload.data
        for upload in resource_uploads(
            (), load(project, "task", "refund").value.resources, None, {}
        )
    }
    assert staged["task-resources/resources/A-201.pdf"] == b"%PDF-1.7\n\xff\xfe\0revised"

    (folder / "huge.tif").write_bytes(b"\0" * (16 * 1024 * 1024 + 1))
    assert "huge.tif is larger than 16 MiB" in problems(project, "task", "refund")


def test_a_missing_file_says_how_to_get_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from plural import Resource
    from plural.execution.inputs import resource_uploads

    monkeypatch.setenv("PLURAL_BLOB_CACHE", str(tmp_path / "blobs"))
    drawing = Resource.from_file(_write(tmp_path / "A-201.pdf", b"\xff\0pdf"))
    assert drawing.delivery == "blob"
    note = Resource.from_file(_write(tmp_path / "note.txt", b"plain"))
    assert (note.delivery, note.content) == ("inline", "plain")
    monkeypatch.setenv("PLURAL_BLOB_CACHE", str(tmp_path / "elsewhere"))
    with pytest.raises(ValueError, match="plural pull"):
        resource_uploads((), (drawing,), None, {})


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_a_task_in_an_environment_with_no_apps_carries_its_answer_key(
    project: Project,
) -> None:
    root = project.root
    (root / "environments/answers").mkdir()
    (root / "environments/answers/environment.yaml").write_text(
        "name: answers\nreadme: null\nruntime:\n  provider: local\n", encoding="utf-8"
    )
    (root / "tasks/triage").mkdir()
    (root / "tasks/triage/instruction.md").write_text("Which team?\n", encoding="utf-8")
    (root / "tasks/triage/task.yaml").write_text(
        "name: triage\ninstructions: instruction.md\nenvironment: answers\n"
        "verifiers: [resolved]\nexpected: billing\n",
        encoding="utf-8",
    )
    workspace = Workspace(Project.at(root))

    task = workspace.get("task", "triage")

    assert task.expected == "billing"
    assert task.definition().environment.apps == ()
    assert "billing" not in str(task.definition().public_payload)
