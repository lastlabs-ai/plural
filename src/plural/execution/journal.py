"""A long run's journal: what the App host recorded so far, and its run checkpoints.

When an Environment sets ``checkpoint_every``, the Job polls the host as the
episode runs and appends its steps, States, and metric points to the Trial's
``run/`` folder, with the Agent's episode record as of the latest run
checkpoint. The folder has the layout of a finished Trial's artifacts, so a
checkpoint is rebuilt from it the way one is rebuilt from any Trial. A Trial
whose runner died leaves a journal and no result: it is interrupted, and
``plural trial resume`` continues it from the latest run checkpoint.
"""

from __future__ import annotations

import json
import math
import shutil
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plural.apps.host import STATES_FILE, STEPS_FILE
from plural.harness.episode import EPISODE_FILE
from plural.metrics import METRICS_FILE
from plural.sim import PERSONAS_FILE

RUN_FOLDER = "run"
"""Under a Trial's folder: the journal of its latest long execution."""
CHECKPOINTS_FILE = "run-checkpoints.jsonl"
JOURNAL_FILE = "journal.json"
STALE_SECONDS = 60.0
"""How long a journal goes unwritten before its runner is taken to have died.
The Job writes it at least every heartbeat, five seconds apart."""

_STREAMS = {
    "steps": STEPS_FILE,
    "states": STATES_FILE,
    "metrics": METRICS_FILE,
    "checkpoints": CHECKPOINTS_FILE,
    "personas": PERSONAS_FILE,
}


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _append(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    text = "".join(json.dumps(dict(row), sort_keys=True, default=str) + "\n" for row in rows)
    if text:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)


@dataclass
class RunJournal:
    """The ``run/`` folder of one Trial."""

    root: Path

    @classmethod
    def of(cls, trial_dir: Path) -> RunJournal:
        """The journal in a Trial's folder.

        Returns:
            The journal; it may not exist yet.
        """
        return cls(trial_dir / RUN_FOLDER)

    @property
    def exists(self) -> bool:
        """Whether a long execution of the Trial has written one."""
        return (self.root / JOURNAL_FILE).is_file()

    def state(self) -> dict[str, Any]:
        """The journal's own record: its execution, cursors, and when it was last written.

        Returns:
            The record, or an empty one.
        """
        path = self.root / JOURNAL_FILE
        if not path.is_file():
            return {}
        value = json.loads(path.read_text("utf-8"))
        return value if isinstance(value, dict) else {}

    def start(
        self,
        execution_id: int,
        *,
        prefix: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        resumed_from: int | None = None,
    ) -> None:
        """Begin the journal of a new execution.

        A resumed execution starts from the interrupted one's records through
        its checkpoint, so a second interruption still has the whole run.
        """
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        for key, rows in (prefix or {}).items():
            if key in _STREAMS:
                _append(self.root / _STREAMS[key], rows)
        self._write_state(
            {
                "execution_id": execution_id,
                "cursors": {key: 0 for key in _STREAMS},
                "resumed_from": resumed_from,
                "started_at": _now(),
            }
        )

    def append(self, progress: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Add what the host recorded since the last poll.

        Returns:
            The run checkpoints this poll added.
        """
        state = self.state()
        cursors = dict(state.get("cursors") or {})
        added: list[dict[str, Any]] = []
        for key, name in _STREAMS.items():
            rows = [dict(item) for item in progress.get(key) or () if isinstance(item, Mapping)]
            _append(self.root / name, rows)
            cursors[key] = int(cursors.get(key) or 0) + len(rows)
            if key == "checkpoints":
                added = rows
        clock = progress.get("clock")
        self._write_state(
            {**state, "cursors": cursors, **({"clock": clock} if clock is not None else {})}
        )
        return added

    def cursors(self) -> dict[str, int]:
        """How many of each record the journal holds from this execution.

        Returns:
            The cursors the host's ``progress`` takes as ``since``.
        """
        return {key: int(value) for key, value in (self.state().get("cursors") or {}).items()}

    def episode(self, data: bytes) -> None:
        """Keep the Agent's episode record as of the latest run checkpoint."""
        temporary = self.root / f".{EPISODE_FILE}.tmp"
        temporary.write_bytes(data)
        temporary.replace(self.root / EPISODE_FILE)

    def touch(self) -> None:
        """Say the runner is alive."""
        state = self.state()
        if state:
            self._write_state(state)

    def checkpoints(self) -> list[dict[str, Any]]:
        """Every run checkpoint the journal holds, in order.

        Returns:
            Each marker: its step, turn, simulated time, and elapsed seconds.
        """
        return _read(self.root / CHECKPOINTS_FILE)

    def latest(self) -> dict[str, Any] | None:
        """The latest run checkpoint whose step the journal holds.

        Returns:
            The marker, or ``None`` when there is none yet.
        """
        steps = {
            int(item["step"]) for item in self.read("steps") if isinstance(item.get("step"), int)
        }
        states = {
            int(item["step"]) for item in self.read("states") if isinstance(item.get("step"), int)
        }
        usable = [
            item
            for item in self.checkpoints()
            if int(item.get("step") or 0) in steps and int(item.get("step") or 0) in states
        ]
        return usable[-1] if usable else None

    def read(self, key: str) -> list[dict[str, Any]]:
        """One of the journal's streams.

        Returns:
            Its records, in order.
        """
        return _read(self.root / _STREAMS[key])

    def spent_through(self, step: int) -> float | None:
        """What the Agent's model calls cost through ``step``, from its episode record.

        Returns:
            The cost in dollars, or ``None`` when no call reported one.
        """
        records = sorted(
            _read(self.root / EPISODE_FILE), key=lambda item: int(item.get("sequence") or 0)
        )
        cut = 0
        for index, record in enumerate(records):
            info = record.get("info")
            number = info.get("step") if isinstance(info, Mapping) else None
            if (
                record.get("kind") == "environment.step"
                and isinstance(number, int)
                and number <= step
            ):
                cut = index + 1
        values = []
        for record in records[:cut]:
            if record.get("kind") not in {"model.call", "context.compaction"}:
                continue
            usage = record.get("usage")
            cost = usage.get("cost_usd") if isinstance(usage, Mapping) else None
            if isinstance(cost, (int, float)) and math.isfinite(cost):
                values.append(float(cost))
        return math.fsum(values) if values else None

    def _write_state(self, state: Mapping[str, Any]) -> None:
        path = self.root / JOURNAL_FILE
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps({**state, "updated_at": _now(), "updated": time.time()}, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)


def interrupted(trial_dir: Path, *, now: float | None = None) -> bool:
    """Whether a Trial's runner died mid-execution.

    Its journal names an execution that has no result, and has not been
    written for :data:`STALE_SECONDS`.

    Returns:
        ``True`` for an interrupted Trial.
    """
    journal = RunJournal.of(trial_dir)
    if not journal.exists:
        return False
    state = journal.state()
    execution = state.get("execution_id")
    if not isinstance(execution, int):
        return False
    if (trial_dir / "executions" / str(execution) / "result.json").is_file():
        return False
    updated = state.get("updated")
    if not isinstance(updated, (int, float)):
        return True
    return (time.time() if now is None else now) - float(updated) > STALE_SECONDS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["CHECKPOINTS_FILE", "RUN_FOLDER", "STALE_SECONDS", "RunJournal", "interrupted"]
