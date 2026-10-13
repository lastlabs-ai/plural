"""Rebuild a Trial's App steps from the App host's account rather than the Harness's.

A Harness writes ``episode.jsonl``, but the Harness is the code under test: it
could add a step, change a reward, or leave steps out. The App host, which
the Harness cannot reach into, records every action it ran. A Job therefore
keeps the Harness's step records only for their place in the transcript, and
takes every observation, reward, and outcome on them from the host. A step
the Harness never recorded, as with Harnesses that write no episode at all,
is added from the host's record.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from plural.apps.host import STEPS_FILE
from plural.rewards import event_id

_HOST_FIELDS = (
    "observation",
    "reward",
    "rewards",
    "terminated",
    "truncated",
    "info",
    "view",
    "error",
    "app",
    "seat",
    "action",
    "arguments",
    "sequence",
    "event_id",
)


_UNVERIFIED = frozenset({*_HOST_FIELDS} - {"action", "arguments"})
"""A step the host never ran keeps what the Harness said it did, marked unverified."""


def _step_number(record: Mapping[str, Any]) -> int | None:
    info = record.get("info")
    value = info.get("step") if isinstance(info, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _host_fields(step: Mapping[str, Any]) -> dict[str, Any]:
    info = dict(step.get("info") or {}) if isinstance(step.get("info"), Mapping) else {}
    seat = {"seat": step["seat"]} if step.get("seat") else {}
    return {
        **seat,
        "observation": step.get("observation"),
        "reward": float(step.get("reward") or 0.0),
        "rewards": list(step.get("rewards") or []),
        "terminated": bool(step.get("terminated")),
        "truncated": bool(step.get("truncated")),
        "info": info,
        "view": step.get("view") or None,
        "error": info.get("error"),
        "app": step.get("app"),
        "action": step.get("action"),
        "arguments": dict(step.get("arguments") or {})
        if isinstance(step.get("arguments"), Mapping)
        else {},
    }


def merge_host_steps(
    records: Sequence[Mapping[str, Any]], steps: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The episode with every App step as the host recorded it.

    Each Harness step record is matched to the host step whose number it
    reports, since the host returns that number with every observation. A
    matched record takes the host's action, arguments, observation, rewards,
    and outcome; a record matching no host step keeps only its place, with no
    reward. Host steps no record matched are appended in order. Every record
    is then numbered afresh, so no two share the ``event_id`` a reward targets.

    Returns:
        The merged records.
    """
    by_number = {number: step for step in steps if (number := _step_number(step)) is not None}
    used: set[int] = set()
    merged: list[dict[str, Any]] = []
    for record in records:
        if record.get("kind") != "environment.step":
            merged.append(dict(record))
            continue
        number = _step_number(record)
        host = by_number.get(number) if number is not None and number not in used else None
        if host is None:
            clean = {key: value for key, value in record.items() if key not in _UNVERIFIED}
            clean.update(
                {
                    "reward": 0.0,
                    "rewards": [],
                    "info": {"unverified": True},
                    "error": "The App host has no record of this step.",
                }
            )
        else:
            used.add(number)  # type: ignore[arg-type]
            clean = {key: value for key, value in record.items() if key not in _HOST_FIELDS}
            clean.update(_host_fields(host))
        merged.append(clean)
    turn = max((_integer(item.get("turn")) for item in merged), default=0)
    for number in sorted(set(by_number) - used):
        host = by_number[number]
        merged.append(
            {
                "kind": "environment.step",
                "turn": max(turn, _integer(host.get("turn"))),
                **_host_fields(host),
            }
        )
    for sequence, item in enumerate(merged, start=1):
        item["sequence"] = sequence
        item["event_id"] = event_id(sequence)
    return merged


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def episode_terminated(steps: Sequence[Mapping[str, Any]]) -> tuple[bool, bool]:
    """Whether the host saw the Environment end, by termination or truncation.

    Returns:
        ``(terminated, truncated)`` after the last step.
    """
    if not steps:
        return False, False
    last = steps[-1]
    return bool(last.get("terminated")), bool(last.get("truncated"))


def dump_jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Encode rows as JSON lines.

    Returns:
        The file's bytes.
    """
    return "".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows).encode()


__all__ = ["STEPS_FILE", "dump_jsonl", "episode_terminated", "merge_host_steps"]
