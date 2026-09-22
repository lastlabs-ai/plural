from __future__ import annotations

import json
from pathlib import Path

from plural.agents import AgentBinding, AgentDefinition
from plural.catalog import ModelCatalog
from plural.common import RoutingSpec
from plural.environments.definition import EnvironmentDefinition
from plural.importers.mercor import import_mercor_trial
from plural.jobs import BenchmarkJobSource, JobSpec, TrialReceipt
from plural.tasks import BenchmarkDefinition, TaskDefinition
from plural.trajectory import normalize_trajectory
from plural.verifiers import DeterministicVerifier, VerifierRuntime, WeightedVerifier


def test_trajectory_normalizes_native_formats_and_preserves_original() -> None:
    original = {
        "messages": [{"role": "assistant", "content": "working"}],
        "actions": [{"type": "action", "name": "search"}],
        "tool_results": [{"type": "tool_result", "content": "found"}],
        "observations": [{"observation": {"status": "done"}}],
        "rewards": [{"reward": 1}],
        "costs": [{"cost": 0.01}],
        "timings": [{"latency_seconds": 0.2}],
    }
    trajectory = normalize_trajectory(original)
    assert [event.kind for event in trajectory.events] == [
        "message",
        "action",
        "tool_result",
        "observation",
        "reward",
        "cost",
        "timing",
    ]
    assert trajectory.original == original
    assert trajectory.events[0].original == original["messages"][0]

    jsonl = '{"role":"user","content":"go"}\n{"type":"reasoning","text":"think"}\n'
    assert [event.kind for event in normalize_trajectory(jsonl).events] == [
        "message",
        "reasoning",
    ]


def test_trajectory_reads_atif_steps() -> None:
    document = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "codex", "model_name": "openai/gpt-5.6-sol"},
        "steps": [
            {"step_id": 1, "source": "user", "message": "Create hello.txt."},
            {
                "step_id": 2,
                "source": "agent",
                "message": "I'll create it.",
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "function_name": "write_file",
                        "arguments": {"path": "hello.txt"},
                    }
                ],
                "observation": {
                    "results": [{"source_call_id": "call-1", "content": "File created"}]
                },
            },
        ],
    }
    trajectory = normalize_trajectory(document)
    assert [event.kind for event in trajectory.events] == [
        "message",
        "message",
        "action",
        "observation",
    ]
    assert trajectory.events[2].payload["function_name"] == "write_file"
    assert trajectory.original == document


def test_planning_pins_benchmark_task_and_catalog_endpoint() -> None:
    catalog = ModelCatalog()
    catalog_model = catalog.models()[0]
    endpoint = catalog_model.ordered_endpoints()[0]
    task = TaskDefinition(
        task_id="case",
        revision="1.2.3",
        instructions="Solve",
        environment=EnvironmentDefinition(name="env"),
        verifiers=(
            WeightedVerifier(
                verifier=DeterministicVerifier(
                    name="check",
                    command=("python", "check.py"),
                    runtime=VerifierRuntime(),
                )
            ),
        ),
    )
    agent = AgentBinding(
        agent=AgentDefinition(
            name="agent",
            model=catalog_model.id,
            routing=RoutingSpec(provider=endpoint.provider),
        )
    )
    benchmark = BenchmarkDefinition(name="suite", revision="2.3.4", tasks=(task,))
    plan = JobSpec(
        source=BenchmarkJobSource(benchmark=benchmark),
        agents=(agent,),
    ).plan(catalog)
    trial = plan.trials[0]

    assert trial.benchmark is not None
    assert trial.benchmark.model_dump() == {
        "name": "suite",
        "version": "2.3.4",
        "content_hash": benchmark.content_hash,
    }
    assert trial.task_pin.name == "case"
    assert trial.task_pin.version == "1.2.3"
    assert trial.task_pin.content_hash == task.content_hash
    assert trial.model.catalog_model_id == catalog_model.id
    assert trial.model.provider == endpoint.provider
    assert trial.model.upstream_id == endpoint.upstream_id
    assert trial.model.catalog_updated_at == catalog.updated_at
    assert plan.lock.task_pins == (trial.task_pin,)
    assert plan.lock.model_resolutions == (trial.model,)


