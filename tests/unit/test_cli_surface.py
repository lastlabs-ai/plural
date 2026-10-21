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
RESOURCE_VERBS = {"init", "validate", "push", "release", "pull", "show", "list", "delete"}


def _root() -> TyperGroup:
    root = get_command(app)
    assert isinstance(root, TyperGroup)
    return root


def _visible(group: TyperGroup) -> set[str]:
    return {name for name, command in group.commands.items() if not command.hidden}


def _hidden(group: TyperGroup) -> set[str]:
    return {name for name, command in group.commands.items() if command.hidden}


def test_top_level_commands_are_the_documented_set() -> None:
    root = _root()
    assert _visible(root) == {
        "auth",
        "credential",
        "project",
        "app",
        *RESOURCE_GROUPS,
        "run",
        "job",
        "trial",
        "review",
        "reward",
        "model",
        "runtime",
        "secret",
        "session",
    }
    assert _hidden(root) == {"rewards", "models"}


def test_resource_groups_share_one_verb_set_and_nothing_publishes() -> None:
    root = _root()
    extras = {
        "benchmark": {"add", "remove"},
        "env": {"serve"},
        "verifier": {"try", "apply"},
    }
    for name in RESOURCE_GROUPS:
        group = root.commands[name]
        assert isinstance(group, TyperGroup)
        assert _visible(group) == RESOURCE_VERBS | extras.get(name, set()), name
        assert _hidden(group) == ({"add", "eject-files"} if name == "env" else set()), name
        assert not group.hidden


@pytest.mark.parametrize(
    ("group", "verbs"),
    [
        ("auth", {"login", "logout", "status", "scope"}),
        ("project", {"init", "push", "show"}),
        ("app", {"add", "list", "remove"}),
        ("job", {"show", "list", "rerun", "record"}),
        ("trial", {"show", "rerun"}),
        ("reward", {"show", "export"}),
        ("model", {"list"}),
        ("secret", {"list", "set", "delete"}),
        ("credential", {"list", "set", "delete"}),
        (
            "runtime",
            {
                "providers",
                "provider",
                "list",
                "show",
                "create",
                "edit",
                "delete",
                "use",
                "template",
                "policy",
            },
        ),
    ],
)
def test_auth_project_job_and_model_verbs(group: str, verbs: set[str]) -> None:
    command = _root().commands[group]
    assert isinstance(command, TyperGroup)
    assert _visible(command) == verbs


@pytest.mark.parametrize(
    ("args", "new"),
    [
        (["job", "push", "j1"], "plural job record"),
        (["credential", "unset", "TOKEN"], "plural credential delete"),
        (["env", "add", "desk", "--mcp", "x"], "plural app add"),
        (["env", "eject-files", "desk"], "plural app add ENV --files-server --copy"),
        (["models", "list", "--help"], "plural model"),
        (["rewards", "show", "--help"], "plural reward"),
        (["auth", "scope", "."], "plural auth scope --account"),
        (["session", "import", "missing", "--dest", "out"], "--out"),
    ],
)
def test_deprecated_names_still_work_and_name_the_new_form(
    args: list[str], new: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, args)
    assert f"use `{new}`" in result.stderr
    assert "deprecated" in result.stderr


def test_hidden_aliases_stay_out_of_help() -> None:
    runner = CliRunner()
    root = runner.invoke(app, ["--help"]).stdout
    listed = {line.strip("│ ").split(" ")[0] for line in root.splitlines()}
    assert {"model", "reward", "app"} <= listed
    assert not {"models", "rewards"} & listed
    assert "Objects:" in root
    env = runner.invoke(app, ["env", "--help"]).stdout
    assert "eject-files" not in env
    assert "--server-env" in runner.invoke(app, ["app", "add", "--help"]).stdout
    pull = runner.invoke(app, ["task", "pull", "--help"]).stdout
    assert "--revision" not in pull
    assert "-t" not in runner.invoke(app, ["runtime", "create", "--help"]).stdout.split()
    assert "-v" not in runner.invoke(app, ["task", "init", "--help"]).stdout.split()


def test_one_short_flag_means_one_option() -> None:
    meanings: dict[str, set[str]] = {}

    def walk(command: object) -> None:
        for param in getattr(command, "params", []):
            for flag in [*param.opts, *param.secondary_opts]:
                if len(flag) == 2 and flag.startswith("-"):
                    meanings.setdefault(flag, set()).add(param.opts[-1] if param.opts else "")
        for child in (getattr(command, "commands", None) or {}).values():
            walk(child)

    walk(_root())
    for flag, names in meanings.items():
        assert len({name for name in names if name.startswith("--")}) <= 1, (flag, names)


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


def test_track_is_a_deprecated_spelling_of_record(capsys: pytest.CaptureFixture[str]) -> None:
    from plural.cli.run_commands import _recording

    assert _recording(False, True) is True
    assert "`--track` is deprecated" in capsys.readouterr().err
    assert _recording(True, False) is True
    assert _recording(False, False) is False
    assert capsys.readouterr().err == ""
