"""Versioned datasets of traces for benchmarks and training.

Examples:
    >>> from plural.environments.dataset import Dataset
    >>> from plural.tracing.schema import Trace
    >>> ds = Dataset.from_traces("demo", [Trace(trace_id="a"), Trace(trace_id="b")])
    >>> len(ds)
    2
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from plural.environments.task import TaskData
from plural.tracing.schema import Trace
from plural.tracing.sinks import JSONLSink, SQLiteSink, traces_from_jsonl

MANIFEST_SCHEMA_VERSION = "1.0.0"
HASH_ALGORITHM = "sha256"
HASH_VERSION = "2"
TASK_MANIFEST_SCHEMA_VERSION = "1.0.0"
TASK_HASH_VERSION = "1"


class TraceFilter(BaseModel):
    """Declarative filters for selecting traces from a sink."""

    trace_kind: Literal["production", "episode", "llm_call"] | None = None
    environment: str | None = None
    environment_fingerprint: str | None = None
    model: str | None = None
    terminated: bool | None = None
    truncated: bool | None = None

    def matches(self, trace: Trace) -> bool:
        """Return whether all configured fields match a trace.

        Args:
            trace: Candidate trace.

        Returns:
            ``True`` when every non-null filter field matches.
        """
        for field_name in type(self).model_fields:
            expected = getattr(self, field_name)
            if expected is not None and getattr(trace, field_name) != expected:
                return False
        return True


class Dataset(BaseModel):
    """A named, content-hashed collection of traces.

    Attributes:
        name: Dataset name.
        version: Human version label.
        traces: Contained traces.
        content_hash: Snapshot hash captured at construction or save time.
            Mutating traces does not update it; compare :attr:`current_content_hash`
            or save again to verify and refresh the snapshot.
        metadata: Arbitrary metadata.
    """

    name: str
    version: str = "0.1.0"
    traces: list[Trace] = Field(default_factory=list)
    content_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_content_hash(self) -> Dataset:
        """Compute the content hash and reject untrusted supplied values.

        Returns:
            The validated dataset.
        """
        computed_hash = self.compute_hash()
        if self.content_hash and self.content_hash != computed_hash:
            raise ValueError(
                "dataset content hash mismatch: "
                f"expected {self.content_hash}, computed {computed_hash}"
            )
        self.content_hash = computed_hash
        return self

    def __len__(self) -> int:
        """Return the number of traces."""
        return len(self.traces)

    def compute_hash(self) -> str:
        """Compute a stable content hash.

        Returns:
            Hex SHA256 digest.
        """
        payload = [
            trace.model_dump(mode="json")
            for trace in sorted(
                self.traces,
                key=lambda item: (
                    item.trace_id,
                    json.dumps(
                        item.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
        ]
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def current_content_hash(self) -> str:
        """Compute the hash of current content without changing snapshot identity."""
        return self.compute_hash()

    @classmethod
    def from_traces(
        cls,
        name: str,
        traces: Iterable[Trace],
        *,
        version: str = "0.1.0",
        metadata: dict[str, Any] | None = None,
    ) -> Dataset:
        """Build a dataset from an iterable of traces.

        Args:
            name: Dataset name.
            traces: Traces to include.
            version: Version label.
            metadata: Optional metadata.

        Returns:
            A new :class:`Dataset`.
        """
        items = list(traces)
        fingerprints = sorted(
            {t.environment_fingerprint for t in items if t.environment_fingerprint}
        )
        meta = dict(metadata or {})
        if fingerprints:
            meta.setdefault("environment_fingerprints", fingerprints)
        return cls(
            name=name,
            version=version,
            traces=items,
            metadata=meta,
        )

    @classmethod
    def from_sink(
        cls,
        sink: JSONLSink | SQLiteSink | Path | str,
        name: str,
        *,
        where: Callable[[Trace], bool] | None = None,
        filter: TraceFilter | None = None,
        version: str = "0.1.0",
    ) -> Dataset:
        """Build a dataset from a sink or JSONL path.

        Args:
            sink: A :class:`JSONLSink`, :class:`SQLiteSink`, or filesystem path.
            name: Dataset name.
            where: Optional predicate filter.
            filter: Optional declarative trace filter.
            version: Version label.

        Returns:
            A filtered :class:`Dataset`.
        """
        if isinstance(sink, (str, Path)):
            traces = traces_from_jsonl(sink)
        elif isinstance(sink, JSONLSink):
            traces = sink.read_all()
        elif isinstance(sink, SQLiteSink):
            traces = sink.query(limit=100_000)
        else:  # pragma: no cover
            raise TypeError(f"unsupported sink type: {type(sink)}")
        if where is not None:
            traces = [t for t in traces if where(t)]
        if filter is not None:
            traces = [t for t in traces if filter.matches(t)]
        return cls.from_traces(name, traces, version=version)

    def save(self, path: str | Path) -> None:
        """Save the dataset as JSONL plus a sidecar manifest.

        Args:
            path: Destination JSONL path.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.content_hash = self.compute_hash()
        with path.open("w", encoding="utf-8") as fh:
            for trace in self.traces:
                fh.write(trace.model_dump_json() + "\n")
        manifest = {
            "name": self.name,
            "version": self.version,
            "content_hash": self.content_hash,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "hash_algorithm": HASH_ALGORITHM,
            "hash_version": HASH_VERSION,
            "count": len(self.traces),
            "metadata": self.metadata,
        }
        path.with_suffix(path.suffix + ".manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path, name: str | None = None) -> Dataset:
        """Load a dataset from JSONL.

        Args:
            path: JSONL path.
            name: Optional override name.

        Returns:
            Loaded dataset.
        """
        path = Path(path)
        traces = traces_from_jsonl(path)
        manifest_path = path.with_suffix(path.suffix + ".manifest.json")
        version = "0.1.0"
        metadata: dict[str, Any] = {}
        recorded_hash: str | None = None
        hash_algorithm: str | None = None
        hash_version: str | None = None
        ds_name = name or path.stem
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            ds_name = name or manifest.get("name") or ds_name
            version = manifest.get("version") or version
            metadata = manifest.get("metadata") or {}
            recorded_hash = manifest.get("content_hash")
            hash_algorithm = manifest.get("hash_algorithm")
            hash_version = manifest.get("hash_version")
        dataset = cls.from_traces(ds_name, traces, version=version, metadata=metadata)
        if recorded_hash:
            if hash_algorithm is None and hash_version is None:
                actual_hash = _legacy_content_hash(traces)
            elif hash_algorithm == HASH_ALGORITHM and hash_version == HASH_VERSION:
                actual_hash = dataset.compute_hash()
            else:
                raise ValueError(
                    f"unsupported dataset hash algorithm/version: "
                    f"{hash_algorithm!r}/{hash_version!r}"
                )
            if actual_hash != recorded_hash:
                raise ValueError(
                    f"dataset content hash mismatch: expected {recorded_hash}, "
                    f"computed {actual_hash}"
                )
            dataset.content_hash = recorded_hash
        return dataset


class TaskDataset(BaseModel):
    """A named, content-hashed collection of benchmark tasks.

    The full :class:`~plural.environments.task.TaskData` payload participates
    in the content hash, including ``expected`` and ``metadata``. The
    ``expected`` field is evaluator-only data and may contain sensitive labels;
    callers should not expose it to policies or include it in episode traces.

    Attributes:
        name: Dataset name.
        version: Human version label.
        tasks: Tasks in deterministic benchmark input order.
        content_hash: Snapshot hash captured at construction or save time.
            Mutating tasks does not update it; compare :attr:`current_content_hash`
            or save again to verify and refresh the snapshot.
        metadata: Arbitrary dataset metadata.
    """

    name: str = Field(min_length=1)
    version: str = Field(default="0.1.0", min_length=1)
    tasks: list[TaskData] = Field(default_factory=list)
    content_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_content(self) -> TaskDataset:
        _validate_unique_task_ids(self.tasks)
        computed_hash = self.compute_hash()
        if self.content_hash and self.content_hash != computed_hash:
            raise ValueError(
                "task dataset content hash mismatch: "
                f"expected {self.content_hash}, computed {computed_hash}"
            )
        self.content_hash = computed_hash
        return self

    def __len__(self) -> int:
        """Return the number of tasks."""
        return len(self.tasks)

    def compute_hash(self) -> str:
        """Compute a stable hash over complete canonical task payloads.

        Returns:
            Hex SHA256 digest.
        """
        return task_content_hash(self.tasks)

    @property
    def current_content_hash(self) -> str:
        """Compute the hash of current content without changing snapshot identity."""
        return self.compute_hash()

    def save(self, path: str | Path) -> None:
        """Save tasks as JSONL with a versioned sidecar manifest.

        The JSONL contains complete task records, including evaluator-only
        ``expected`` values, which may be sensitive.

        Args:
            path: Destination JSONL path.
        """
        _validate_unique_task_ids(self.tasks)
        self.content_hash = self.compute_hash()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for task in self.tasks:
                fh.write(task.model_dump_json() + "\n")
        manifest = {
            "dataset_kind": "task",
            "name": self.name,
            "version": self.version,
            "content_hash": self.content_hash,
            "schema_version": TASK_MANIFEST_SCHEMA_VERSION,
            "hash_algorithm": HASH_ALGORITHM,
            "hash_version": TASK_HASH_VERSION,
            "count": len(self.tasks),
            "metadata": self.metadata,
        }
        path.with_suffix(path.suffix + ".manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> TaskDataset:
        """Load tasks and verify their versioned manifest content hash.

        Args:
            path: Source JSONL path.

        Returns:
            Verified task dataset.

        Raises:
            FileNotFoundError: If the sidecar manifest is missing.
            ValueError: If the manifest is unsupported or integrity checks fail.
        """
        path = Path(path)
        manifest_path = path.with_suffix(path.suffix + ".manifest.json")
        if not manifest_path.exists():
            raise FileNotFoundError(f"task dataset manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dataset_kind") != "task":
            raise ValueError("manifest is not for a task dataset")
        if manifest.get("schema_version") != TASK_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                "unsupported task dataset manifest schema version: "
                f"{manifest.get('schema_version')!r}"
            )
        if (
            manifest.get("hash_algorithm") != HASH_ALGORITHM
            or manifest.get("hash_version") != TASK_HASH_VERSION
        ):
            raise ValueError(
                "unsupported task dataset hash algorithm/version: "
                f"{manifest.get('hash_algorithm')!r}/{manifest.get('hash_version')!r}"
            )

        tasks = [
            TaskData.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if manifest.get("count") != len(tasks):
            raise ValueError(
                f"task dataset count mismatch: expected {manifest.get('count')}, "
                f"loaded {len(tasks)}"
            )
        recorded_hash = manifest.get("content_hash")
        if not isinstance(recorded_hash, str) or not recorded_hash:
            raise ValueError("task dataset manifest is missing content_hash")
        dataset = cls(
            name=manifest.get("name"),
            version=manifest.get("version"),
            tasks=tasks,
            metadata=manifest.get("metadata") or {},
        )
        actual_hash = dataset.compute_hash()
        if actual_hash != recorded_hash:
            raise ValueError(
                f"task dataset content hash mismatch: expected {recorded_hash}, "
                f"computed {actual_hash}"
            )
        dataset.content_hash = recorded_hash
        return dataset


TraceDataset = Dataset


def _validate_unique_task_ids(tasks: Iterable[TaskData]) -> None:
    """Validate task identity independently of snapshot hash validation."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for task in tasks:
        if task.task_id in seen:
            duplicates.add(task.task_id)
        seen.add(task.task_id)
    if duplicates:
        values = ", ".join(repr(task_id) for task_id in sorted(duplicates))
        raise ValueError(f"task_id values must be unique; duplicates: {values}")


def task_content_hash(tasks: Iterable[TaskData]) -> str:
    """Compute the order-sensitive canonical hash for benchmark task inputs.

    Args:
        tasks: Tasks in benchmark input order.

    Returns:
        Hex SHA256 digest.
    """
    payload = [task.model_dump(mode="json") for task in tasks]
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _legacy_content_hash(traces: Iterable[Trace]) -> str:
    """Compute the pre-v2 manifest hash for backward compatibility.

    Args:
        traces: Traces loaded from a legacy dataset.

    Returns:
        The legacy SHA256 content hash.
    """
    digest = hashlib.sha256()
    for trace in sorted(traces, key=lambda item: item.trace_id):
        payload = {
            "trace_id": trace.trace_id,
            "outcome": trace.outcome.model_dump() if trace.outcome else None,
            "task_id": trace.task_id,
            "environment": trace.environment,
        }
        digest.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()
