from __future__ import annotations

import json
from pathlib import Path

import pytest
from project_fixtures import write_project
from typer.testing import CliRunner

from plural import Agent, Environment, Harness, Job, Runtime, Task
from plural.cli.main import app
from plural.harness.builtins import (
    BUILTIN_HARNESS_NAMES,
    builtin_schema,
    get_builtin,
    normalize_kwargs,
    resolve_builtin_package,
)
from plural.harness.vendor_harnesses import (
    ClaudeCodeHarness,
    CodexHarness,
    HermesHarness,
)
from plural.project import Project, ProjectError, ResourceRef, Workspace
from plural.project.resources import load_harness_directory
from plural.verifiers import DeterministicVerifier


def _task() -> Task:
    return Task(
        name="case",
        instructions="Finish the case.",
        environment=Environment(name="world", runtime=Runtime.docker()),
        verifiers=(DeterministicVerifier(name="done", check="python verify.py"),),
    )


def test_agent_accepts_builtin_name_and_kwargs() -> None:
    agent = Agent(
        model="anthropic/claude-sonnet-5",
        harness="claude-code",
        harness_kwargs={"reasoning_effort": "high"},
    )
    assert agent.harness == "claude-code"
    assert agent.harness_kwargs["reasoning_effort"] == "high"
    assert agent.harness_kwargs["version"] == get_builtin("claude-code").pinned_version
    package = agent._resolved_package()
    assert package is not None
    assert package.definition.implementation == "runnable"
    assert package.definition.setup
    assert package.definition.command[2] == "plural.harness.class_runner"
    assert package.definition.command[-1].endswith(":ClaudeCodeHarness")


def test_builtins_use_the_standard_harness_run_interface() -> None:
    classes = (HermesHarness, ClaudeCodeHarness, CodexHarness)
    assert all(issubclass(item, Harness) for item in classes)
    assert all(callable(item.run) for item in classes)
    for name, class_name in (
        ("hermes", "HermesHarness"),
        ("claude-code", "ClaudeCodeHarness"),
        ("codex", "CodexHarness"),
    ):
        package = resolve_builtin_package(name)
        assert package.definition.command[-1] == f"vendor_harnesses.py:{class_name}"


def test_agent_rejects_unknown_name_and_invalid_kwargs() -> None:
    with pytest.raises(ValueError, match="Unknown built-in Harness"):
        Agent(model="openai/gpt-5.6-luna", harness="cursor")
    with pytest.raises(ValueError, match="Invalid harness_kwargs"):
        Agent(
            model="anthropic/claude-sonnet-5",
            harness="claude-code",
            harness_kwargs={"reasoning_effort": "ludicrous"},
        )
    with pytest.raises(ValueError, match="accepts"):
        Agent(model="openai/gpt-5.6-luna", harness="claude-code")


def test_config_file_is_normalized_into_agent_hash(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"model_context_window": 200000}\n', encoding="utf-8")
    first = Agent(
        model="openai/gpt-5.6-luna",
        harness="codex",
        harness_kwargs={"config": str(config)},
    )
    second = Agent(
        model="openai/gpt-5.6-luna",
        harness="codex",
        harness_kwargs={"config": {"model_context_window": 200000}},
    )
    assert first.harness_kwargs["config"] == {"model_context_window": 200000}
    assert first.content_hash == second.content_hash
    changed = Agent(
        model="openai/gpt-5.6-luna",
        harness="codex",
        harness_kwargs={"config": {"model_context_window": 1000}},
    )
    assert changed.content_hash != first.content_hash


def test_version_override_changes_package_lock() -> None:
    default = resolve_builtin_package("hermes", {})
    overridden = resolve_builtin_package("hermes", {"version": "0.18.2"})
    assert default.definition.revision == get_builtin("hermes").pinned_version
    assert overridden.definition.revision == "0.18.2"
    assert default.content_hash != overridden.content_hash
    assert overridden.definition.setup[0][-1] == "0.18.2"