def test_mercor_import_normalizes_and_writes_unverified_bundle(tmp_path: Path) -> None:
    source = tmp_path / "mercor"
    (source / "agent").mkdir(parents=True)
    (source / "verifier").mkdir()
    (source / "artifacts").mkdir()
    (source / "config.json").write_text(
        json.dumps(
            {
                "task": {"name": "case", "version": "1.0.0"},
                "benchmark": {"name": "suite", "version": "3.0.0"},
                "trial_name": "mercor-case__abc123",
                "agent": {
                    "name": "archipelago",
                    "model_name": "text-completion-openai/Qwen3.6-35B-A3B",
                },
                "environment": {
                    "type": "modal",
                    "kwargs": {"modal_app_name": "do-not-copy"},
                },
            }
        ),
        encoding="utf-8",
    )
    (source / "agent" / "trajectory.json").write_text(
        json.dumps(
            {
                "messages": [{"role": "assistant", "content": "done"}],
                "actions": [{"type": "action", "name": "finish"}],
            }
        ),
        encoding="utf-8",
    )
    (source / "agent" / "tito_transitions.json").write_text(
        json.dumps([{"input": "a", "output": "b"}]),
        encoding="utf-8",
    )
    (source / "verifier" / "reward.json").write_text(
        json.dumps({"reward": 0.75, "evidence": ["evidence.txt"]}),
        encoding="utf-8",
    )
    (source / "trial.log").write_text("trial\n", encoding="utf-8")
    (source / "agent" / "start.log").write_text("start\n", encoding="utf-8")
    (source / "agent" / "rollout.log").write_text("complete\n", encoding="utf-8")
    (source / "verifier" / "report.txt").write_text("report\n", encoding="utf-8")
    (source / "verifier" / "grader.log").write_text("grade\n", encoding="utf-8")
    original_manifest = [
        {
            "source": "/logs/artifacts",
            "destination": "artifacts",
            "type": "directory",
            "status": "failed",
        },
        {
            "source": "/logs/missing",
            "destination": "missing",
            "type": "file",
            "status": "completed",
        },
    ]
    (source / "artifacts" / "manifest.json").write_text(
        json.dumps(original_manifest),
        encoding="utf-8",
    )

    destination = tmp_path / "imported-trial"
    imported = import_mercor_trial(source, destination=destination)
    assert imported.provenance == "imported_unverified"
    assert "environment" in imported.config
    assert "modal_app_name" not in json.dumps(imported.config)
    assert imported.score == 0.75
    assert imported.tito_transitions == [{"input": "a", "output": "b"}]
    assert [event.kind for event in imported.trajectory.events] == ["message", "action"]
    assert imported.logs == (
        "agent/rollout.log",
        "agent/start.log",
        "trial.log",
        "verifier/grader.log",
        "verifier/report.txt",
    )
    assert imported.artifact_manifest == original_manifest
    assert [item.status for item in imported.artifact_transfers] == ["failed", "completed"]

    execution = destination / "executions" / "0"
    receipt = TrialReceipt.model_validate_json(
        (execution / "receipt.json").read_text(encoding="utf-8")
    )
    assert receipt.trust == "imported_unverified"
    assert receipt.runtime_provider == "imported"
    assert receipt.model.catalog_model_id == "text-completion-openai/Qwen3.6-35B-A3B"
    assert not (execution / "artifacts/missing").exists()
    assert (execution / "logs/trial.log").read_text(encoding="utf-8") == "trial\n"
    assert (execution / "logs/agent/start.log").read_text(encoding="utf-8") == "start\n"
    assert (execution / "logs/agent/rollout.log").read_text(encoding="utf-8") == "complete\n"
    assert (execution / "logs/verifier/report.txt").read_text(encoding="utf-8") == "report\n"
    assert (execution / "logs/verifier/grader.log").read_text(encoding="utf-8") == "grade\n"
    metadata = json.loads((destination / "import.json").read_text(encoding="utf-8"))
    assert metadata["artifact_manifest"] == original_manifest
    selected = json.loads((destination / "selected.json").read_text(encoding="utf-8"))
    assert selected["execution_id"] == 0
    assert selected["receipt_hash"] == receipt.receipt_hash
