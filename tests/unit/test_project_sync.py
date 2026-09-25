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
    assert "environment/queue 0.1.0 is not pushed yet" in output
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


def test_push_reports_version_conflicts_before_uploading(hosted: Hosted) -> None:
    assert hosted.cli("task", "push", "refund", "--with-deps")[0] == 0
    writes = len(hosted.fake.writes)

    instruction = hosted.project.root / "tasks/refund/instruction.md"
    instruction.write_text("Review order A-1 carefully.\n")
    code, output = hosted.cli("task", "push", "refund")
    assert code == 1
    assert "Bump `version:`" in output
    assert len(hosted.fake.writes) == writes

    manifest = hosted.project.root / "tasks/refund/task.yaml"
    manifest.write_text(manifest.read_text().replace("version: 0.1.0", "version: 0.2.0"))
    code, output = hosted.cli("task", "push", "refund", "--json")
    assert code == 0, output
    assert json.loads(output)["steps"][-1]["status"] == "pushed"
    assert hosted.fake.revision_count() == 4


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


def test_hosted_runs_use_pushed_revisions_only(hosted: Hosted) -> None:
    code, output = hosted.cli("run", "--task", "refund", "--agent", "baseline", "--hosted")
    assert code == 1
    assert "Hosted runs use pushed revisions only" in output
    assert hosted.fake.jobs == []

    assert hosted.cli("task", "push", "refund", "--with-deps")[0] == 0
    assert hosted.cli("agent", "push", "baseline", "--with-deps")[0] == 0
    code, output = hosted.cli(
        "run", "--task", "refund", "--agent", "baseline", "--hosted", "--json"
    )
    assert code == 0, output
    job = hosted.fake.jobs[-1]
    task_parent = hosted.fake.parents[(hosted.project_id, "tasks", "refund")]
    agent_parent = hosted.fake.parents[(hosted.project_id, "agents", "baseline")]
    assert job["source"] == {
        "type": "task",
        "revision_id": hosted.fake.revisions[task_parent["id"]][0]["id"],
    }
    assert job["agent_revision_ids"] == [hosted.fake.revisions[agent_parent["id"]][0]["id"]]


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


def test_project_push_bumps_a_changed_resource_instead_of_overwriting(hosted: Hosted) -> None:
    assert hosted.cli("project", "push", "--yes")[0] == 0
    writes = len(hosted.fake.writes)
    revisions = hosted.fake.revision_count()
    instruction = hosted.project.root / "tasks/refund/instruction.md"
    instruction.write_text("Review order A-1 carefully.\n")

    code, output = hosted.cli("project", "push", "--yes")
    assert code == 1
    assert "nothing was uploaded" in output
    assert "--bump" in output
    assert len(hosted.fake.writes) == writes

    code, output = hosted.cli("project", "push", "--bump", "--yes", "--json")
    assert code == 0, output
    steps = json.loads(output)["steps"]
    bumped = next(step for step in steps if step["resource"] == "task/refund")
    assert bumped["status"] == "pushed"
    assert bumped["version"] != "0.1.0"
    manifest = (hosted.project.root / "tasks/refund/task.yaml").read_text()
    assert f"version: {bumped['version']}" in manifest
    assert hosted.fake.revision_count() > revisions


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