def _agent_project(root: Path, agent_yaml: str) -> Workspace:
    project = write_project(root)
    (project.root / "agents/baseline/agent.yaml").write_text(agent_yaml, encoding="utf-8")
    return Workspace(project)


def test_agent_yaml_keeps_compact_builtin_and_matches_python(tmp_path: Path) -> None:
    agent = Agent(
        model="anthropic/claude-sonnet-5",
        name="baseline",
        harness="claude-code",
        harness_kwargs={"permission_mode": "acceptEdits"},
    )
    space = _agent_project(
        tmp_path / "support-desk",
        "name: baseline\n"
        "version: 0.1.0\n"
        "model: anthropic/claude-sonnet-5\n"
        "harness: claude-code\n"
        "harness_kwargs:\n"
        "  permission_mode: acceptEdits\n",
    )
    loaded = space.load(ResourceRef("agent", "baseline"))
    restored = loaded.value
    assert isinstance(restored, Agent)
    assert restored.harness == "claude-code"
    assert restored.harness_kwargs["permission_mode"] == "acceptEdits"
    assert restored.content_hash == agent.content_hash
    assert loaded.dependencies == ()
    job = Job(_task(), agents=(agent,))
    assert Job(_task(), agents=(restored,)).content_hash == job.content_hash


def test_builtin_names_cannot_be_redeclared_as_project_harnesses(tmp_path: Path) -> None:
    project = write_project(tmp_path / "support-desk")
    directory = project.root / "harnesses/hermes"
    directory.mkdir()
    (directory / "harness.yaml").write_text(
        "name: hermes\nversion: 0.1.0\npython: harness.py:Hermes\n", encoding="utf-8"
    )
    with pytest.raises(ProjectError) as caught:
        Workspace(project).load(ResourceRef("harness", "hermes"))
    assert "'hermes' is a built-in Harness" in " ".join(caught.value.problems)


def test_custom_class_harness_loads_the_same_everywhere(tmp_path: Path) -> None:
    project = write_project(tmp_path / "support-desk")
    space = Workspace(project)
    harness = space.load(ResourceRef("harness", "scripted")).value
    assert isinstance(harness, Harness)
    assert type(harness).name == "scripted"
    agent = space.load(ResourceRef("agent", "baseline")).value
    assert isinstance(agent.harness, Harness)
    assert agent.harness.content_hash == harness.content_hash
    direct = load_harness_directory(project.root / "harnesses/scripted", name="scripted")
    assert direct.content_hash == harness.content_hash
    fresh = Workspace(Project.at(project.root)).load(ResourceRef("agent", "baseline")).value
    assert fresh.content_hash == agent.content_hash


def test_cli_lists_builtins_and_shows_their_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    project = write_project(tmp_path / "support-desk")
    monkeypatch.chdir(project.root)
    runner = CliRunner()
    listed = runner.invoke(app, ["harness", "list", "--local", "--json"])
    assert listed.exit_code == 0, listed.output
    names = {item["name"] for item in json.loads(listed.stdout)}
    assert names == {"scripted"}
    listed = runner.invoke(app, ["harness", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    payload = json.loads(listed.stdout)
    builtins = {item["name"] for item in payload if item["location"] == "built-in"}
    assert builtins == set(BUILTIN_HARNESS_NAMES)
    shown = runner.invoke(app, ["harness", "show", "claude-code", "--json"])
    assert shown.exit_code == 0, shown.output
    body = json.loads(shown.stdout)
    assert body["location"] == "built-in"
    assert body["pinned_version"] == get_builtin("claude-code").pinned_version
    assert body["harness_kwargs"]["title"] == "claude-code"
    assert "reasoning_effort" in body["harness_kwargs"]["properties"]
    unknown = runner.invoke(app, ["harness", "show", "cursor"])
    assert unknown.exit_code == 1
    assert builtin_schema("codex")["x-pinned-version"] == get_builtin("codex").pinned_version


def test_normalize_kwargs_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Invalid harness_kwargs"):
        normalize_kwargs("hermes", {"unknown": True})
