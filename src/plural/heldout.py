"""The held-out split: Tasks kept back to confirm a fix, and a count of every peek at them.

Diagnosis and fixing never look at held-out Tasks. A run that includes them is
a **peek**, and each one is counted: locally in ``.plural/heldout.jsonl``, and
in the hosted project's ``benchmark_heldout_runs``. Only ``plural run
--heldout`` and the confirm commands run them.

Examples:
    >>> split_heldout([f"t{i}" for i in range(10)], 0.3, seed=7)
    ('t2', 't5', 't6')
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PEEKS_FILE = "heldout.jsonl"
DEFAULT_FRACTION = 0.3
MIN_TASKS_FOR_DEFAULT = 20
"""``plural eval init`` holds out ``DEFAULT_FRACTION`` by default from this many Tasks."""


def split_heldout(
    tasks: Sequence[str],
    fraction: float,
    *,
    seed: int = 0,
    groups: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Pick the held-out Tasks with a seeded sample, optionally stratified.

    With ``groups`` (each Task's category), each group gives the same share,
    rounded, and at least one Task stays in dev from every group. Without, the
    sample is over all Tasks. The same seed always picks the same Tasks.

    Args:
        tasks: Every Task in the Benchmark, by name.
        fraction: The share to hold out, above 0 and below 1.
        seed: The sample's seed.
        groups: Each Task's stratum, such as its category.

    Returns:
        The held-out Task names, in Benchmark order.

    Raises:
        ValueError: When the fraction is out of range or would hold out every Task.

    Examples:
        >>> groups = {"a1": "a", "a2": "a", "b1": "b", "b2": "b"}
        >>> split_heldout(list(groups), 0.5, seed=1, groups=groups)
        ('a1', 'b1')
    """
    if not 0 < fraction < 1:
        raise ValueError(f"the held-out share must be above 0 and below 1, not {fraction:g}")
    rng = random.Random(seed)
    strata: dict[str, list[str]] = {}
    for task in tasks:
        strata.setdefault((groups or {}).get(task, ""), []).append(task)
    chosen: set[str] = set()
    for members in strata.values():
        count = min(len(members) - 1, round(len(members) * fraction))
        if count > 0:
            chosen.update(rng.sample(members, count))
    if not chosen and len(tasks) > 1:
        chosen.add(rng.choice(list(tasks)))
    if len(chosen) >= len(tasks):
        raise ValueError("the split would hold out every Task; a Benchmark needs dev Tasks")
    return tuple(task for task in tasks if task in chosen)


def suggested_count(total: int, fraction: float = DEFAULT_FRACTION) -> int:
    """How many Tasks a split of ``fraction`` holds out of ``total``.

    Returns:
        The count, at least one when there are two or more Tasks.

    Examples:
        >>> suggested_count(60), suggested_count(5)
        (18, 2)
    """
    return max(1, math.floor(total * fraction + 0.5)) if total > 1 else 0


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


__all__ = [
    "DEFAULT_FRACTION",
    "MIN_TASKS_FOR_DEFAULT",
    "PEEKS_FILE",
    "peeks",
    "peeks_path",
    "record_peek",
    "split_heldout",
    "suggested_count",
]
