"""Publish one locally executed TrialExecution to a hosted Trial.

The engine writes each execution to the local store as ``receipt.json``,
``result.json``, ``logs/``, and ``artifacts/`` (with ``episode.jsonl`` when the
Harness ran through ``HarnessEnvironment``). ``publish_execution`` replays that
record through the hosted worker contracts: it opens a hosted execution,
streams episode and log events, uploads artifacts, and reports the terminal
transition with usage, phase timings, and Verifier results.

Every write is idempotent. A hosted execution is keyed by the local Job,
Trial, and execution number, event keys are ``{hosted execution id}:{n}``, and
artifacts are immutable per path, so publishing the same execution twice
records it once. Nothing is estimated: a measurement the local run did not
record is omitted, and the server shows it as not reported.

``HostedTracker`` does the same while a Job runs: attached to a ``JobStore``,
it opens each hosted execution when the local one starts, keeps it alive with
heartbeats, and publishes it when it finishes.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from plural import __version__
from plural.execution.store import JobStore
from plural.harness.episode import EPISODE_FILE, EPISODE_SCHEMA
from plural.jobs import JobPlan, JobSpec, ProgressEvent, TrialResult, VerifierResult
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


AgentPin = tuple[str, str]
"""The hosted Agent a local binding ran as: its name and definition hash."""

_FINISHED = {"succeeded", "failed", "cancelled", "awaiting_review"}
_ADVANCE = {"queued": 0, "stale": 0, "provisioning": 1, "running": 2}


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


def execution_key(job_id: str, trial_id: str, execution_id: int) -> str:
    """Idempotency key of one local execution, known before it starts."""
    return f"local:{job_id}:{trial_id}:{execution_id}"


def agent_pins(spec: JobSpec) -> dict[str, AgentPin]:
    """Each Agent binding of ``spec`` as the hosted Agent of the same definition."""
    return {
        binding.content_hash: (binding.name, binding.agent.content_hash) for binding in spec.agents
    }


def _advance(studio: Studio, execution_id: str, status: str, worker_id: str, until: str) -> str:
    """Move a hosted execution forward through provisioning to ``until``."""
    steps = ("provisioning", "running")
    if status not in _ADVANCE or _ADVANCE[status] > steps.index(until):
        return status
    for step in steps[_ADVANCE[status] : steps.index(until) + 1]:
        studio.request(
            "POST",
            f"/trial-executions/{quote(execution_id)}/transition",
            json={"status": step, "worker_id": worker_id},
        )
    return until


def publish_execution(
    studio: Studio,
    trial_id: str,
    execution_root: Path,
    *,
    worker_id: str = "local",
    agent_definition: str | None = None,
) -> Published:
    """Report one local execution directory as an execution of hosted ``trial_id``.

    A receipt records the Agent binding's digest; the hosted pin is the Agent
    definition's. Pass ``agent_definition`` so the two can be compared.
    """
    result = TrialResult.model_validate_json(
        (execution_root / "result.json").read_text(encoding="utf-8")
    )
    receipt = result.receipt
    trial = studio.trials.get(trial_id)
    pins = trial.get("pins") or {}
    for label, local, hosted in (
        ("Environment", receipt.environment_digest, pins.get("environment")),
        ("Agent", agent_definition or receipt.agent_digest, pins.get("agent")),
    ):
        if hosted and local != hosted:
            raise PublishError(f"{label} {local} does not match the hosted pin {hosted}")
    verifier_results = _hosted_results(result.verifier_results, list(pins.get("verifiers") or []))

    execution = studio.trials.create_execution(
        trial_id,
        idempotency_key=execution_key(receipt.job_id, receipt.trial_id, receipt.execution_id),
        worker_id=worker_id,
    )
    execution_id = str(execution["id"])
    path = f"/trial-executions/{quote(execution_id)}"
    status = str(execution.get("status") or "queued")
    if status in {"succeeded", "failed", "cancelled", "awaiting_review"}:
        return Published(execution_id, status, 0, 0)
    status = _advance(studio, execution_id, status, worker_id, "running")

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


def _hosted_trials(studio: Studio, hosted_job_id: str) -> dict[tuple[str, str, int], str]:
    return {
        (str(item.get("task_name")), str(item.get("agent_name")), int(item["attempt"])): str(
            item["id"]
        )
        for item in studio.jobs.trials(hosted_job_id)
    }


def publish_job(
    studio: Studio,
    store: JobStore,
    local_job_id: str,
    hosted_job_id: str,
    *,
    worker_id: str = "local",
    agents: Mapping[str, AgentPin] | None = None,
) -> list[Published]:
    """Publish every execution of a local Job to the hosted Job with the same plan.

    Trials are matched on Task name, Agent name, and attempt. Every local
    execution, including failed ones, becomes a hosted execution in order, so
    retries and their cost are kept. ``agents`` maps each local Agent binding
    to the hosted Agent it ran as; by default, the Agent of the same name and
    definition.
    """
    pins = dict(agents) if agents is not None else agent_pins(store.load_spec(local_job_id))
    hosted = _hosted_trials(studio, hosted_job_id)
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
            name, definition = pins.get(receipt.agent_digest, ("", None))
            key = (receipt.task_pin.name, name, receipt.attempt)
            target = hosted.get(key)
            if target is None:
                raise PublishError(
                    f"No hosted Trial for Task {key[0]} attempt {key[2]} with Agent {key[1]}"
                )
            published.append(
                publish_execution(
                    studio,
                    target,
                    execution_root,
                    worker_id=worker_id,
                    agent_definition=definition,
                )
            )
    return published


class HostedTracker:
    """Report a local Job to its hosted client Job while it runs.

    Pass :meth:`observe` as the ``JobStore``'s ``on_event``. Reporting runs on
    one background thread, so the engine never waits on the network, and each
    request is idempotent: ``publish_job`` finishes anything tracking could
    not. A failure is recorded in ``errors`` and never stops the local run.

    Args:
        studio: Hosted API addressed to the project that holds the Job.
        store: The store the local Job writes to.
        spec: The local Job.
        plan: The local Job's plan, as the runner computed it.
        hosted_job_id: The hosted Job, created with executor ``client``.
        agents: Each local Agent binding's hosted Agent, as ``agent_pins``.
        heartbeat_seconds: How often running executions report liveness.
    """

    def __init__(
        self,
        studio: Studio,
        store: JobStore,
        spec: JobSpec,
        plan: JobPlan,
        hosted_job_id: str,
        *,
        agents: Mapping[str, AgentPin],
        heartbeat_seconds: float = 15.0,
    ) -> None:
        self.studio = studio
        self.store = store
        self.job_id = plan.job_id
        self.hosted_job_id = hosted_job_id
        self.worker_id = f"plural-cli:{plan.job_id}"
        self.errors: list[str] = []
        self._agents = {
            binding.agent_id: agents[binding.content_hash]
            for binding in spec.agents
            if binding.content_hash in agents
        }
        self._local = {trial.trial_id: trial for trial in plan.trials}
        self._heartbeat_seconds = heartbeat_seconds
        self._queue: queue.Queue[ProgressEvent | None] = queue.Queue()
        self._hosted: dict[tuple[str, str, int], str] | None = None
        self._executions: dict[tuple[str, int], str] = {}
        self._active: set[str] = set()
        self._last_beat = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="plural-tracker", daemon=True)
        self._thread.start()

    def observe(self, event: ProgressEvent) -> None:
        """Queue one local progress event for reporting."""
        self._queue.put(event)

    def close(self, *, cancelled: bool = False) -> list[str]:
        """Report everything queued, then stop.

        ``cancelled`` also cancels the hosted Job, for a local run that was
        interrupted before every Trial finished.

        Returns:
            The reporting errors, if any.
        """
        self._queue.put(None)
        self._thread.join()
        if cancelled:
            try:
                self.studio.jobs.cancel(self.hosted_job_id)
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)
        return list(self.errors)

    def _run(self) -> None:
        while True:
            try:
                event = self._queue.get(timeout=self._heartbeat_seconds)
            except queue.Empty:
                self._beat()
                continue
            if event is None:
                return
            try:
                self._handle(event)
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)
            if time.monotonic() - self._last_beat >= self._heartbeat_seconds:
                self._beat()

    def _target(self, trial_id: str) -> str | None:
        trial = self._local.get(trial_id)
        if trial is None:
            return None
        if self._hosted is None:
            self._hosted = _hosted_trials(self.studio, self.hosted_job_id)
        pin = self._agents.get(trial.agent_id)
        name = pin[0] if pin is not None else trial.agent_name
        return self._hosted.get((trial.task_pin.name, name, trial.attempt))

    def _handle(self, event: ProgressEvent) -> None:
        if event.trial_id is None or event.execution_id is None:
            return
        target = self._target(event.trial_id)
        if target is None:
            raise PublishError(f"No hosted Trial for local Trial {event.trial_id}")
        local = (event.trial_id, event.execution_id)
        if event.type == "provisioning":
            record = self.studio.trials.create_execution(
                target,
                idempotency_key=execution_key(self.job_id, *local),
                worker_id=self.worker_id,
            )
            execution_id = str(record["id"])
            self._executions[local] = execution_id
            _advance(
                self.studio,
                execution_id,
                str(record.get("status") or "queued"),
                self.worker_id,
                "provisioning",
            )
            self._active.add(execution_id)
        elif event.type == "environment_ready" and local in self._executions:
            _advance(
                self.studio, self._executions[local], "provisioning", self.worker_id, "running"
            )
        elif event.type in _FINISHED:
            root = (
                self.store.trial_path(event.trial_id, self.job_id)
                / "executions"
                / str(event.execution_id)
            )
            if not (root / "result.json").exists():
                return
            pin = self._agents.get(self._local[event.trial_id].agent_id)
            published = publish_execution(
                self.studio,
                target,
                root,
                worker_id=self.worker_id,
                agent_definition=pin[1] if pin is not None else None,
            )
            self._active.discard(published.execution_id)

    def _beat(self) -> None:
        self._last_beat = time.monotonic()
        if not self._active:
            return
        try:
            self.studio.request(
                "POST",
                "/workers/heartbeat",
                json={
                    "worker_id": self.worker_id,
                    "status": "active",
                    "capabilities": {"client": "plural-cli", "plural_version": __version__},
                    "execution_ids": sorted(self._active),
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        message = str(exc) or type(exc).__name__
        if message not in self.errors and len(self.errors) < 20:
            self.errors.append(message)


__all__ = [
    "AgentPin",
    "HostedTracker",
    "PublishError",
    "Published",
    "agent_pins",
    "execution_key",
    "publish_execution",
    "publish_job",
]
