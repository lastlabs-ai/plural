"""Publish one locally executed TrialExecution to a hosted Trial.

The engine writes each execution to the local store as ``receipt.json``,
``result.json``, ``logs/``, and ``artifacts/`` (with ``episode.jsonl`` when the
Harness ran through ``HarnessEnvironment``). ``publish_execution`` replays that
record through the hosted worker contracts: it opens a hosted execution,
streams episode and log events, uploads artifacts, and reports the terminal
transition with usage, phase timings, and Verifier results.

Every write is idempotent. Event keys are ``{hosted execution id}:{n}`` and
artifacts are immutable per path, so publishing the same execution twice
records it once. Nothing is estimated: a measurement the local run did not
record is omitted, and the server shows it as not reported.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from plural import __version__
from plural.execution.store import JobStore
from plural.harness.episode import EPISODE_FILE, EPISODE_SCHEMA
from plural.jobs import TrialResult, VerifierResult
from plural.studio import Studio
from plural.usage import TokenUsage, UsageTotals

EVENT_BATCH = 200
LOG_LINES_PER_EVENT = 50
_EPISODE_KINDS = {
    "environment.reset": ("observation", "environment"),
    "environment.step": ("action", "environment"),
    "model.call": ("model_call", "model"),
}
_ROLES = {
    "rendering": "rendering",
    "trajectory": "trajectory",
    "verifier_evidence": "verifier",
}
_LOGS = (
    ("stdout.log", "stdout", "harness"),
    ("stderr.log", "stderr", "harness"),
    ("verifier.stdout.log", "stdout", "verifier"),
    ("verifier.stderr.log", "stderr", "verifier"),
)


class PublishError(ValueError):
    """The local execution cannot be represented faithfully on the hosted Trial."""


@dataclass(frozen=True)
class Published:
    execution_id: str
    status: str
    events: int
    artifacts: int


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if isinstance(record, dict) and record.get("schema") == EPISODE_SCHEMA:
                records.append(record)
    return records


def episode_events(
    records: list[dict[str, Any]], *, stream_id: str, execution_id: str
) -> list[dict[str, Any]]:
    """Map episode records onto hosted progress events, keeping causal links.

    An Environment step's parent is the model call that opened its turn.
    """
    events: list[dict[str, Any]] = []
    opener: dict[int, str] = {}
    for record in records:
        mapped = _EPISODE_KINDS.get(str(record.get("kind")))
        if mapped is None:
            continue
        kind, component = mapped
        sequence = int(record["sequence"])
        key = f"{execution_id}:episode:{sequence}"
        turn = record.get("turn")
        parent = None
        if isinstance(turn, int):
            if kind == "model_call":
                opener.setdefault(turn, key)
            else:
                parent = opener.get(turn)
        payload = {
            name: value
            for name, value in record.items()
            if name not in {"schema", "kind", "sequence", "turn", "started_at", "ended_at"}
        }
        message = (
            str(record.get("action") or "step")
            if kind == "action"
            else str(record.get("model") or "model call")
            if kind == "model_call"
            else "reset"
        )
        events.append(
            {
                "stream_type": "trial",
                "stream_id": stream_id,
                "ingest_key": key,
                "timestamp": record["started_at"],
                "ended_at": record.get("ended_at"),
                "kind": kind,
                "phase": "agent_execution",
                "message": message,
                "payload": payload,
                "execution_id": execution_id,
                "source_sequence": sequence,
                "parent_key": parent,
                "turn": turn if isinstance(turn, int) else None,
                "component": component,
            }
        )
    return events


def log_events(
    logs: Path, *, stream_id: str, execution_id: str, timestamp: str, offset: int
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for name, stream, component in _LOGS:
        path = logs / name
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for start in range(0, len(lines), LOG_LINES_PER_EVENT):
            chunk = "\n".join(lines[start : start + LOG_LINES_PER_EVENT])
            events.append(
                {
                    "stream_type": "trial",
                    "stream_id": stream_id,
                    "ingest_key": f"{execution_id}:log:{name}:{start}",
                    "timestamp": timestamp,
                    "kind": "log",
                    "phase": "verification" if component == "verifier" else "agent_execution",
                    "message": "",
                    "payload": {"stream": stream, "chunk": chunk},
                    "execution_id": execution_id,
                    "source_sequence": offset + len(events),
                    "component": component,
                }
            )
    return events


def agent_usage(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Total the model calls an episode recorded. ``None`` when there were none."""
    totals = UsageTotals()
    for record in records:
        if record.get("kind") != "model.call":
            continue
        raw = record.get("usage")
        totals = totals.add(
            TokenUsage.model_validate(raw) if isinstance(raw, dict) else TokenUsage()
        )
    if totals.calls == 0:
        return None
    return {
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "cached_input_tokens": totals.cached_input_tokens,
        "calls": totals.calls,
        "calls_missing_tokens": totals.calls_missing_tokens,
        "calls_missing_cost": totals.calls_missing_cost,
        "cost_usd": totals.cost_usd,
        "cost_basis": "reported",
    }


