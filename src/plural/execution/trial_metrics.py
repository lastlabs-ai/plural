"""Build a Trial's metrics from its Verifier results, the App host's points, and its receipt."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from plural.atif import ATIF_FILE
from plural.jobs import VerifierResult
from plural.metrics import (
    METRICS_FILE,
    MetricSpec,
    aggregate_series,
    builtin_values,
    combine_seats,
    seat_series,
    series_by_metric,
)
from plural.sandbox.models import DownloadedFile
from plural.tasks import TaskDefinition

FINISHED = frozenset({"environment_terminated", "agent_finished", "agent_response"})
"""Stop reasons that mean the episode reached its end, rather than a limit or an error."""


def metric_lines(artifacts: Sequence[DownloadedFile]) -> list[dict[str, Any]]:
    """The App host's running metric points, from the Trial's ``metrics.jsonl``.

    Returns:
        One mapping per point, in the order recorded.
    """
    item = next((entry for entry in artifacts if entry.path == METRICS_FILE), None)
    if item is None:
        return []
    lines: list[dict[str, Any]] = []
    for raw in item.data.decode(errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        if isinstance(parsed, Mapping):
            lines.append(dict(parsed))
    return lines


def task_metric_specs(task: TaskDefinition) -> dict[str, MetricSpec]:
    """Every metric a Task's Verifiers produce, by name; the first Verifier wins a shared name.

    Returns:
        Each metric's spec.
    """
    specs: dict[str, MetricSpec] = {}
    for binding in task.verifiers:
        for spec in binding.verifier.metric_specs:
            specs.setdefault(spec.name, spec)
    return specs


def seat_metrics(
    task: TaskDefinition,
    artifacts: Sequence[DownloadedFile],
    *,
    turns: int,
    lines: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, float | None]]:
    """Each seat's value of every running metric its ``measure`` hook gave per seat.

    Returns:
        Seat to metric to value; empty when no metric was measured per seat.
    """
    specs = task_metric_specs(task)
    grouped = seat_series(metric_lines(artifacts) if lines is None else lines)
    steps = max(turns, 0) or None
    return {
        seat: {
            name: aggregate_series(points, specs[name], steps=steps)
            for name, points in metrics.items()
            if name in specs and specs[name].kind == "running"
        }
        for seat, metrics in grouped.items()
    }


def _total_tokens(artifacts: Sequence[DownloadedFile]) -> int | None:
    item = next((entry for entry in artifacts if entry.path == ATIF_FILE), None)
    if item is None:
        return None
    try:
        final = json.loads(item.data).get("final_metrics") or {}
    except (ValueError, AttributeError):
        return None
    prompt, completion = final.get("total_prompt_tokens"), final.get("total_completion_tokens")
    if not isinstance(prompt, (int, float)) and not isinstance(completion, (int, float)):
        return None
    return int((prompt or 0) + (completion or 0))


def trial_metrics(
    task: TaskDefinition,
    results: Sequence[VerifierResult],
    artifacts: Sequence[DownloadedFile],
    *,
    cost_usd: float | None,
    latency_seconds: float | None,
    turns: int,
    stop_reason: str,
    succeeded: bool,
    checked: bool = True,
) -> dict[str, float | None]:
    """Every metric's value on one Trial.

    The built-ins come first; then each running metric's aggregate over the
    App host's points; then what each Verifier's ``check`` returned. A
    declared metric whose Verifier gave no value is ``None``, and so is a
    running metric with no points. When the Trial failed before its checks
    ran (``checked`` false), their metrics are missing rather than ``None``:
    not applicable is a judgment only a check can make.

    Returns:
        Each metric's value by name.
    """
    values = builtin_values(
        cost_usd=cost_usd,
        latency_seconds=latency_seconds,
        turns=turns,
        total_tokens=_total_tokens(artifacts),
        succeeded=succeeded and stop_reason in FINISHED if stop_reason else succeeded,
    )
    specs = task_metric_specs(task)
    steps = max(turns, 0)
    lines = metric_lines(artifacts)
    series = series_by_metric(lines)
    by_seat = seat_metrics(task, artifacts, turns=turns, lines=lines)
    for name, spec in specs.items():
        if (
            spec.kind == "running"
            and name not in series
            and any(name in seat for seat in by_seat.values())
        ):
            values[name] = combine_seats(
                (seat.get(name) for seat in by_seat.values()), spec.seat_aggregate
            )
        elif spec.kind == "running":
            values[name] = aggregate_series(series.get(name, ()), spec, steps=steps or None)
        elif checked:
            values.setdefault(name, None)
    for result in results:
        for name, value in result.metrics.items():
            values[name] = value
    return values


__all__ = ["FINISHED", "metric_lines", "seat_metrics", "task_metric_specs", "trial_metrics"]
