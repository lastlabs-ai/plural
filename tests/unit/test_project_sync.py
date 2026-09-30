"""Push, pull, hosted reads, and hosted runs against an in-memory hosted API."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from hosted_fake import FakeHosted, routed
from project_fixtures import hasher_for, write_project
from typer.testing import CliRunner

import plural.auth
from plural.auth import Credential, Profile, load_config, save_config
from plural.cli.main import app
from plural.harness.retrieval import tree_digest
from plural.project import Project, ProjectBinding

runner = CliRunner()


class Hosted:
    def __init__(self, project: Project, fake: FakeHosted, project_id: str) -> None:
        self.project = project
        self.fake = fake
        self.project_id = project_id

    def cli(self, *args: str) -> tuple[int, str]:
        result = runner.invoke(app, list(args))
        if result.exception is not None and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result.exit_code, result.output


@pytest.fixture
def hosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path) -> Iterator[Hosted]:
    project = write_project(tmp_path / "support-desk")
    fake = FakeHosted(hasher_for(project.root))
    record = fake.add_project("support-desk")
    plural.auth.default_credential_store().set("default", Credential(access_token="token"))
    project.write_binding(
        ProjectBinding(
            api_url="https://plural.test",
            account_id="acc_personal",
            project_id=record["id"],
            project_slug="support-desk",
        )
    )
    monkeypatch.chdir(project.root)
    with routed(monkeypatch, fake):
        yield Hosted(project, fake, record["id"])


def test_plain_push_requires_hosted_dependencies_and_uploads_nothing(hosted: Hosted) -> None:
    code, output = hosted.cli("task", "push", "refund")
    assert code == 1
    assert "nothing was uploaded" in output
    assert "environment/queue is not pushed yet" in output
    assert "--with-deps" in output
    assert hosted.fake.writes == []


def test_push_with_deps_orders_dependencies_and_repeats_without_duplicates(
    hosted: Hosted,
) -> None:
    code, output = hosted.cli("task", "push", "refund", "--with-deps", "--json")
    assert code == 0, output
    steps = json.loads(output)["steps"]
    assert [step["resource"] for step in steps] == [
        "environment/queue",
        "verifier/resolved",
        "task/refund",
    ]
    assert {step["status"] for step in steps} == {"pushed"}
    assert hosted.fake.revision_count() == 3
    assert all(parent["visibility"] == "private" for parent in hosted.fake.parents.values())
    task_revision = hosted.fake.revisions[
        hosted.fake.parents[(hosted.project_id, "tasks", "refund")]["id"]
    ][0]
    assert {item["kind"] for item in task_revision["dependencies"]} == {"environment", "verifier"}

    lock = hosted.project.read_lock()
    assert lock.project_id == hosted.project_id
    assert lock.resources["task/refund"].revision_id == task_revision["id"]
    assert lock.resources["task/refund"].dependencies == ["environment/queue", "verifier/resolved"]

    writes = len(hosted.fake.writes)
    packages = dict(hosted.fake.packages)
    code, output = hosted.cli("task", "push", "refund", "--json")
    assert code == 0, output
    assert {step["status"] for step in json.loads(output)["steps"]} == {"unchanged"}
    assert hosted.fake.revision_count() == 3
    assert hosted.fake.packages == packages
    assert len(hosted.fake.writes) == writes


def test_a_changed_resource_becomes_the_next_numbered_revision(hosted: Hosted) -> None:
    code, output = hosted.cli("task", "push", "refund", "--with-deps", "--json")
    assert code == 0, output
    first = json.loads(output)["steps"][-1]
    assert (first["number"], first["version"], first["revision"]) == (1, "0.1.0", "#1 (0.1.0)")

    instruction = hosted.project.root / "tasks/refund/instruction.md"
    instruction.write_text("Review order A-1 carefully.\n")
    code, output = hosted.cli("task", "push", "refund", "--json")
    assert code == 0, output
    step = json.loads(output)["steps"][-1]
    assert (step["status"], step["number"], step["version"]) == ("pushed", 2, None)
    assert step["note"] == "version 0.1.0 already names #1 (0.1.0)"
    assert hosted.fake.revision_count() == 4
    manifest = (hosted.project.root / "tasks/refund/task.yaml").read_text()
    assert "version: 0.1.0" in manifest
    parent = hosted.fake.parents[(hosted.project_id, "tasks", "refund")]
    newest = hosted.fake.revisions[parent["id"]][-1]
    assert newest["parent_revision_id"] == first["revision_id"]
    lock = hosted.project.read_lock().resources["task/refund"]
    assert (lock.number, lock.version) == (2, None)


def test_release_labels_the_revision_matching_the_local_files(hosted: Hosted) -> None:
    assert hosted.cli("task", "push", "refund", "--with-deps")[0] == 0
    (hosted.project.root / "tasks/refund/instruction.md").write_text("Carefully.\n")
    code, output = hosted.cli("task", "release", "refund", "1.0.0", "--json")
    assert code == 0, output
    step = json.loads(output)["steps"][-1]
    assert (step["number"], step["version"]) == (2, "1.0.0")
    assert hosted.project.read_lock().resources["task/refund"].version == "1.0.0"

    code, output = hosted.cli("task", "release", "refund", "1.0.0")
    assert code == 0, output
    code, output = hosted.cli("task", "release", "refund", "1.0.1")
    assert code == 1
    assert "already released as 1.0.0" in output
    (hosted.project.root / "tasks/refund/instruction.md").write_text("Again.\n")
    code, output = hosted.cli("task", "release", "refund", "1.0.0")
    assert code == 1
    assert "1.0.0 already names #2 (1.0.0)" in output
    code, output = hosted.cli("task", "release", "refund", "v2")
    assert code == 1
    assert "MAJOR.MINOR.PATCH" in output


def test_a_push_on_top_of_unsynced_hosted_changes_is_refused(hosted: Hosted) -> None:
    assert hosted.cli("verifier", "push", "resolved")[0] == 0
    parent = hosted.fake.parents[(hosted.project_id, "verifiers", "resolved")]
    theirs = {**hosted.fake.revisions[parent["id"]][0], "id": "rev_theirs", "number": 2}
    theirs.update(content_hash="sha256:" + "b" * 64, version=None)
    hosted.fake.revisions[parent["id"]].append(theirs)
    parent["current_revision_id"] = "rev_theirs"

    verifier = next((hosted.project.root / "verifiers/resolved").glob("*.py"))
    verifier.write_text(verifier.read_text() + "\n# local edit\n")
    code, output = hosted.cli("verifier", "push", "resolved")
    assert code == 1
    assert "hosted #2, synced #1 (0.1.0)" in output
    code, output = hosted.cli("verifier", "push", "resolved", "--force", "--json")
    assert code == 0, output
    assert json.loads(output)["steps"][-1]["number"] == 3


def test_push_refuses_credential_files(hosted: Hosted) -> None:
    (hosted.project.root / "environments/queue/.env").write_text("OPENAI_API_KEY=secret\n")
    code, output = hosted.cli("env", "push", "queue")
    assert code == 1
    assert ".env" in output
    assert hosted.fake.writes == []


def test_server_hash_disagreement_is_reported(hosted: Hosted) -> None:
    hosted.fake.hasher = lambda collection, slug, payload: "sha256:" + "f" * 64
    code, output = hosted.cli("verifier", "push", "resolved")
    assert code == 1
    assert "SDK and server versions disagree" in output


def test_pull_restores_files_and_protects_local_edits(hosted: Hosted) -> None:
    assert hosted.cli("task", "push", "refund", "--with-deps")[0] == 0
    root = hosted.project.root
    original = tree_digest(root / "tasks/refund")

    import shutil

    shutil.rmtree(root / "tasks/refund")
    shutil.rmtree(root / "environments/queue")
    code, output = hosted.cli("task", "pull", "refund", "--with-deps")
    assert code == 0, output
    assert tree_digest(root / "tasks/refund") == original
    assert (root / "environments/queue/environment.py").is_file()
    assert hosted.cli("task", "validate", "refund")[0] == 0

    code, output = hosted.cli("task", "pull", "refund")
    assert code == 0 and "unchanged" in output

    (root / "tasks/refund/instruction.md").write_text("local edit\n")
    code, output = hosted.cli("task", "pull", "refund")
    assert code == 1
    assert "--force" in output
    assert (root / "tasks/refund/instruction.md").read_text() == "local edit\n"

    code, output = hosted.cli("task", "pull", "refund", "--force", "--json")
    assert code == 0, output
    backup = Path(json.loads(output)[-1]["backup"])
    assert (backup / "instruction.md").read_text() == "local edit\n"
    assert tree_digest(root / "tasks/refund") == original


def _web_app_task(hosted: Hosted, slug: str) -> None:
    """A Task saved in the web app: a definition and dependency pins, no package."""
    fake = hosted.fake
    source = fake.revisions[fake.parents[(hosted.project_id, "tasks", "refund")]["id"]][0]
    parent = {"id": f"tas_{slug}", "slug": slug, "name": "Web Task", "visibility": "private"}
    fake.parents[(hosted.project_id, "tasks", slug)] = parent
    fake.revisions[parent["id"]] = [
        {
            "id": f"rev_{slug}",
            "version": "0.1.0",
            "content_hash": "sha256:" + "a" * 64,
            "package_digest": None,
            "status": "available",
            "dependencies": source["dependencies"],
            "definition": {
                "name": "Web Task",
                "version": "0.1.0",
                "instructions": "Review order C-3 and submit refunded or denied.",
                "info": {"authors": [], "keywords": []},
                "goals": [],
                "resources": [],
                "initial_state": {"order": "C-3", "refundable": True},
                "reset_options": {},
            },
        }
    ]


def test_pull_writes_a_web_app_task_and_the_dependencies_it_lacks(hosted: Hosted) -> None:
    import shutil

    assert hosted.cli("task", "push", "refund", "--with-deps")[0] == 0
    _web_app_task(hosted, "web-task")
    root = hosted.project.root
    shutil.rmtree(root / "environments/queue")

    code, output = hosted.cli("task", "pull", "web-task", "--json")
    assert code == 0, output
    steps = json.loads(output)
    assert [step["resource"] for step in steps] == ["environment/queue", "task/web-task"]
    assert [step["rebuilt"] for step in steps] == [False, True]
    manifest = (root / "tasks/web-task/task.yaml").read_text()
    assert "name: web-task" in manifest
    assert "title: Web Task" in manifest
    assert "environment: queue" in manifest
    assert "order: C-3" in manifest
    # Stored values that differ from the manifest default are kept, since they are hashed.
    assert "keywords: []" in manifest
    assert "goals" not in manifest
    assert (root / "tasks/web-task/instruction.md").read_text().startswith("Review order C-3")
    assert hosted.cli("task", "validate", "web-task")[0] == 0
    assert hosted.project.read_lock().resources["task/web-task"].revision_id == "rev_web-task"


def test_a_title_is_the_hosted_name_and_the_directory_is_the_slug(hosted: Hosted) -> None:
    manifest = hosted.project.root / "tasks/refund/task.yaml"
    text = manifest.read_text().replace("name: refund", "name: refund\ntitle: Refund A-1")
    manifest.write_text(text)
    code, output = hosted.cli("task", "push", "refund", "--with-deps")
    assert code == 0, output
    parent = hosted.fake.parents[(hosted.project_id, "tasks", "refund")]
    assert parent["name"] == "Refund A-1"
    assert hosted.cli("task", "validate", "refund")[0] == 0

    code, output = hosted.cli("task", "push", "refund", "--json")
    assert {step["status"] for step in json.loads(output)["steps"]} == {"unchanged"}

    manifest.write_text(text.replace("Refund A-1", "Refund triage"))
    code, output = hosted.cli("task", "push", "refund", "--json")
    assert code == 0, output
    assert {step["status"] for step in json.loads(output)["steps"]} == {"unchanged"}
    assert parent["name"] == "Refund triage"
    assert parent["slug"] == "refund"
    assert len(hosted.fake.revisions[parent["id"]]) == 1


def test_a_run_pulls_a_task_that_only_the_hosted_project_has(hosted: Hosted) -> None:
    assert hosted.cli("task", "push", "refund", "--with-deps")[0] == 0
    _web_app_task(hosted, "web-task")
    code, output = hosted.cli("run", "--task", "web-task", "--agent", "baseline", "--hosted")
    assert code == 0, output
    assert "Pulled from the hosted project" in output
    assert "task/web-task 0.1.0" in output
    assert (hosted.project.root / "tasks/web-task/task.yaml").is_file()


def test_a_web_app_environment_without_files_still_cannot_be_pulled(hosted: Hosted) -> None:
    assert hosted.cli("env", "push", "queue")[0] == 0
    parent = hosted.fake.parents[(hosted.project_id, "environments", "queue")]
    hosted.fake.revisions[parent["id"]][0]["package_digest"] = None
    import shutil

    shutil.rmtree(hosted.project.root / "environments/queue")
    code, output = hosted.cli("env", "pull", "queue")
    assert code == 1
    assert "carries code" in output


def test_hosted_show_and_list_are_labeled(hosted: Hosted) -> None:
    assert hosted.cli("verifier", "push", "resolved")[0] == 0
    code, output = hosted.cli("verifier", "show", "resolved", "--hosted", "--json")
    assert code == 0, output
    payload = json.loads(output)
    assert payload["location"] == "hosted"
    assert payload["revisions"][0]["restorable"] is True

    code, output = hosted.cli("verifier", "list", "--json")
    assert code == 0, output
    labels = {(item["name"], item["location"]) for item in json.loads(output)}
    assert labels == {("resolved", "local"), ("resolved", "hosted")}

    code, output = hosted.cli("task", "show", "refund", "--json")
    assert json.loads(output)["location"] == "local"


def test_push_is_refused_when_the_scope_selects_another_project(hosted: Hosted, home: Path) -> None:
    other = hosted.fake.add_project("other")
    config = load_config()
    save_config(
        config.with_profile(
            "default",
            Profile(
                api_url="https://plural.test",
                account_id="acc_personal",
                project_id=other["id"],
                project_slug="other",
            ),
        )
    )
    code, output = hosted.cli("verifier", "push", "resolved")
    assert code == 1
    assert "bound to 'support-desk'" in output
    assert "plural auth scope --project support-desk" in output
    assert hosted.fake.writes == []


def test_a_hosted_run_pushes_the_revisions_it_needs_first(hosted: Hosted) -> None:
    code, output = hosted.cli("run", "--task", "refund", "--agent", "baseline", "--hosted")
    assert code == 0, output
    assert "Pushed to the hosted project first" in output
    assert "task/refund #1 (0.1.0)" in output
    job = hosted.fake.jobs[-1]
    task_parent = hosted.fake.parents[(hosted.project_id, "tasks", "refund")]
    agent_parent = hosted.fake.parents[(hosted.project_id, "agents", "baseline")]
    assert job["source"] == {
        "type": "task",
        "revision_id": hosted.fake.revisions[task_parent["id"]][0]["id"],
    }
    assert job["agent_revision_ids"] == [hosted.fake.revisions[agent_parent["id"]][0]["id"]]

    instruction = hosted.project.root / "tasks/refund/instruction.md"
    instruction.write_text("Review order A-1 carefully.\n")
    code, output = hosted.cli("run", "--task", "refund", "--agent", "baseline", "--hosted")
    assert code == 0, output
    assert "task/refund #2 (version 0.1.0 already names #1 (0.1.0))" in output
    assert "version: 0.1.0" in (hosted.project.root / "tasks/refund/task.yaml").read_text()
    newest = hosted.fake.revisions[task_parent["id"]][-1]
    assert (newest["number"], newest["version"]) == (2, None)
    assert hosted.fake.jobs[-1]["source"]["revision_id"] == newest["id"]

    code, output = hosted.cli("run", "--task", "refund", "--agent", "baseline", "--hosted")
    assert code == 0, output
    assert "Pushed to the hosted project first" not in output


def test_a_retained_version_is_callable_by_name(hosted: Hosted) -> None:
    root = hosted.project.root
    assert hosted.cli("run", "--task", "refund", "--agent", "baseline", "--hosted")[0] == 0
    instruction = root / "tasks/refund/instruction.md"
    instruction.write_text("Review order A-1 carefully.\n")
    assert hosted.cli("run", "--task", "refund", "--agent", "baseline", "--hosted")[0] == 0
    task_parent = hosted.fake.parents[(hosted.project_id, "tasks", "refund")]
    first, second = hosted.fake.revisions[task_parent["id"]]

    code, output = hosted.cli("run", "--task", "refund@1", "--agent", "baseline", "--hosted")
    assert code == 0, output
    assert "task/refund@1" in output
    assert "working copy is unchanged" in output
    assert hosted.fake.jobs[-1]["source"]["revision_id"] == first["id"]
    assert instruction.read_text() == "Review order A-1 carefully.\n"
    retained = root / ".plural/versions/task-refund@1/tasks/refund/instruction.md"
    assert retained.read_text() != instruction.read_text()

    for selector in ("0.1.0", first["content_hash"]):
        code, output = hosted.cli(
            "run", "--task", f"refund@{selector}", "--agent", "baseline", "--hosted"
        )
        assert code == 0, output
        assert hosted.fake.jobs[-1]["source"]["revision_id"] == first["id"]

    code, output = hosted.cli("run", "--task", "refund@2", "--agent", "baseline", "--hosted")
    assert code == 0, output
    assert "retained" not in output
    assert hosted.fake.jobs[-1]["source"]["revision_id"] == second["id"]

    code, output = hosted.cli("run", "--task", "refund@1", "--agent", "baseline", "--json")
    assert code == 0, output
    assert output.startswith("Using retained revisions")
    job_id = json.loads(output[output.index("{") :])["job_id"]
    assert (root / ".plural/jobs" / job_id).is_dir()

    code, output = hosted.cli("task", "show", "refund@#1", "--json")
    assert code == 0, output
    payload = json.loads(output)
    assert payload["location"] == "hosted"
    assert [item["number"] for item in payload["revisions"]] == [1]
    code, output = hosted.cli("task", "show", "refund@2", "--json")
    assert json.loads(output)["location"] == "local"

    code, output = hosted.cli("task", "pull", "refund@9")
    assert code == 1
    assert "has no revision 9" in output
    code, output = hosted.cli("task", "pull", "refund@1", "--revision", "2")
    assert code == 1
    assert "different revisions" in output
    code, output = hosted.cli("task", "validate", "refund@1")
    assert code == 1
    assert "plural task pull refund@1" in output
    code, output = hosted.cli("run", "--task", "refund@", "--agent", "baseline")
    assert code == 1
    assert "no valid revision" in output


def test_hosted_model_run_records_an_agent_named_after_the_model(hosted: Hosted) -> None:
    assert hosted.cli("task", "push", "refund", "--with-deps")[0] == 0
    code, output = hosted.cli(
        "run", "-t", "refund", "-m", "openai/gpt-5.6-luna", "--hosted", "--json"
    )
    assert code == 0, output
    assert (hosted.project_id, "agents", "openai-gpt-5-6-luna") in hosted.fake.parents


def test_project_push_uploads_every_resource_and_repeats_as_unchanged(hosted: Hosted) -> None:
    code, output = hosted.cli("project", "push", "--yes", "--json")
    assert code == 0, output
    steps = json.loads(output)["steps"]
    assert steps
    assert {step["status"] for step in steps} == {"pushed"}
    assert hosted.fake.revision_count() == len(steps)

    writes = len(hosted.fake.writes)
    code, output = hosted.cli("project", "push", "--yes")
    assert code == 0, output
    assert "already pushed" in output
    assert len(hosted.fake.writes) == writes


def test_project_push_adds_a_revision_for_a_change_without_touching_files(
    hosted: Hosted,
) -> None:
    assert hosted.cli("project", "push", "--yes")[0] == 0
    revisions = hosted.fake.revision_count()
    instruction = hosted.project.root / "tasks/refund/instruction.md"
    instruction.write_text("Review order A-1 carefully.\n")
    manifest = hosted.project.root / "tasks/refund/task.yaml"
    before = manifest.read_text()

    code, output = hosted.cli("project", "push", "--yes")
    assert code == 0, output
    assert "task/refund" in output and "new revision" in output
    assert manifest.read_text() == before

    code, output = hosted.cli("project", "push", "--yes", "--json")
    assert code == 0, output
    assert hosted.fake.revision_count() > revisions
    changed = [step for step in json.loads(output)["steps"] if step["action"] != "unchanged"]
    assert changed == []


def test_project_push_ignores_the_retired_bump_flag(hosted: Hosted) -> None:
    code, output = hosted.cli("project", "push", "--bump", "--yes")
    assert code == 0, output
    assert "--bump is no longer needed" in output


def test_project_push_asks_before_uploading_without_yes(hosted: Hosted) -> None:
    code, output = hosted.cli("project", "push")
    assert code == 1
    assert "--yes" in output
    assert hosted.fake.writes == []


def test_models_list_comes_from_the_hosted_policy(hosted: Hosted) -> None:
    code, output = hosted.cli("models", "list", "--provider", "anthropic", "--json")
    assert code == 0, output
    payload = json.loads(output)
    assert payload["source"] == "hosted"
    assert [item["id"] for item in payload["models"]] == ["anthropic/claude-sonnet-5"]


def test_a_wanted_version_labels_only_when_free_and_not_a_number() -> None:
    from plural.project.sync import HostedRevision, _label

    released = HostedRevision("res", "rev-1", "1.0.0", "sha256:a", None, number=1)
    assert _label(None, [released]) == (None, None)
    assert _label("1.1.0", [released]) == ("1.1.0", None)
    assert _label("1.0.0", [released]) == (None, "version 1.0.0 already names #1 (1.0.0)")
    version, note = _label("7", [released])
    assert version is None
    assert note is not None and "#7" in note
