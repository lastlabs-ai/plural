from __future__ import annotations

import json
from pathlib import Path

import pytest
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
from plural.project import dump, load
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


def test_python_and_yaml_roundtrip_keep_compact_builtin(tmp_path: Path) -> None:
    agent = Agent(
        model="anthropic/claude-sonnet-5",
        harness="claude-code",
        harness_kwargs={"permission_mode": "acceptEdits"},
    )
    job = Job(_task(), agents=(agent,))
    path = dump(job, tmp_path / "job.yaml")
    text = path.read_text(encoding="utf-8")
    assert "harness: claude-code" in text
    assert "permission_mode: acceptEdits" in text
    assert "kind: harness" not in text.split("agents:", 1)[1]
    restored = load(path)
    assert isinstance(restored, Job)
    restored_agent = restored.agents[0]
    assert restored_agent.harness == "claude-code"
    assert restored_agent.harness_kwargs["permission_mode"] == "acceptEdits"
    assert restored_agent.content_hash == agent.content_hash
    assert restored.content_hash == job.content_hash
    assert restored.plan == job.plan


def test_legacy_declared_vendor_harness_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "harness.yaml"
    path.write_text(
        "kind: harness\nname: hermes\nimplementation: declared\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="built-in now"):
        load(path)


def test_custom_class_harness_roundtrips(tmp_path: Path) -> None:
    source = tmp_path / "runner"
    source.mkdir()
    module = source / "harness.py"
    module.write_text(
        """
from plural import Harness, HarnessResult

class CustomHarness(Harness):
    name = "custom-loop"

    def run(self, task, agent, environment):
        return HarnessResult(response=task.instructions)
""".lstrip(),
        encoding="utf-8",
    )
    harness = load(f"{module}:CustomHarness")
    assert isinstance(harness, Harness)
    agent = Agent(model="openai/gpt-5.6-luna", harness=harness)
    path = dump(agent, tmp_path / "agent.yaml")
    restored = load(path)
    assert isinstance(restored, Agent)
    assert isinstance(restored.harness, Harness)
    assert type(restored.harness).name == "custom-loop"
    assert restored.content_hash == agent.content_hash


def test_cli_lists_builtins_and_emits_schema() -> None:
    runner = CliRunner()
    listed = runner.invoke(app, ["harness", "list"])
    assert listed.exit_code == 0, listed.output
    payload = json.loads(listed.output)
    names = {item["name"] for item in payload}
    assert set(BUILTIN_HARNESS_NAMES) <= names
    schema = runner.invoke(app, ["harness", "schema", "claude-code"])
    assert schema.exit_code == 0, schema.output
    body = json.loads(schema.output)
    assert body["title"] == "claude-code"
    assert "reasoning_effort" in body["properties"]
    unknown = runner.invoke(app, ["harness", "schema", "cursor"])
    assert unknown.exit_code == 2
    assert builtin_schema("codex")["x-pinned-version"] == get_builtin("codex").pinned_version


def test_normalize_kwargs_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Invalid harness_kwargs"):
        normalize_kwargs("hermes", {"unknown": True})