def _hosted_results(
    results: tuple[VerifierResult, ...], pins: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_digest = {str(pin.get("content_hash")): pin for pin in pins}
    out = []
    for result in results:
        pin = by_digest.get(result.verifier_digest)
        if pin is None:
            raise PublishError(
                f"Verifier {result.verifier_name} ran at {result.verifier_digest}, which "
                "the hosted Trial does not pin. Push the same Verifier revision first."
            )
        if result.status == "awaiting_review":
            continue
        out.append(
            {
                "verifier_revision_id": pin["revision_id"],
                "verifier_name": result.verifier_name,
                "verifier_digest": result.verifier_digest,
                "kind": result.kind,
                "status": result.status,
                "score": result.score,
                "scores": dict(result.scores),
                "evidence": list(result.evidence),
                "feedback": result.feedback,
                "started_at": result.started_at.isoformat() if result.started_at else None,
                "completed_at": result.completed_at.isoformat() if result.completed_at else None,
            }
        )
    return out


def _outcome(artifacts: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    """How the episode ended, as the Harness reported it in ``result.json``."""
    path = artifacts / "result.json"
    reported: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = None
        if isinstance(raw, dict):
            reported = raw
    outcome: dict[str, Any] = {
        key: reported[key]
        for key in ("stop_reason", "terminated", "truncated", "total_reward")
        if key in reported
    }
    rewards = [
        record["reward"]
        for record in records
        if record.get("kind") == "environment.step"
        and isinstance(record.get("reward"), (int, float))
    ]
    if "total_reward" not in outcome and rewards:
        outcome["total_reward"] = float(sum(rewards))
    return outcome


def _batches(items: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(items), EVENT_BATCH):
        yield items[start : start + EVENT_BATCH]


def publish_execution(
    studio: Studio,
    trial_id: str,
    execution_root: Path,
    *,
    worker_id: str = "local",
) -> Published:
    """Report one local execution directory as an execution of hosted ``trial_id``."""
    result = TrialResult.model_validate_json(
        (execution_root / "result.json").read_text(encoding="utf-8")
    )
    receipt = result.receipt
    trial = studio.trials.get(trial_id)
    pins = trial.get("pins") or {}
    for label, local, hosted in (
        ("Environment", receipt.environment_digest, pins.get("environment")),
        ("Agent", receipt.agent_digest, pins.get("agent")),
    ):
        if hosted and local != hosted:
            raise PublishError(f"{label} {local} does not match the hosted pin {hosted}")
    verifier_results = _hosted_results(result.verifier_results, list(pins.get("verifiers") or []))

    execution = studio.trials.create_execution(
        trial_id,
        idempotency_key=f"local:{receipt.receipt_hash}",
        worker_id=worker_id,
    )
    execution_id = str(execution["id"])
    path = f"/trial-executions/{quote(execution_id)}"
    status = str(execution.get("status") or "queued")
    if status in {"succeeded", "failed", "cancelled", "awaiting_review"}:
        return Published(execution_id, status, 0, 0)
    for step in ("provisioning", "running"):
        if status in {"queued", "provisioning"} and step != status:
            studio.request(
                "POST", f"{path}/transition", json={"status": step, "worker_id": worker_id}
            )
            status = step

    artifacts_root = execution_root / "artifacts"
    records = _records(artifacts_root / EPISODE_FILE)
    events = episode_events(records, stream_id=trial_id, execution_id=execution_id)
    started = receipt.started_at or receipt.completed_at
    if started is not None:
        events += log_events(
            execution_root / "logs",
            stream_id=trial_id,
            execution_id=execution_id,
            timestamp=started.isoformat(),
            offset=len(records),
        )
    for batch in _batches(events):
        studio.request("POST", "/events/batch", json={"events": batch})

    manifest_path = artifacts_root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")).get("artifacts", [])
        if manifest_path.exists()
        else []
    )
    uploaded = 0
    for entry in manifest:
        relative = str(entry["path"])
        data = (artifacts_root / relative).read_bytes()
        studio.request(
            "POST",
            f"{path}/artifacts",
            params={
                "path": relative,
                "role": _ROLES.get(str(entry.get("role")), "output"),
                "producer": "harness",
            },
            content=data,
            content_type=str(entry.get("media_type") or "application/octet-stream"),
        )
        uploaded += 1

    usage: dict[str, Any] = {}
    agent = agent_usage(records)
    if agent is not None:
        usage["agent"] = agent
    elif receipt.cost_usd is not None:
        usage["agent"] = {"cost_usd": receipt.cost_usd, "cost_basis": "reported"}
    report: dict[str, Any] = {
        **_outcome(artifacts_root, records),
        "usage": usage,
        "phases": [phase.model_dump(mode="json") for phase in receipt.phases],
        "runtime": {
            "plural_version": __version__,
            "provider": receipt.runtime_provider,
            "worker": worker_id,
        },
    }
    final = result.status
    if final in {"succeeded", "awaiting_review"}:
        studio.request("POST", f"{path}/transition", json={"status": "verifying"})
        body: dict[str, Any] = {
            "status": "succeeded",
            "result": report,
            "verifier_results": verifier_results,
        }
    else:
        body = {
            "status": final,
            "result": report,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }
    done = studio.request("POST", f"{path}/transition", json=body)
    return Published(execution_id, str(done.get("status") or final), len(events), uploaded)


def publish_job(
    studio: Studio,
    store: JobStore,
    local_job_id: str,
    hosted_job_id: str,
    *,
    worker_id: str = "local",
) -> list[Published]:
    """Publish every execution of a local Job to the hosted Job with the same plan.

    Trials are matched on Task name, Agent name, and attempt. Every local
    execution, including failed ones, becomes a hosted execution in order, so
    retries and their cost are kept.
    """
    names = {
        binding.agent.content_hash: binding.name for binding in store.load_spec(local_job_id).agents
    }
    hosted = {
        (str(item.get("task_name")), str(item.get("agent_name")), item["attempt"]): item
        for item in studio.jobs.trials(hosted_job_id)
    }
    published: list[Published] = []
    trials_root = store.job_path(local_job_id) / "trials"
    for trial_root in sorted(path for path in trials_root.iterdir() if path.is_dir()):
        executions = sorted(
            (path for path in (trial_root / "executions").iterdir() if path.name.isdigit()),
            key=lambda path: int(path.name),
        )
        for execution_root in executions:
            receipt = TrialResult.model_validate_json(
                (execution_root / "result.json").read_text(encoding="utf-8")
            ).receipt
            key = (receipt.task_pin.name, names.get(receipt.agent_digest, ""), receipt.attempt)
            target = hosted.get(key)
            if target is None:
                raise PublishError(
                    f"No hosted Trial for Task {key[0]} attempt {key[2]} with Agent {key[1]}"
                )
            published.append(
                publish_execution(studio, str(target["id"]), execution_root, worker_id=worker_id)
            )
    return published
