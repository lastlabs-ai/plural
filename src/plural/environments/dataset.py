"""Content-addressed collections of canonical Traces."""

# ruff: noqa: D102

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from plural.tracing.schema import Trace
from plural.tracing.sinks import JSONLSink, SQLiteSink, traces_from_jsonl

MANIFEST_SCHEMA_VERSION = "2.0.0"
HASH_ALGORITHM = "sha256"
HASH_VERSION = "2"


class TraceFilter(BaseModel):
    """Declarative filters for selecting traces from a sink."""

    trace_kind: Literal["production", "episode", "llm_call"] | None = None
    environment: str | None = None
    environment_fingerprint: str | None = None
    model: str | None = None
    terminated: bool | None = None
    truncated: bool | None = None

    def matches(self, trace: Trace) -> bool:
        """Return whether every configured field matches."""
        for field_name in type(self).model_fields:
            expected = getattr(self, field_name)
            if expected is not None and getattr(trace, field_name) != expected:
                return False
        return True


class TraceDataset(BaseModel):
    """A named, immutable-identity collection of Traces."""

    name: str
    revision: str = "0.1.0"
    traces: list[Trace] = Field(default_factory=list)
    content_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_hash(self) -> TraceDataset:
        computed = self.compute_hash()
        if self.content_hash and self.content_hash != computed:
            raise ValueError(
                f"trace dataset content hash mismatch: expected {self.content_hash}, "
                f"computed {computed}"
            )
        self.content_hash = computed
        return self

    def __len__(self) -> int:
        return len(self.traces)

    def compute_hash(self) -> str:
        payload = [
            trace.model_dump(mode="json")
            for trace in sorted(self.traces, key=lambda item: item.trace_id)
        ]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @property
    def current_content_hash(self) -> str:
        return self.compute_hash()

    @classmethod
    def from_traces(
        cls,
        name: str,
        traces: Iterable[Trace],
        *,
        revision: str = "0.1.0",
        metadata: dict[str, Any] | None = None,
    ) -> TraceDataset:
        return cls(
            name=name,
            revision=revision,
            traces=list(traces),
            metadata=metadata or {},
        )

    @classmethod
    def from_sink(
        cls,
        sink: JSONLSink | SQLiteSink | Path | str,
        name: str,
        *,
        where: Callable[[Trace], bool] | None = None,
        filter: TraceFilter | None = None,
        revision: str = "0.1.0",
    ) -> TraceDataset:
        if isinstance(sink, (str, Path)):
            traces = traces_from_jsonl(sink)
        elif isinstance(sink, JSONLSink):
            traces = sink.read_all()
        elif isinstance(sink, SQLiteSink):
            traces = sink.query(limit=100_000)
        else:
            raise TypeError(f"unsupported sink type: {type(sink)}")
        selected = [
            trace
            for trace in traces
            if (where is None or where(trace)) and (filter is None or filter.matches(trace))
        ]
        return cls.from_traces(name, selected, revision=revision)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.content_hash = self.compute_hash()
        target.write_text(
            "".join(trace.model_dump_json() + "\n" for trace in self.traces),
            encoding="utf-8",
        )
        target.with_suffix(target.suffix + ".manifest.json").write_text(
            json.dumps(
                {
                    "name": self.name,
                    "revision": self.revision,
                    "content_hash": self.content_hash,
                    "schema_version": MANIFEST_SCHEMA_VERSION,
                    "hash_algorithm": HASH_ALGORITHM,
                    "hash_version": HASH_VERSION,
                    "count": len(self.traces),
                    "metadata": self.metadata,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> TraceDataset:
        target = Path(path)
        manifest_path = target.with_suffix(target.suffix + ".manifest.json")
        if not manifest_path.exists():
            raise ValueError("trace dataset manifest is required")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported trace dataset manifest schema")
        if (
            manifest.get("hash_algorithm") != HASH_ALGORITHM
            or manifest.get("hash_version") != HASH_VERSION
        ):
            raise ValueError("unsupported trace dataset hash algorithm/version")
        dataset = cls(
            name=str(manifest["name"]),
            revision=str(manifest["revision"]),
            traces=traces_from_jsonl(target),
            content_hash=str(manifest["content_hash"]),
            metadata=manifest.get("metadata") or {},
        )
        if len(dataset) != int(manifest["count"]):
            raise ValueError("trace dataset record count mismatch")
        return dataset


__all__ = ["TraceDataset", "TraceFilter"]
