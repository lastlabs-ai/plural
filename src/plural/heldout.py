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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plural.jobs import TrialResult

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


def revealed_nothing(trials: Sequence[TrialResult]) -> bool | None:
    """Whether a held-out run showed nothing: every Trial errored before a verdict.

    Such a run still counts as a peek.

    Returns:
        ``True`` or ``False``, or ``None`` when there are no Trials.
    """
    if not trials:
        return None
    return all(
        item.status != "succeeded" and item.score is None and item.stop_reason == "error"
        for item in trials
    )


def peeks(state_dir: Path, benchmark: str | None = None) -> list[dict[str, Any]]:
    """Every counted peek, optionally for one Benchmark.

    Each says whether its run ``revealed_nothing``, read from the Job's local
    result; ``None`` while the Job has no result here.

    Returns:
        The records, oldest first.
    """
    path = peeks_path(state_dir)
    if not path.is_file():
        return []
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return [
        {**item, "revealed_nothing": _revealed_nothing(state_dir, item)}
        for item in records
        if benchmark is None or item.get("benchmark") == benchmark
    ]


def local_uses(state_dir: Path, names: Sequence[str]) -> dict[str, str]:
    """Which of these Tasks a local Job has already run, other than as held out.

    A held-out Task must be one nothing has touched. A local Job that ran it as
    a dev Task, on its own, or as a fork has used it; a ``--heldout`` run that
    held it out has only peeked. Read from each Job's ``config.json``.

    Returns:
        The first Job found to use each used Task, by Task name.
    """
    wanted = set(names)
    used: dict[str, str] = {}
    root = state_dir / "jobs"
    if not wanted or not root.is_dir():
        return used
    for directory in sorted(root.iterdir()):
        config = directory / "config.json"
        if not config.is_file():
            continue
        try:
            source = json.loads(config.read_text("utf-8")).get("source") or {}
            ran = _ran(directory)
        except ValueError:
            continue
        held = set()
        if source.get("kind") == "benchmark" and source.get("include_heldout"):
            held = set((source.get("benchmark") or {}).get("heldout") or ())
        for name in ran - held:
            if name in wanted:
                used.setdefault(name, directory.name)
    return used


def _ran(directory: Path) -> set[str]:
    """The Tasks a local Job ran Trials of, from its Trials' receipts.

    Returns:
        Their names.
    """
    result = directory / "result.json"
    if result.is_file():
        trials = json.loads(result.read_text("utf-8")).get("trials") or ()
    else:
        trials = [
            json.loads(path.read_text("utf-8")) for path in directory.glob("trials/*/result.json")
        ]
    return {
        str(pin["name"])
        for item in trials
        if isinstance(pin := (item.get("receipt") or {}).get("task_pin"), dict) and pin.get("name")
    }


def _revealed_nothing(state_dir: Path, record: dict[str, Any]) -> bool | None:
    from plural.jobs import JobResult

    result = state_dir / "jobs" / str(record.get("job_id")) / "result.json"
    if not result.is_file():
        return None
    try:
        trials = JobResult.model_validate_json(result.read_text("utf-8")).trials
    except ValueError:
        return None
    return revealed_nothing(trials)


__all__ = ["PEEKS_FILE", "local_uses", "peeks", "peeks_path", "record_peek", "revealed_nothing"]
