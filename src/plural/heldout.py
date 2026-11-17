"""Held-out Tasks: a Benchmark's ``heldout:`` list, and a count of every peek at them.

Diagnosis and fixing never look at held-out Tasks. A run that includes them is
a **peek**, and each one is counted: locally in ``.plural/heldout.jsonl``, and
in the hosted project's ``benchmark_heldout_runs``. Only ``plural run
--heldout`` and the confirm commands run them.

Examples:
    >>> import tempfile
    >>> folder = Path(tempfile.mkdtemp())
    >>> _ = record_peek(folder, benchmark="quoting", job_id="job_1", purpose="eval", tasks=["q1"])
    >>> len(peeks(folder, "quoting"))
    1
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PEEKS_FILE = "heldout.jsonl"


def peeks_path(state_dir: Path) -> Path:
    """The local peek ledger in a project's ``.plural`` folder.

    Returns:
        ``.plural/heldout.jsonl``.
    """
    return state_dir / PEEKS_FILE


def record_peek(
    state_dir: Path,
    *,
    benchmark: str,
    job_id: str,
    purpose: str,
    tasks: Sequence[str],
    user: str | None = None,
) -> dict[str, Any]:
    """Count one run that touched held-out Tasks.

    Returns:
        The record written.
    """
    record = {
        "benchmark": benchmark,
        "job_id": job_id,
        "purpose": purpose,
        "tasks": list(tasks),
        "user": user,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = peeks_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def peeks(state_dir: Path, benchmark: str | None = None) -> list[dict[str, Any]]:
    """Every counted peek, optionally for one Benchmark.

    Returns:
        The records, oldest first.
    """
    path = peeks_path(state_dir)
    if not path.is_file():
        return []
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return [item for item in records if benchmark is None or item.get("benchmark") == benchmark]


__all__ = ["PEEKS_FILE", "peeks", "peeks_path", "record_peek"]
