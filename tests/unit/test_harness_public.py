from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import plural
from plural import Agent, Environment, Harness, Job, Runtime, Task
from plural.cli.main import app
from plural.project import dump, load
from plural.verifiers import DeterministicVerifier

ROOT = Path(__file__).resolve().parents[2]
BANNED = re.compile(
    r"\bschema_version\b|\bprotocol_adapter\b|\bprotocol\b"
    r"|\bdefinition\b|\bbinding\b|\bpackage\b|_v1\b",
    re.IGNORECASE,
)


def _harness(source: Path) -> Harness:
    source.mkdir()
    module = source / "harness.py"
    module.write_text(
        """
from plural import Harness, HarnessResult

class CustomHarness(Harness):
    name = "custom-loop"
    version = "1.2.3"
    description = "A custom interaction loop."
    secrets = ("OPENAI_API_KEY",)

    def run(self, task, agent, environment):
        return HarnessResult(response=task.instructions)
""".lstrip(),
        encoding="utf-8",
    )
    value = load(f"{module}:CustomHarness")
    assert isinstance(value, Harness)
    return value


def _job(harness: Harness) -> Job:
    task = Task(
        name="case",
        instructions="Complete the case.",
        environment=Environment(name="world", runtime=Runtime.docker()),
        verifiers=(DeterministicVerifier(name="done", check="python verify.py"),),
    )
    return Job(
        task,
        agents=(Agent(model="openai/gpt-5.6-luna", harness=harness),),
    )


def test_public_harness_class_and_exports_hide_internals(tmp_path: Path) -> None:
    harness = _harness(tmp_path / "runner")
    package = harness._package()
    assert package.definition.command[2] == "plural.harness.class_runner"
    assert package.definition.outputs[0].path == "result.json"
    assert package.definition.trajectory_path == "trajectory.jsonl"
    assert Harness is plural.Harness
    assert "HarnessResult" in plural.__all__
    assert "HarnessEnvironment" in plural.__all__
    assert "HarnessPackage" not in plural.__all__
    assert "PackageSource" not in plural.__all__
    assert BANNED.search(" ".join(Harness.model_fields)) is None
    assert BANNED.search(str(Harness.model_json_schema())) is None


def test_harness_and_agent_yaml_roundtrip_preserves_hash_and_plan(tmp_path: Path) -> None:
    harness = _harness(tmp_path / "runner")
    harness_path = dump(harness, tmp_path / "harness.yaml")
    harness_yaml = harness_path.read_text(encoding="utf-8")
    assert BANNED.search(harness_yaml) is None
    restored_harness = load(harness_path)
    assert isinstance(restored_harness, Harness)
    assert restored_harness.content_hash == harness.content_hash

    job = _job(harness)
    job_path = dump(job, tmp_path / "job.yaml")
    job_yaml = job_path.read_text(encoding="utf-8")
    agent_yaml = job_yaml.split("agents:", 1)[1]
    assert BANNED.search(agent_yaml) is None
    restored_job = load(job_path)
    assert isinstance(restored_job, Job)
    assert restored_job.content_hash == job.content_hash
    assert restored_job.plan == job.plan


def test_public_agent_rejects_secret_not_declared_by_harness(tmp_path: Path) -> None:
    harness = _harness(tmp_path / "runner")
    with pytest.raises(ValueError, match="not declared by Harness"):
        Agent(
            model="openai/gpt-5.6-luna",
            harness=harness,
            secret_names=("ANTHROPIC_API_KEY",),
        )


def test_harness_cli_scaffold_and_validate_are_plain(tmp_path: Path) -> None:
    runner = CliRunner()
    created = runner.invoke(
        app,
        ["harness", "init", str(tmp_path / "custom"), "--name", "custom"],
    )
    assert created.exit_code == 0, created.output
    emitted = (tmp_path / "custom" / "harness.yaml").read_text(encoding="utf-8")
    assert BANNED.search(emitted) is None
    implementation = (tmp_path / "custom" / "harness.py").read_text(encoding="utf-8")
    assert "class CustomHarness(Harness)" in implementation
    assert "def run(" in implementation
    assert "command=" not in implementation
    assert "source=" not in implementation
    validated = runner.invoke(app, ["harness", "validate", str(tmp_path / "custom")])
    assert validated.exit_code == 0, validated.output


def test_current_harness_docs_and_examples_hide_internal_tokens() -> None:
    paths = (
        ROOT / "docs/project/harnesses.md",
        ROOT / "docs/concepts/harness-policy.md",
        ROOT / "examples/wordle/advanced.py",
        ROOT / "examples/wordle/harness.py",
        ROOT / "examples/jobs/minimal_harness/harness.yaml",
        ROOT / "examples/jobs/minimal_harness/harness.py",
        ROOT / "examples/jobs/README.md",
    )
    for path in paths:
        assert BANNED.search(path.read_text(encoding="utf-8")) is None, path
