from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from typer.testing import CliRunner

from plural.cli.scaffold import (
    scaffold_agent,
    scaffold_benchmark,
    scaffold_environment,
    scaffold_harness,
    scaffold_task,
    scaffold_verifier,
)

cli_main = import_module("plural.cli.main")


class _Publisher:
    def __init__(self, kind: str, calls: list[tuple[str, Any]]) -> None:
        self.kind = kind
        self.calls = calls
        self.count = 0

    def publish(self, value: Any, **references: Any) -> dict[str, Any]:
        self.count += 1
        revision_id = f"{self.kind}_revision_{self.count}"
        self.calls.append(
            (
                self.kind,
                {
                    "value": value,
                    "references": references,
                    "id": revision_id,
                },
            )
        )
        record = {"id": revision_id, "status": "published"}
        if self.kind == "environment":
            record["environment_id"] = f"environment_parent_{self.count}"
        return record

    def stamp_harness(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(("harness-evidence", payload))
        return {"id": "stamp_1", "compatible": True}


class _Jobs:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self.calls = calls

    def submit(self, spec: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("job", {"spec": spec, **kwargs}))
        return {"id": "job_1", "status": "queued", "mode": spec.mode.value}

    def watch(self, job_id: str, *, cursor: int = 0) -> Any:
        self.calls.append(("watch", {"job_id": job_id, "cursor": cursor}))
        return iter(
            (
                {
                    "sequence": 1,
                    "phase": "queued",
                    "message": "Job queued",
                    "payload": {},
                },
                {
                    "sequence": 2,
                    "phase": "running",
                    "message": "Trial running",
                    "payload": {"trial_id": "trial_1"},
                },
            )
        )


class _HostedClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.harnesses = _Publisher("harness", self.calls)
        self.environments = _Publisher("environment", self.calls)
        self.verifiers = _Publisher("verifier", self.calls)
        self.tasks = _Publisher("task", self.calls)
        self.benchmarks = _Publisher("benchmark", self.calls)
        self.agents = _Publisher("agent", self.calls)
        self.jobs = _Jobs(self.calls)

    def __enter__(self) -> _HostedClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _task_graph(tmp_path: Path) -> tuple[Path, Path]:
    environment = tmp_path / "environment"
    verifier = tmp_path / "verifier.yaml"
    task = tmp_path / "task.yaml"
    agent = tmp_path / "agent.yaml"
    scaffold_environment(environment, "world")
    scaffold_verifier(verifier, name="correct")
    scaffold_task(
        task,
        task_id="case-1",
        environment_path=environment,
        verifier_paths=(verifier,),
    )
    scaffold_agent(agent, name="candidate", model="openai/gpt-5.6-luna")
    return task, agent


def _training_benchmark_graph(tmp_path: Path) -> tuple[Path, Path]:
    first_environment = tmp_path / "environment-a"
    second_environment = tmp_path / "environment-b"
    verifier = tmp_path / "verifier.yaml"
    first_task = tmp_path / "task-a.yaml"
    second_task = tmp_path / "task-b.yaml"
    benchmark = tmp_path / "benchmark.yaml"
    harness = tmp_path / "harness"
    agent = tmp_path / "agent.yaml"
    scaffold_environment(first_environment, "world-a")
    scaffold_environment(second_environment, "world-b")
    scaffold_verifier(verifier, name="shared-correct")
    scaffold_task(
        first_task,
        task_id="case-a",
        environment_path=first_environment,
        verifier_paths=(verifier,),
    )
    scaffold_task(
        second_task,
        task_id="case-b",
        environment_path=second_environment,
        verifier_paths=(verifier,),
    )
    scaffold_benchmark(
        benchmark,
        name="mixed-suite",
        task_paths=(first_task, second_task),
    )
    scaffold_harness(harness, "training-harness")
    harness_source = harness / "harness.py"
    source = harness_source.read_text(encoding="utf-8")
    harness_source.write_text(
        source.replace(
            '    description = "Custom Agent interaction loop."\n',
            '    description = "Custom Agent interaction loop."\n    supports_tito = True\n',
        ),
        encoding="utf-8",
    )
    scaffold_agent(
        agent,
        name="candidate",
        model="openai/gpt-5.6-luna",
        harness_path=harness,
    )
    return benchmark, agent


def test_run_task_syncs_exact_ids_and_watches_by_default(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    task, agent = _task_graph(tmp_path)
    client = _HostedClient()
    monkeypatch.setattr(cli_main, "_client", lambda: client)

    result = CliRunner().invoke(
        cli_main.app,
        ["run", str(task), "--agent", str(agent), "--mode", "eval", "--hosted"],
    )

    assert result.exit_code == 0, result.output
    assert [kind for kind, _ in client.calls] == [
        "environment",
        "verifier",
        "task",
        "agent",
        "job",
        "watch",
    ]
    task_call = client.calls[2][1]
    assert task_call["references"] == {
        "environment_revision_id": "environment_revision_1",
        "verifier_revision_ids": ["verifier_revision_1"],
    }
    job_call = client.calls[4][1]
    assert job_call["source_revision_id"] == "task_revision_1"
    assert job_call["agent_revision_ids"] == ("agent_revision_1",)
    assert job_call["idempotency_key"] == job_call["spec"].job_id
    assert job_call["spec"].mode.value == "eval"
    assert '"id": "job_1"' in result.stdout
    assert "    1 queued" in result.stdout
    assert "    2 running          trial_1 Trial running" in result.stdout


def test_run_mixed_benchmark_deduplicates_dependencies_and_preserves_train_mode(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    benchmark, agent = _training_benchmark_graph(tmp_path)
    client = _HostedClient()
    monkeypatch.setattr(cli_main, "_client", lambda: client)

    result = CliRunner().invoke(
        cli_main.app,
        [
            "run",
            str(benchmark),
            "--agent",
            str(agent),
            "--mode",
            "train",
            "--idempotency-key",
            "release-42",
            "--no-watch",
            "--hosted",
        ],
    )

    assert result.exit_code == 0, result.output
    assert [kind for kind, _ in client.calls] == [
        "harness",
        "environment",
        "environment",
        "verifier",
        "task",
        "task",
        "benchmark",
        "agent",
        "harness-evidence",
        "harness-evidence",
        "job",
    ]
    assert client.verifiers.count == 1
    first_task_call = client.calls[4][1]
    second_task_call = client.calls[5][1]
    assert first_task_call["references"]["environment_revision_id"] == "environment_revision_1"
    assert second_task_call["references"]["environment_revision_id"] == "environment_revision_2"
    assert first_task_call["references"]["verifier_revision_ids"] == ["verifier_revision_1"]
    assert second_task_call["references"]["verifier_revision_ids"] == ["verifier_revision_1"]
    assert client.calls[6][1]["references"]["task_revision_ids"] == [
        "task_revision_1",
        "task_revision_2",
    ]
    assert client.calls[7][1]["references"]["harness_revision_id"] == "harness_revision_1"
    job_call = client.calls[10][1]
    assert job_call["source_revision_id"] == "benchmark_revision_1"
    assert job_call["agent_revision_ids"] == ("agent_revision_1",)
    assert job_call["idempotency_key"] == "release-42"
    assert job_call["spec"].mode.value == "train"


def test_run_json_uses_job_watch_json_lines_rendering(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    task, agent = _task_graph(tmp_path)
    client = _HostedClient()
    monkeypatch.setattr(cli_main, "_client", lambda: client)

    result = CliRunner().invoke(
        cli_main.app,
        ["run", str(task), "--agent", str(agent), "--json", "--hosted"],
    )

    assert result.exit_code == 0, result.output
    assert '{"sequence":1,"phase":"queued","message":"Job queued","payload":{}}' in result.stdout
    assert (
        '{"sequence":2,"phase":"running","message":"Trial running",'
        '"payload":{"trial_id":"trial_1"}}'
    ) in result.stdout


def test_invalid_hosted_graph_fails_before_client_or_writes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    task, agent = _task_graph(tmp_path)
    opened = 0

    def client() -> _HostedClient:
        nonlocal opened
        opened += 1
        return _HostedClient()

    monkeypatch.setattr(cli_main, "_client", client)
    result = CliRunner().invoke(
        cli_main.app,
        ["run", str(task), "--agent", str(agent), "--mode", "train", "--hosted"],
    )

    assert result.exit_code == 2
    assert "requires every selected Agent harness to support TITO" in result.stderr
    assert opened == 0


class _OfflineResult(BaseModel):
    status: Literal["succeeded"] = "succeeded"
    job_id: str = "local_job"


def test_local_default_offline_and_private_keep_execution_local(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    task, agent = _task_graph(tmp_path)
    stores: list[Path] = []

    class OfflineJob:
        def __init__(self, _: Any, **kwargs: Any) -> None:
            stores.append(kwargs["store"].root)

        async def run(self) -> _OfflineResult:
            return _OfflineResult()

    monkeypatch.setattr(cli_main, "JobRunner", OfflineJob)
    monkeypatch.setattr(
        cli_main,
        "_client",
        lambda: (_ for _ in ()).throw(AssertionError("hosted client opened")),
    )
    runner = CliRunner()
    for flag in (None, "--offline", "--private"):
        args = ["run", str(task), "--agent", str(agent), "--api-key", "test"]
        if flag is not None:
            args.append(flag)
        result = runner.invoke(
            cli_main.app,
            args,
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["job_id"] == "local_job"

    assert stores == [tmp_path / ".plural" / "jobs"] * 3
