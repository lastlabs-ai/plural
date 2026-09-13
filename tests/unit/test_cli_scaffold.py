from __future__ import annotations

import json
from pathlib import Path

from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from plural.cli.main import app


def test_cli_help_leads_with_public_object_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init", "validate", "inspect", "export", "run", "models", "benchmarks", "auth"):
        assert command in result.stdout
    root = get_command(app)
    assert isinstance(root, TyperGroup)
    for compatibility_group in ("env", "task", "verifier", "agent", "harness", "benchmark"):
        assert root.commands[compatibility_group].hidden
    assert "watch" in root.commands["job"].commands


def test_init_creates_python_first_project(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "project.py").is_file()
    assert (tmp_path / "project.yaml").read_text().startswith("kind: job")
    validated = CliRunner().invoke(app, ["validate", str(tmp_path / "project.yaml")])
    assert validated.exit_code == 0, validated.output


def test_direct_benchmark_dry_run_supports_overrides(tmp_path: Path) -> None:
    project = tmp_path / "project.py"
    project.write_text(
        "from plural import Agent, Benchmark, Environment, Task\n"
        "from plural.verifiers import DeterministicVerifier\n"
        "environment = Environment(name='world')\n"
        "verifier = DeterministicVerifier(name='done', check='python verify.py')\n"
        "task = Task(name='one', instructions='Do it', environment=environment, "
        "verifiers=[verifier])\n"
        "benchmark = Benchmark(name='suite', version='1.0.0', tasks=[task])\n"
        "agent = Agent(model='openai/gpt-5.6-luna')\n"
    )
    result = CliRunner().invoke(
        app,
        [
            "run",
            f"{project}:benchmark",
            "--agent",
            f"{project}:agent",
            "--attempts",
            "3",
            "--concurrency",
            "2",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["mode"] == "eval"
    assert payload["trial_count"] == 3
    assert payload["runtimes"] == ["docker"]


def test_old_environment_manifest_gets_clean_break_error(tmp_path: Path) -> None:
    path = tmp_path / "environment.yaml"
    path.write_text(
        "schema_version: '1'\nname: old\ntasks: []\nverifier: null\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["validate", str(path)])
    assert result.exit_code == 2
    assert "schema-v1 Environment is unsupported" in result.stderr
