from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import ValidationError
from typer.testing import CliRunner

from plural.cli.main import app
from plural.cli.scaffold import (
    allow_harness,
    load_agent,
    load_environment,
    load_harness,
    load_job,
    scaffold_agent,
    scaffold_benchmark,
    scaffold_environment,
    scaffold_harness,
    scaffold_job,
)


def _project(tmp_path: Path) -> Path:
    environment = tmp_path / "environment"
    harness = tmp_path / "harness"
    scaffold_environment(environment, "demo")
    scaffold_harness(harness, "chat")
    allow_harness(environment, harness)
    benchmark = scaffold_benchmark(
        tmp_path / "benchmark.yaml",
        name="demo-benchmark",
        environment_path=environment,
    )
    agent = scaffold_agent(
        tmp_path / "agent.yaml",
        name="demo-agent",
        model="openai/model",
        environment_path=environment,
        harness_path=harness,
    )
    return scaffold_job(
        tmp_path / "job.yaml",
        environment_path=environment,
        benchmark_path=benchmark,
        agent_paths=(agent,),
    )


def test_scaffolds_all_foundational_files_and_validates(tmp_path: Path) -> None:
    job_path = _project(tmp_path)

    assert (tmp_path / "environment" / "environment.yaml").exists()
    assert (tmp_path / "environment" / "environment.py").exists()
    assert (tmp_path / "environment" / "tasks.jsonl").exists()
    assert (tmp_path / "environment" / "Dockerfile").exists()
    assert (tmp_path / "harness" / "harness.yaml").exists()
    assert (tmp_path / "benchmark.yaml").exists()
    assert (tmp_path / "agent.yaml").exists()
    assert job_path.exists()

    environment = load_environment(tmp_path / "environment")
    assert [task.task_id for task in environment.tasks] == ["example"]
    plan = load_job(job_path).plan()
    assert plan.trial_count == 1


def test_environment_yaml_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "environment.yaml"
    path.write_text(
        "schema_version: '1'\nname: demo\nrevision: 0.1.0\nunknown: true\n",
        encoding="utf-8",
    )
    try:
        load_environment(path)
    except ValidationError as exc:
        assert "unknown" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown config field was accepted")


def test_cli_help_and_machine_readable_dry_run(tmp_path: Path) -> None:
    job_path = _project(tmp_path)
    runner = CliRunner()
    environment = {"PLURAL_CONFIG_HOME": str(tmp_path / "config")}

    help_result = runner.invoke(app, ["--help"], env=environment)
    assert help_result.exit_code == 0
    assert "benchmark" in help_result.stdout
    assert "harness" in help_result.stdout
    assert "runtime" in help_result.stdout

    result = runner.invoke(
        app,
        [
            "run",
            str(job_path),
            "--dry-run",
            "--n-attempts",
            "2",
            "--retry",
            "4",
            "--format",
            "json",
            "--no-sync",
        ],
        env=environment,
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["sync"] is False
    assert payload["trial_count"] == 2
    assert len(payload["trials"]) == 2
    assert [item["attempt"] for item in payload["trials"]] == [1, 2]

    default_result = runner.invoke(
        app,
        ["run", str(job_path), "--dry-run", "--format", "json"],
        env=environment,
    )
    assert default_result.exit_code == 0
    assert json.loads(default_result.stdout)["sync"] is False


def test_cli_does_not_claim_execution_succeeded(tmp_path: Path) -> None:
    job_path = _project(tmp_path)
    result = CliRunner().invoke(
        app,
        ["run", str(job_path), "--runtime", "local"],
        env={"PLURAL_CONFIG_HOME": str(tmp_path / "config")},
    )
    assert result.exit_code == 2
    assert any(
        token in result.stderr
        for token in ("unsafe_local", "not configured", "cannot enforce network")
    )


def test_cli_executes_and_persists_unsafe_local_job(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            request = json.loads(self.rfile.read(length))
            assert request["model"] == "openai/model"
            payload = json.dumps(
                {
                    "model": request["model"],
                    "choices": [{"message": {"role": "assistant", "content": "done"}}],
                    "usage": {},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    job_path = _project(tmp_path)
    try:
        result = CliRunner().invoke(
            app,
            ["run", str(job_path), "--unsafe-local", "--format", "json"],
            env={
                "PLURAL_CONFIG_HOME": str(tmp_path / "config"),
                "PLURAL_GATEWAY_URL": f"http://127.0.0.1:{server.server_port}/v1",
                "PLURAL_ALLOW_NO_AUTH": "1",
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert result.exit_code == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["trials"][0]["status"] == "succeeded"
    assert (tmp_path / ".plural/jobs" / payload["job_id"] / "result.json").exists()


def test_cli_builds_and_inspects_verified_harness_archive(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    scaffold_harness(harness, "archive-test")
    runner = CliRunner()
    built = runner.invoke(app, ["harness", "build", str(harness)])
    assert built.exit_code == 0, built.stderr
    artifact = json.loads(built.stdout)

    inspected = runner.invoke(
        app,
        [
            "harness",
            "inspect",
            artifact["artifact"],
            "--digest",
            artifact["digest"],
        ],
    )
    assert inspected.exit_code == 0, inspected.stderr
    assert json.loads(inspected.stdout)["package"]["source"]["kind"] == "archive"


def test_local_harness_binding_tracks_source_tree_changes(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    scaffold_harness(harness, "digest-test")
    first = load_harness(harness)
    assert first.source.digest is not None
    assert first.source.unsafe_local is True

    (harness / "harness.py").write_text("print('changed')\n", encoding="utf-8")
    second = load_harness(harness)
    assert second.source.digest != first.source.digest
    assert second.package_id != first.package_id


def test_published_harness_add_and_agent_use_archive_binding(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    harness = tmp_path / "harness"
    scaffold_environment(environment, "demo")
    scaffold_harness(harness, "published")
    runner = CliRunner()
    published = runner.invoke(app, ["harness", "publish", str(harness)])
    assert published.exit_code == 0, published.stderr
    archive = json.loads(published.stdout)

    added = runner.invoke(
        app,
        [
            "harness",
            "add",
            archive["published"],
            "--digest",
            archive["digest"],
            "--environment",
            str(environment),
        ],
    )
    assert added.exit_code == 0, added.stderr
    agent_path = scaffold_agent(
        tmp_path / "agent.yaml",
        name="published-agent",
        model="openai/model",
        environment_path=environment,
        harness_path=archive["published"],
        harness_digest=archive["digest"],
    )
    loaded = load_agent(agent_path)
    assert loaded.harness_package is not None
    assert loaded.harness_package.source.kind == "archive"
    assert loaded.harness.digest == archive["digest"]
