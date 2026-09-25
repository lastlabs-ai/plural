from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from plural import Agent, Harness, HarnessEnvironment
from plural.harness import class_runner
from plural.harness.retrieval import build_archive, extract_archive, package_from_archive
from plural.project.resources import load_harness_directory


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
        step = environment.step("answer", value=task.info["value"])
        return HarnessResult(
            response=step.observation,
            trajectory=(
                {{
                    "type": "action",
                    "observation": step.observation,
                    "reward": step.reward,
                    "terminated": step.terminated,
                }},
            ),
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
    assert terminal["artifacts"] == ["trajectory.jsonl", "logs.txt", "episode.jsonl"]
    episode = [
        json.loads(line)
        for line in (execution / "episode.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["kind"] for record in episode] == ["environment.reset", "environment.step"]
    step = episode[1]
    assert step["schema"] == "plural.episode/v1"
    assert step["action"] == "answer"
    assert step["arguments"] == {"value": "done"}
    assert step["observation"] == {"status": "complete", "value": "done"}
    assert step["turn"] == 1
    assert step["duration_ms"] >= 0


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


def _harness_package(root: Path, *, config: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write_harness(root)
    (root / "harness.yaml").write_text(
        "name: support-loop\nversion: 1.0.0\npython: custom.py:SupportHarness\n" + config,
        encoding="utf-8",
    )
    return root


def test_class_source_and_config_are_in_harness_and_agent_hash(
    tmp_path: Path,
) -> None:
    source = _harness_package(tmp_path / "support-loop")
    first = load_harness_directory(source, name="support-loop")
    assert isinstance(first, Harness)
    configured = type(first)(config={"label": "one"})
    configured._bind_source(source)
    changed = type(first)(config={"label": "two"})
    changed._bind_source(source)
    assert configured.content_hash != changed.content_hash
    first_agent = Agent(model="openai/gpt-5.6-luna", harness=configured)
    changed_agent = Agent(model="openai/gpt-5.6-luna", harness=changed)
    assert first_agent.content_hash != changed_agent.content_hash

    _harness_package(source, config="config:\n  label: one\n")
    from_manifest = load_harness_directory(source, name="support-loop")
    assert from_manifest.config == {"label": "one"}
    assert from_manifest.content_hash == configured.content_hash
    before = from_manifest.content_hash

    (source / "custom.py").write_text(
        (source / "custom.py").read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8"
    )
    edited = load_harness_directory(source, name="support-loop")
    assert edited.content_hash != before


def test_class_harness_archive_preserves_package_and_python_reference(
    tmp_path: Path,
) -> None:
    source = _harness_package(tmp_path / "source")
    original = load_harness_directory(source, name="support-loop")
    archive = tmp_path / "harness.tar.gz"
    digest = build_archive(source, archive)

    package = package_from_archive(
        str(archive),
        digest,
        cache_root=tmp_path / "cache",
    )
    assert package.source.kind == "archive"
    assert package.definition.command[-2] == "custom.py:SupportHarness"

    restored_root = tmp_path / "restored"
    extract_archive(archive.read_bytes(), restored_root)
    restored = load_harness_directory(restored_root, name="support-loop")
    assert restored.content_hash == original.content_hash
    agent = Agent(model="openai/gpt-5.6-luna", harness=original)
    assert Agent(model="openai/gpt-5.6-luna", harness=restored).content_hash == agent.content_hash
