"""Atomic local job store under ``.plural/jobs``."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from plural.domain import (
    ErrorCode,
    JobLock,
    JobPlan,
    JobResult,
    JobSpec,
    ProgressEvent,
    TrialResult,
    TrialSpec,
    canonical_json,
)
from plural.sandbox import DownloadedFile, safe_relative_path


class JobStore:
    """Crash-safe filesystem persistence for local execution."""

    def __init__(self, root: Path = Path(".plural/jobs")) -> None:
        self.root = root

    def job_path(self, job_id: str) -> Path:
        """Return a validated job directory."""
        if not job_id or any(item in job_id for item in ("/", "\\", "..", "\x00")):
            raise ValueError("invalid job id")
        return self.root / job_id

    def initialize(self, spec: JobSpec, plan: JobPlan) -> Path:
        """Create or validate a locked job directory."""
        destination = self.job_path(plan.job_id)
        destination.mkdir(parents=True, exist_ok=True)
        lock_path = destination / "lock.json"
        if lock_path.exists():
            existing = JobLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
            if existing != plan.lock:
                raise ValueError(ErrorCode.LOCK_INCOMPATIBLE.value)
        else:
            self._write_model(lock_path, plan.lock)
        config_path = destination / "config.json"
        if config_path.exists():
            existing_spec = JobSpec.model_validate_json(config_path.read_text(encoding="utf-8"))
            if existing_spec != spec:
                raise ValueError(ErrorCode.LOCK_INCOMPATIBLE.value)
        else:
            self._write_model(config_path, spec)
        return destination

    def load_spec(self, job_id: str) -> JobSpec:
        """Load a persisted job config."""
        return JobSpec.model_validate_json(
            (self.job_path(job_id) / "config.json").read_text(encoding="utf-8")
        )

    def load_lock(self, job_id: str) -> JobLock:
        """Load a persisted reproducibility lock."""
        return JobLock.model_validate_json(
            (self.job_path(job_id) / "lock.json").read_text(encoding="utf-8")
        )

    def list_jobs(self) -> tuple[dict[str, Any], ...]:
        """List stored jobs without accepting partial files as results."""
        if not self.root.exists():
            return ()
        output = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if not path.is_dir() or not (path / "lock.json").exists():
                continue
            result_path = path / "result.json"
            output.append(
                {
                    "job_id": path.name,
                    "status": (
                        JobResult.model_validate_json(
                            result_path.read_text(encoding="utf-8")
                        ).status
                        if result_path.exists()
                        else "pending"
                    ),
                    "cancel_requested": (path / "cancel").exists(),
                }
            )
        return tuple(output)

    def emit(
        self,
        job_id: str,
        event_type: str,
        status: str,
        *,
        trial_id: str | None = None,
        execution_id: int | None = None,
        message: str = "",
        data: Mapping[str, Any] | None = None,
        secret_values: Iterable[str] = (),
    ) -> ProgressEvent:
        """Append one monotonic, sanitized progress event."""
        path = self.job_path(job_id) / "events.jsonl"
        sequence = 1
        if path.exists():
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
            if lines:
                sequence = int(json.loads(lines[-1])["sequence"]) + 1
        sanitized = _sanitize_event_data(dict(data or {}), secret_values)
        event = ProgressEvent.model_validate(
            {
                "sequence": sequence,
                "timestamp": datetime.now(timezone.utc),
                "job_id": job_id,
                "type": event_type,
                "status": status,
                "trial_id": trial_id,
                "execution_id": execution_id,
                "message": redact_mapping({"value": message}, secret_values)["value"][:2000],
                "data": sanitized,
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (canonical_json(event) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return event

    def events(
        self,
        job_id: str,
        *,
        after: int = 0,
        follow: bool = False,
        poll_interval: float = 0.1,
    ) -> Iterable[ProgressEvent]:
        """Yield events after a sequence cursor, optionally following updates."""
        path = self.job_path(job_id) / "events.jsonl"
        cursor = after
        while True:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line:
                        continue
                    event = ProgressEvent.model_validate_json(line)
                    if event.sequence > cursor:
                        cursor = event.sequence
                        yield event
            if not follow or (self.job_path(job_id) / "result.json").exists():
                return
            time.sleep(poll_interval)

    def request_cancel(self, job_id: str) -> None:
        """Atomically create a cancellation marker."""
        path = self.job_path(job_id) / "cancel"
        self._write_bytes(path, b"cancelled\n")

    def clear_cancel(self, job_id: str) -> None:
        """Clear a prior cancellation marker before explicit resume."""
        (self.job_path(job_id) / "cancel").unlink(missing_ok=True)

    def cancel_requested(self, job_id: str) -> bool:
        """Return whether cancellation was requested."""
        return (self.job_path(job_id) / "cancel").exists()

    def trial_path(self, trial: TrialSpec | str, job_id: str | None = None) -> Path:
        """Return a validated trial directory."""
        trial_id = trial.trial_id if isinstance(trial, TrialSpec) else trial
        owner = trial.job_id if isinstance(trial, TrialSpec) else job_id
        if owner is None:
            raise ValueError("job_id is required")
        if not trial_id or any(item in trial_id for item in ("/", "\\", "..", "\x00")):
            raise ValueError("invalid trial id")
        return self.job_path(owner) / "trials" / trial_id

    def successful_result(self, trial: TrialSpec) -> TrialResult | None:
        """Return a successful persisted trial result, if present."""
        root = self.trial_path(trial)
        selected_path = root / "selected.json"
        if not selected_path.exists():
            return None
        selected = json.loads(selected_path.read_text(encoding="utf-8"))
        if not isinstance(selected, dict) or not isinstance(selected.get("execution_id"), int):
            raise ValueError("invalid selected execution pointer")
        path = root / "attempts" / str(selected["execution_id"]) / "result.json"
        result = TrialResult.model_validate_json(path.read_text(encoding="utf-8"))
        receipt_path = path.with_name("receipt.json")
        persisted_receipt = type(result.receipt).model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        if persisted_receipt != result.receipt:
            raise ValueError("selected execution receipt/result mismatch")
        self._validate_result_ownership(trial, result)
        if result.status != "succeeded":
            raise ValueError("selected execution is not successful")
        if selected.get("receipt_hash") != result.receipt.receipt_hash:
            raise ValueError("selected execution receipt hash mismatch")
        return result

    def next_execution_id(self, trial: TrialSpec) -> int:
        """Return the next monotonic execution ID for a trial."""
        root = self.trial_path(trial) / "attempts"
        if not root.exists():
            return 0
        identifiers = [
            int(path.name) for path in root.iterdir() if path.is_dir() and path.name.isdigit()
        ]
        return max(identifiers, default=-1) + 1

    def trial_results(self, job_id: str) -> tuple[TrialResult, ...]:
        """Load all complete trial results in lexical order."""
        root = self.job_path(job_id) / "trials"
        if not root.exists():
            return ()
        output = []
        for path in sorted(root.glob("*/result.json")):
            output.append(TrialResult.model_validate_json(path.read_text(encoding="utf-8")))
        return tuple(output)

    def write_trial_attempt(
        self,
        trial: TrialSpec,
        execution_id: int,
        result: TrialResult,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        artifacts: Iterable[DownloadedFile] = (),
        verifier_stdout: bytes = b"",
        verifier_stderr: bytes = b"",
    ) -> Path:
        """Append one immutable execution and update the selected result."""
        self._validate_result_ownership(trial, result)
        attempt = self.trial_path(trial) / "attempts" / str(execution_id)
        attempt.mkdir(parents=True, exist_ok=False)
        logs = attempt / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._write_bytes(logs / "stdout.log", stdout)
        self._write_bytes(logs / "stderr.log", stderr)
        self._write_bytes(logs / "verifier.stdout.log", verifier_stdout)
        self._write_bytes(logs / "verifier.stderr.log", verifier_stderr)
        artifact_root = attempt / "artifacts"
        for artifact in artifacts:
            relative = safe_relative_path(artifact.path)
            destination = artifact_root / relative
            self._write_bytes(destination, artifact.data)
        self._write_model(attempt / "receipt.json", result.receipt)
        self._write_model(attempt / "result.json", result)
        trial_root = self.trial_path(trial)
        if result.status == "succeeded":
            self._write_bytes(
                trial_root / "selected.json",
                (
                    canonical_json(
                        {
                            "execution_id": execution_id,
                            "receipt_hash": result.receipt.receipt_hash,
                        }
                    )
                    + "\n"
                ).encode(),
            )
        if result.status == "succeeded" or not (trial_root / "selected.json").exists():
            self._write_model(trial_root / "result.json", result)
        return attempt

    def write_job_result(self, result: JobResult) -> Path:
        """Atomically publish the aggregate result."""
        path = self.job_path(result.job_id) / "result.json"
        self._write_model(path, result)
        return path

    def write_review(
        self,
        trial: TrialSpec,
        verifier_name: str,
        submission: Mapping[str, Any],
        result: TrialResult,
    ) -> Path:
        """Append one immutable human review and publish its resolved Trial result."""
        if not verifier_name or any(item in verifier_name for item in ("/", "\\", "..", "\x00")):
            raise ValueError("invalid verifier name")
        self._validate_result_ownership(trial, result)
        destination = self.trial_path(trial) / "reviews" / verifier_name
        if destination.exists():
            raise ValueError("review was already submitted")
        destination.mkdir(parents=True, exist_ok=False)
        self._write_bytes(
            destination / "submission.json",
            (canonical_json(dict(submission)) + "\n").encode(),
        )
        self._write_model(destination / "result.json", result)
        self._write_model(self.trial_path(trial) / "result.json", result)
        return destination

    def read_job_result(self, job_id: str) -> JobResult | None:
        """Load the aggregate result when complete."""
        path = self.job_path(job_id) / "result.json"
        return (
            JobResult.model_validate_json(path.read_text(encoding="utf-8"))
            if path.exists()
            else None
        )

    def write_sync_state(self, job_id: str, state: Mapping[str, Any]) -> Path:
        """Persist replay-safe hosted upload metadata without credentials."""
        path = self.job_path(job_id) / "sync.json"
        self._write_bytes(path, (canonical_json(dict(state)) + "\n").encode("utf-8"))
        return path

    def read_sync_state(self, job_id: str) -> dict[str, Any] | None:
        """Read hosted upload metadata when a prior sync was registered."""
        path = self.job_path(job_id) / "sync.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return dict(raw) if isinstance(raw, dict) else None

    def _validate_result_ownership(self, trial: TrialSpec, result: TrialResult) -> None:
        receipt = result.receipt
        lock = self.load_lock(trial.job_id)
        if (
            receipt.job_id != trial.job_id
            or receipt.trial_id != trial.trial_id
            or receipt.attempt != trial.attempt
            or receipt.environment_digest != trial.environment.digest
            or receipt.harness_digest != (trial.harness.digest if trial.harness is not None else "")
            or lock.job_id != trial.job_id
            or receipt.task_digest != trial.task_digest
            or receipt.task_digest not in lock.task_digests
            or receipt.environment_digest not in lock.environment_digests
            or receipt.agent_digest not in lock.agent_digests
            or (bool(receipt.harness_digest) and receipt.harness_digest not in lock.harness_digests)
        ):
            raise ValueError("trial result does not belong to its locked job")

    def _write_model(self, path: Path, model: BaseModel) -> None:
        self._write_bytes(path, (canonical_json(model) + "\n").encode())

    def _write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def redact_mapping(values: Mapping[str, Any], secret_values: Iterable[str]) -> dict[str, Any]:
    """Recursively redact exact secret values before persistence."""
    secrets = {item for item in secret_values if item}

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            output = value
            for secret in secrets:
                output = output.replace(secret, "***")
            return output
        if isinstance(value, dict):
            return {str(key): redact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [redact(item) for item in value]
        return value

    return {str(key): redact(value) for key, value in values.items()}


_PRIVATE_EVENT_KEYS = frozenset(
    {
        "expected",
        "hidden_state",
        "private_reasoning",
        "reasoning",
        "secret",
        "secrets",
        "state",
        "verifier_input",
    }
)


def _sanitize_event_data(
    values: Mapping[str, Any],
    secret_values: Iterable[str],
) -> dict[str, Any]:
    redacted = redact_mapping(values, secret_values)

    def sanitize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): "[redacted]"
                if str(key).lower() in _PRIVATE_EVENT_KEYS
                else sanitize(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [sanitize(item) for item in value[:100]]
        if isinstance(value, str):
            return value[:20_000]
        return value

    sanitized = sanitize(redacted)
    return sanitized if isinstance(sanitized, dict) else {}


__all__ = ["JobStore", "redact_mapping"]
