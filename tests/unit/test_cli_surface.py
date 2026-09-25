"""The command surface: nouns, verbs, and what was removed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from project_fixtures import write_project
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from plural.cli.main import app

RESOURCE_GROUPS = ("env", "task", "verifier", "harness", "agent", "benchmark")
RESOURCE_VERBS = {"init", "validate", "push", "pull", "show", "list"}


def _root() -> TyperGroup:
    root = get_command(app)
    assert isinstance(root, TyperGroup)
    return root


def test_top_level_commands_are_the_documented_set() -> None:
    commands = set(_root().commands)
    assert commands == {
        "auth",
        "project",
        *RESOURCE_GROUPS,
        "run",
        "job",
        "trial",
        "review",
        "models",
        "session",
    }


def test_resource_groups_share_one_verb_set_and_nothing_publishes() -> None:
    root = _root()
    extras = {"benchmark": {"add", "remove"}, "agent": {"serve"}}
    for name in RESOURCE_GROUPS:
        group = root.commands[name]
        assert isinstance(group, TyperGroup)
        assert set(group.commands) == RESOURCE_VERBS | extras.get(name, set()), name
        assert not group.hidden


@pytest.mark.parametrize(
    ("group", "verbs"),
    [
        ("auth", {"login", "logout", "status", "scope"}),
        ("project", {"init", "push", "show"}),
        ("job", {"show", "list", "rerun", "push"}),
        ("trial", {"show", "rerun", "rescore"}),
        ("models", {"list"}),
    ],
)
def test_auth_project_job_and_model_verbs(group: str, verbs: set[str]) -> None:
    command = _root().commands[group]
    assert isinstance(command, TyperGroup)
    assert set(command.commands) == verbs


def test_benchmark_dry_run_applies_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    project = write_project(tmp_path / "support-desk")
    monkeypatch.chdir(project.root / "benchmarks/basics")
    result = CliRunner().invoke(
        app,
        ["run", "-b", "basics", "-a", "baseline", "--attempts", "3", "--dry-run", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["trials"]) == 6
    assert {item["task"] for item in payload["trials"]} == {"refund", "deny"}


def test_old_environment_manifests_fail_with_the_unknown_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    project = write_project(tmp_path / "support-desk")
    manifest = project.root / "environments/queue/environment.yaml"
    manifest.write_text(manifest.read_text() + "tasks: []\nverifier: null\n")
    monkeypatch.chdir(project.root)
    result = CliRunner().invoke(app, ["env", "validate", "queue"])
    assert result.exit_code == 1
    assert "tasks" in result.output
    assert "verifier" in result.output
