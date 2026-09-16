from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from plural import Agent, Harness, HarnessEnvironment
from plural.cli.scaffold import load_harness_reference
from plural.harness import class_runner
from plural.harness.retrieval import build_archive, package_from_archive
from plural.project import dump, load


def _write_harness(root: Path, *, asynchronous: bool = False) -> Path:
    module = root / "custom.py"
    keyword = "async " if asynchronous else ""
    module.write_text(
        f"""
from plural import Harness, HarnessResult

class SupportHarness(Harness):
    name = "support-loop"
    version = "1.0.0"

    {keyword}def run(self, task, agent, environment):
        observation = environment.reset()
        observation = environment.step("answer", value=task.info["value"])
        return HarnessResult(
            response=observation,
            trajectory=({{"type": "action", "observation": observation}},),
            logs=("finished",),
            metadata={{"custom": self.config.get("label", "default")}},
            trace_id="trace-custom",
        )
""".lstrip(),
        encoding="utf-8",
    )
    return module


def _request(environment_root: Path) -> dict[str, object]:
    return {
        "task": {
            "task_id": "case-1",
            "instructions": "Answer the task.",
            "info": {"value": "done"},
        },
        "agent": {
            "name": "agent",
            "model": "openai/gpt-5.6-luna",
            "instructions": "Be concise.",
        },
        "environment": {
            "name": "world",
            "workspace": str(environment_root),
            "observation": {"status": "new"},
            "reset_command": [
                "python",
                "-c",
                'import json; print(json.dumps({"status": "ready"}))',
            ],
            "actions": [
                {
                    "name": "answer",
                    "description": "Answer the task.",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                    "command": [
                        "python",
                        "-c",
                        (
                            "import json,sys; value=json.loads(sys.stdin.read()); "
                            'print(json.dumps({"status":"complete","value":value["value"]}))'
                        ),
                    ],
                }
            ],
        },
    }


@pytest.mark.parametrize("asynchronous", [False, True])
def test_class_runner_standardizes_sync_and_async_harnesses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    asynchronous: bool,
) -> None:
    module = _write_harness(tmp_path, asynchronous=asynchronous)
    environment = tmp_path / "environment"
    environment.mkdir()
    execution = tmp_path / "execution"
    execution.mkdir()
    monkeypatch.chdir(execution)
    monkeypatch.setattr(
        class_runner.sys,
        "stdin",
        io.StringIO(json.dumps(_request(environment)) + "\n"),
    )

    class_runner.main([f"{module}:SupportHarness", '{"label":"test"}'])

    result = json.loads((execution / "result.json").read_text(encoding="utf-8"))
    assert result["response"] == {"status": "complete", "value": "done"}
    assert result["custom"] == "test"
    assert result["trace_id"] == "trace-custom"
    assert "finished" in (execution / "logs.txt").read_text(encoding="utf-8")
    trajectory = json.loads((execution / "trajectory.jsonl").read_text(encoding="utf-8"))
    assert trajectory["observation"]["status"] == "complete"
    terminal = json.loads(capsys.readouterr().out)
    assert terminal["outputs"] == ["result.json"]
    assert terminal["artifacts"] == ["trajectory.jsonl", "logs.txt"]


def test_environment_tools_and_unknown_action_are_clear() -> None:
    environment = HarnessEnvironment(
        {
            "actions": [
                {
                    "name": "lookup",
                    "description": "Look up a record.",
                    "parameters": {"type": "object"},
                    "command": ["python", "-c", "print('{}')"],
                }
            ]
        }
    )
    assert environment.tools()[0]["function"]["name"] == "lookup"
    with pytest.raises(ValueError, match="available actions: lookup"):
        environment.step("missing")


def test_class_source_and_config_are_in_harness_and_agent_hash(
    tmp_path: Path,
) -> None:
    module = _write_harness(tmp_path)
    first = load(f"{module}:SupportHarness")
    assert isinstance(first, Harness)
    configured = type(first)(config={"label": "one"})
    configured._bind_source(module)
    changed = type(first)(config={"label": "two"})
    changed._bind_source(module)
    assert configured.content_hash != changed.content_hash
    first_agent = Agent(model="openai/gpt-5.6-luna", harness=configured)
    changed_agent = Agent(model="openai/gpt-5.6-luna", harness=changed)
    assert first_agent.content_hash != changed_agent.content_hash

    path = dump(first_agent, tmp_path / "agent.yaml")
    text = path.read_text(encoding="utf-8")
    assert "python: custom.py:SupportHarness" in text
    assert "command:" not in text
    restored = load(path)
    assert isinstance(restored, Agent)
    assert restored.content_hash == first_agent.content_hash


def test_class_harness_archive_preserves_package_and_yaml_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_harness(source)
    (source / "harness.yaml").write_text(
        "kind: harness\npython: custom.py:SupportHarness\n",
        encoding="utf-8",
    )
    archive = tmp_path / "harness.tar.gz"
    digest = build_archive(source, archive)

    package = package_from_archive(
        str(archive),
        digest,
        cache_root=tmp_path / "cache",
    )
    assert package.source.kind == "archive"
    assert package.definition.command[-2] == "custom.py:SupportHarness"

    harness = load_harness_reference(
        str(archive),
        digest=digest,
        cache_root=tmp_path / "cache",
    )
    agent = Agent(model="openai/gpt-5.6-luna", harness=harness)
    path = dump(agent, tmp_path / "archived-agent.yaml")
    text = path.read_text(encoding="utf-8")
    assert f"archive: {archive}" in text
    assert f"digest: {digest}" in text
    restored = load(path)
    assert isinstance(restored, Agent)
    assert restored.content_hash == agent.content_hash
