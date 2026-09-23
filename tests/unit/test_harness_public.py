from __future__ import annotations

import re
from pathlib import Path

import pytest
from project_fixtures import write_project
from typer.testing import CliRunner

import plural
from plural import Agent, Environment, Harness, Job, Runtime, Task
from plural.cli.main import app
from plural.project import Project, ResourceRef, Workspace
from plural.project.resources import load_harness_directory
from plural.verifiers import DeterministicVerifier

ROOT = Path(__file__).resolve().parents[2]
BANNED = re.compile(
    r"\bschema_version\b|\bprotocol_adapter\b|\bprotocol\b"
    r"|\bdefinition\b|\bbinding\b|\bpackage\b|_v1\b",
    re.IGNORECASE,
)


HARNESS_YAML = """\
name: custom-loop
version: 1.2.3
description: A custom interaction loop.
python: harness.py:CustomHarness
"""


def _harness(source: Path) -> Harness:
    source.mkdir(parents=True)
    (source / "harness.yaml").write_text(HARNESS_YAML, encoding="utf-8")
    (source / "harness.py").write_text(
        """
from plural import Harness, HarnessResult

class CustomHarness(Harness):
    secrets = ("OPENAI_API_KEY",)

    def run(self, task, agent, environment):
        return HarnessResult(response=task.instructions)
""".lstrip(),
        encoding="utf-8",
    )
    return load_harness_directory(source, name="custom-loop")


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


def test_harness_and_agent_manifests_preserve_hash_and_plan(tmp_path: Path) -> None:
    project = write_project(tmp_path / "support-desk")
    harness = _harness(project.root / "harnesses/custom-loop")
    assert type(harness).name == "custom-loop"
    assert type(harness).version == "1.2.3"
    assert BANNED.search(HARNESS_YAML) is None
    agent_yaml = (
        "name: baseline\nversion: 0.1.0\nmodel: openai/gpt-5.6-luna\nharness: custom-loop\n"
    )
    (project.root / "agents/baseline/agent.yaml").write_text(agent_yaml, encoding="utf-8")
    assert BANNED.search(agent_yaml) is None

    space = Workspace(Project.at(project.root))
    restored_harness = space.load(ResourceRef("harness", "custom-loop")).value
    assert restored_harness.content_hash == harness.content_hash
    restored_agent = space.load(ResourceRef("agent", "baseline")).value
    agent = Agent(model="openai/gpt-5.6-luna", name="baseline", harness=harness)
    assert restored_agent.content_hash == agent.content_hash
    job = Job(_job(harness).source, agents=(agent,))
    restored_job = Job(job.source, agents=(restored_agent,))
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


def test_harness_cli_scaffold_is_plain_and_unfinished_until_filled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    project = write_project(tmp_path / "support-desk")
    monkeypatch.chdir(project.root)
    runner = CliRunner()
    created = runner.invoke(app, ["harness", "init", "custom"])
    assert created.exit_code == 0, created.output
    directory = project.root / "harnesses/custom"
    emitted = (directory / "harness.yaml").read_text(encoding="utf-8")
    assert BANNED.search(emitted) is None
    implementation = (directory / "harness.py").read_text(encoding="utf-8")
    assert "class CustomHarness(Harness)" in implementation
    assert "def run(" in implementation
    assert "command=" not in implementation
    assert "source=" not in implementation
    validated = runner.invoke(app, ["harness", "validate", "custom"])
    assert validated.exit_code == 1
    assert "harnesses/custom/harness.py:" in validated.output
    assert "unfinished scaffold" in validated.output


def test_current_harness_docs_and_examples_hide_internal_tokens() -> None:
    paths = (
        ROOT / "docs/project/harnesses.md",
        ROOT / "docs/concepts/harness-policy.md",
        ROOT / "examples/wordle/harnesses/word-list/harness.yaml",
        ROOT / "examples/wordle/harnesses/word-list/harness.py",
        ROOT / "examples/first-project/harnesses/scripted-triage/harness.yaml",
        ROOT / "examples/first-project/harnesses/scripted-triage/harness.py",
        ROOT / "examples/jobs/minimal_harness/harness.yaml",
        ROOT / "examples/jobs/minimal_harness/harness.py",
        ROOT / "examples/jobs/README.md",
    )
    for path in paths:
        assert BANNED.search(path.read_text(encoding="utf-8")) is None, path
