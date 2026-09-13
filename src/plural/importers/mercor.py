"""Read-only adapter for Mercor trial directories."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from plural.common import FrozenModel, content_hash, stable_id
from plural.jobs import (
    ArtifactManifest,
    ArtifactManifestEntry,
    BenchmarkPin,
    JobMode,
    ModelResolution,
    TrialReceipt,
    TrialResult,
)
from plural.tasks import TaskPin
from plural.trajectory import Trajectory, normalize_trajectory


class MercorArtifactTransfer(FrozenModel):
    """One artifact transfer row retained from a Mercor manifest."""

    source: str
    destination: str
    type: str = ""
    status: str = ""


class MercorTrialImport(FrozenModel):
    """Typed, normalized view of one Mercor trial directory."""

    source: str
    provenance: Literal["imported_unverified"] = "imported_unverified"
    config: dict[str, Any] = Field(default_factory=dict)
    trajectory: Trajectory
    tito_transitions: Any = None
    verifier: dict[str, Any] = Field(default_factory=dict)
    reward: float | None = None
    logs: tuple[str, ...] = ()
    artifacts: ArtifactManifest = Field(default_factory=ArtifactManifest)
    artifact_manifest: Any = None
    artifact_transfers: tuple[MercorArtifactTransfer, ...] = ()

    def write_plural_bundle(self, destination: Path) -> Path:
        """Write a Plural-compatible imported Trial bundle.

        Returns:
            The created Trial bundle directory.
        """
        destination.mkdir(parents=True, exist_ok=True)
        execution = destination / "executions" / "0"
        if execution.exists():
            raise FileExistsError(execution)
        (execution / "logs").mkdir(parents=True)
        artifact_root = execution / "artifacts"
        artifact_root.mkdir()
        source_root = Path(self.source)
        for log in self.logs:
            relative = _relative(log)
            _write_bytes(
                execution / "logs" / _log_destination(relative),
                (source_root / relative).read_bytes(),
            )

        payloads: dict[str, bytes] = {
            "trajectory.json": (
                json.dumps(self.trajectory.model_dump(mode="json"), sort_keys=True) + "\n"
            ).encode()
        }
        if self.tito_transitions is not None:
            payloads["tito_transitions.json"] = (
                json.dumps(self.tito_transitions, sort_keys=True) + "\n"
            ).encode()
        if self.verifier:
            payloads["verifier-reward.json"] = (
                json.dumps(self.verifier, sort_keys=True) + "\n"
            ).encode()
        for entry in self.artifacts.artifacts:
            try:
                relative = _relative(entry.path)
            except ValueError:
                continue
            source_path = source_root / "artifacts" / relative
            if not source_path.exists():
                source_path = source_root / relative
            if source_path.is_file() and relative.as_posix() not in payloads:
                payloads[relative.as_posix()] = source_path.read_bytes()
        for transfer in self.artifact_transfers:
            if transfer.status.lower() not in {"success", "succeeded", "completed"}:
                continue
            try:
                local = source_root / _relative(transfer.destination)
            except ValueError:
                continue
            if local.is_file():
                name = _artifact_destination(transfer.destination, local.name)
                payloads.setdefault(name, local.read_bytes())
            elif local.is_dir():
                for source_path in sorted(local.rglob("*")):
                    if not source_path.is_file() or source_path.name == "manifest.json":
                        continue
                    nested_relative = source_path.relative_to(local).as_posix()
                    artifact_name = _artifact_destination(transfer.destination, nested_relative)
                    payloads.setdefault(artifact_name, source_path.read_bytes())
        entries = tuple(_entry(name, data) for name, data in sorted(payloads.items()))
        for output_name, data in payloads.items():
            _write_bytes(artifact_root / output_name, data)
        _write_model(artifact_root / "manifest.json", ArtifactManifest(artifacts=entries))

        task_pin = _task_pin(self.config)
        benchmark = _benchmark_pin(self.config)
        model = _model_resolution(self.config)
        job_id = str(self.config.get("job_id") or stable_id("job", self.config))
        trial_id = str(
            self.config.get("trial_id")
            or stable_id("trl", {"source": self.source, "config": self.config})
        )
        receipt = TrialReceipt(
            trial_id=trial_id,
            job_id=job_id,
            execution_id=0,
            task_digest=task_pin.content_hash,
            task_pin=task_pin,
            benchmark=benchmark,
            model=model,
            environment_digest=content_hash(self.config.get("environment") or {"source": "mercor"}),
            verifier_digests=(),
            agent_digest=content_hash(
                self.config.get("agent") or {"model": model.catalog_model_id}
            ),
            mode=JobMode.EVAL,
            runtime_provider="imported",
            artifact_hashes={entry.path: entry.sha256 for entry in entries},
            trust="imported_unverified",
        )
        result = TrialResult(status="succeeded", receipt=receipt, reward=self.reward)
        _write_model(execution / "receipt.json", receipt)
        _write_model(execution / "result.json", result)
        _write_model(destination / "result.json", result)
        _write_bytes(
            destination / "selected.json",
            (
                json.dumps(
                    {"execution_id": 0, "receipt_hash": receipt.receipt_hash},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode(),
        )
        _write_bytes(
            destination / "import.json",
            (
                json.dumps(
                    {
                        "source": self.source,
                        "provenance": self.provenance,
                        "config": self.config,
                        "artifact_manifest": self.artifact_manifest,
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode(),
        )
        return destination


def import_mercor_trial(
    source: Path,
    *,
    destination: Path | None = None,
) -> MercorTrialImport:
    """Normalize a Mercor trial directory without mutating it.

    Returns:
        Typed imported data, optionally also written as a Plural Trial bundle.
    """
    root = source.expanduser().resolve()
    config = _read_json(root / "config.json", required=True)
    if not isinstance(config, dict):
        raise ValueError("Mercor config.json must contain an object")
    trajectory_path = root / "agent" / "trajectory.json"
    trajectory = normalize_trajectory(_read_json(trajectory_path, required=True))
    transitions = _read_json(root / "agent" / "tito_transitions.json")
    if transitions is None:
        transitions = _read_json(root / "tito_transitions.json")
    verifier_raw = _read_json(root / "verifier" / "reward.json")
    verifier = verifier_raw if isinstance(verifier_raw, dict) else {}
    reward_value = verifier.get("reward") if isinstance(verifier, dict) else None
    reward = float(reward_value) if isinstance(reward_value, (int, float)) else None
    logs = _discover_logs(root)
    manifest, raw_manifest, transfers = _read_manifest(root)
    imported = MercorTrialImport(
        source=str(root),
        config=_without_modal(config),
        trajectory=trajectory,
        tito_transitions=transitions,
        verifier=verifier,
        reward=reward,
        logs=logs,
        artifacts=manifest,
        artifact_manifest=raw_manifest,
        artifact_transfers=transfers,
    )
    if destination is not None:
        imported.write_plural_bundle(destination)
    return imported


def _read_json(path: Path, *, required: bool = False) -> Any:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_manifest(
    root: Path,
) -> tuple[ArtifactManifest, Any, tuple[MercorArtifactTransfer, ...]]:
    for path in (
        root / "artifacts" / "manifest.json",
        root / "artifact_manifest.json",
        root / "manifest.json",
    ):
        raw = _read_json(path)
        if raw is None:
            continue
        rows = raw.get("artifacts", raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            continue
        entries = []
        transfers = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("source") is not None and row.get("destination") is not None:
                transfers.append(
                    MercorArtifactTransfer(
                        source=str(row["source"]),
                        destination=str(row["destination"]),
                        type=str(row.get("type") or ""),
                        status=str(row.get("status") or ""),
                    )
                )
            relative = str(row.get("path") or row.get("name") or "")
            digest = str(row.get("sha256") or row.get("digest") or "")
            if digest and not digest.startswith("sha256:"):
                digest = f"sha256:{digest}"
            if not relative or len(digest) != 71:
                continue
            entries.append(
                ArtifactManifestEntry(
                    path=relative,
                    sha256=digest,
                    media_type=str(row.get("media_type") or "application/octet-stream"),
                    size=int(row.get("size") or row.get("size_bytes") or 0),
                    role=str(row["role"]) if row.get("role") else None,
                )
            )
        return ArtifactManifest(artifacts=tuple(entries)), raw, tuple(transfers)
    return ArtifactManifest(), None, ()


def _without_modal(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _without_modal(item)
            for key, item in value.items()
            if "modal" not in str(key).lower()
        }
    if isinstance(value, list):
        return [_without_modal(item) for item in value]
    return value


def _discover_logs(root: Path) -> tuple[str, ...]:
    paths: set[Path] = set()
    trial_log = root / "trial.log"
    if trial_log.is_file():
        paths.add(trial_log)
    legacy = root / "logs"
    if legacy.is_dir():
        paths.update(path for path in legacy.rglob("*") if path.is_file())
    agent = root / "agent"
    if agent.is_dir():
        paths.update(path for path in agent.rglob("*.log") if path.is_file())
    verifier = root / "verifier"
    if verifier.is_dir():
        paths.update(
            path
            for path in verifier.rglob("*")
            if path.is_file() and path.suffix.lower() in {".log", ".txt"}
        )
    return tuple(path.relative_to(root).as_posix() for path in sorted(paths))


def _relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe imported path: {value!r}")
    return path


def _log_destination(path: Path) -> Path:
    if path.parts and path.parts[0] == "logs":
        path = Path(*path.parts[1:])
    return path


def _artifact_destination(destination: str, relative: str) -> str:
    base = _relative(destination)
    if base.parts and base.parts[0] == "artifacts":
        base = Path(*base.parts[1:])
    relative_path = _relative(relative)
    if not base.parts:
        return relative_path.as_posix()
    if base.suffix and base.name == relative_path.name:
        return base.as_posix()
    return (base / relative_path).as_posix()


def _task_pin(config: dict[str, Any]) -> TaskPin:
    task = _mapping(config.get("task"))
    task_path = Path(str(task.get("path") or ""))
    name = str(
        task.get("name")
        or task.get("id")
        or config.get("task_id")
        or (task_path.name if task_path.name else "mercor-task")
    )
    version = str(task.get("version") or "imported")
    digest = str(task.get("hash") or task.get("content_hash") or content_hash(task or name))
    return TaskPin(name=name, version=version, content_hash=digest)


def _benchmark_pin(config: dict[str, Any]) -> BenchmarkPin | None:
    benchmark = config.get("benchmark")
    if not isinstance(benchmark, dict):
        return None
    return BenchmarkPin(
        name=str(benchmark.get("name") or benchmark.get("id") or "mercor-benchmark"),
        version=str(benchmark.get("version") or "imported"),
        content_hash=str(
            benchmark.get("hash") or benchmark.get("content_hash") or content_hash(benchmark)
        ),
    )


def _model_resolution(config: dict[str, Any]) -> ModelResolution:
    agent = _mapping(config.get("agent"))
    model_id = str(
        agent.get("model") or agent.get("model_name") or config.get("model") or "mercor/unknown"
    )
    provider = str(agent.get("provider") or model_id.partition("/")[0] or "imported")
    upstream = str(agent.get("upstream_id") or model_id.partition("/")[2] or model_id)
    return ModelResolution(
        catalog_model_id=model_id,
        provider=provider,
        endpoint="imported:unverified",
        upstream_id=upstream,
    )


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _entry(path: str, data: bytes) -> ArtifactManifestEntry:
    media_type = (
        "application/x-ndjson"
        if Path(path).suffix == ".jsonl"
        else mimetypes.guess_type(path)[0] or "application/octet-stream"
    )
    role = (
        "trajectory"
        if "trajectory" in path
        else "verifier_evidence"
        if "verifier" in path
        else "training"
        if "tito" in path
        else None
    )
    return ArtifactManifestEntry(
        path=path,
        sha256=f"sha256:{hashlib.sha256(data).hexdigest()}",
        media_type=media_type,
        size=len(data),
        role=role,
    )


def _write_model(path: Path, model: FrozenModel) -> None:
    _write_bytes(path, (model.model_dump_json() + "\n").encode())


def _write_bytes(path: Path, data: bytes) -> None:
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


__all__ = ["MercorTrialImport", "import_mercor_trial"]
