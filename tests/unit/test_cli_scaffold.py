from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from plural.cli.main import app
from plural.cli.scaffold import (
    load_agent,
    load_benchmark,
    load_environment,
    load_job,
    load_task,
    load_verifier,
    scaffold_agent,
    scaffold_benchmark,
    scaffold_environment,
    scaffold_job,
    scaffold_task,
    scaffold_verifier,
)


def project(tmp_path: Path) -> tuple[Path, Path]:
    environment = tmp_path / "environment"
    verifier = tmp_path / "verifier.yaml"
    task = tmp_path / "task.yaml"
    benchmark = tmp_path / "benchmark.yaml"
    agent = tmp_path / "agent.yaml"
    scaffold_environment(environment, "world")
    scaffold_verifier(verifier, name="exact")
    scaffold_task(
        task,
        task_id="one",
        environment_path=environment,
        verifier_paths=(verifier,),
    )
    scaffold_benchmark(benchmark, name="suite", task_paths=(task,))
    scaffold_agent(agent, name="candidate", model="test/model")
    job = scaffold_job(
        tmp_path / "job.yaml",
        source_path=benchmark,
        source_kind="benchmark",
        agent_paths=(agent,),
    )
    return job, agent


def test_scaffolds_separate_v2_packages_and_resolves_graph(tmp_path: Path) -> None:
    job, _ = project(tmp_path)
    environment = load_environment(tmp_path / "environment")
    verifier = load_verifier(tmp_path / "verifier.yaml")
    task = load_task(tmp_path / "task.yaml")
    benchmark = load_benchmark(tmp_path / "benchmark.yaml")
    spec = load_job(job)
    assert environment.schema_version == "2"
    assert verifier.kind == "deterministic"
    assert task.environment.identity == environment.identity
    assert benchmark.tasks[0].content_hash == task.content_hash
    assert spec.plan().trial_count == 1


def test_agent_yaml_has_no_environment_binding(tmp_path: Path) -> None:
    _, agent_path = project(tmp_path)
    agent = load_agent(agent_path)
    assert agent.name == "candidate"
    assert "environment" not in agent.model_dump()


def test_cli_help_exposes_v2_objects_and_watch(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("env", "task", "verifier", "agent", "benchmark", "review"):
        assert command in result.stdout
    watch = runner.invoke(app, ["job", "watch", "--help"])
    assert watch.exit_code == 0
    assert "--json" in watch.stdout


def test_direct_benchmark_dry_run_supports_mode_attempts(tmp_path: Path) -> None:
    _, agent = project(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(tmp_path / "benchmark.yaml"),
            "--agent",
            str(agent),
            "--mode",
            "eval",
            "--attempts",
            "3",
            "--concurrency",
            "2",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "eval"
    assert payload["trial_count"] == 3
    assert payload["runtimes"] == ["docker"]


def test_v1_environment_gets_clear_migration_error(tmp_path: Path) -> None:
    path = tmp_path / "environment.yaml"
    path.write_text(
        "schema_version: '1'\nname: old\ntasks: []\nverifier: null\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["env", "validate", str(path)])
    assert result.exit_code == 2
    assert "schema-v1 Environment is unsupported" in result.stderr
