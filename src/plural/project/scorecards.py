"""A project's Scorecards at work: labels on local Trials, calibration, decisions, rescore.

The CLI's ``plural scorecard`` commands are thin wrappers over these. Labels on
local Trials live in ``.plural/labels/<scorecard>.jsonl``, and a calibration in
``.plural/calibrations/<scorecard>@<version>.json``, so the same code computes
agreement with or without a hosted project.

Examples:
    >>> from plural.project import Project, Workspace
    >>> space = Workspace(Project.find())  # doctest: +SKIP
    >>> calibration = calibrate_scorecard(space, "steel-quoting")  # doctest: +SKIP
    >>> calibration.metric("delivery_feasible").status  # doctest: +SKIP
    'trusted'
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from plural.jobs import JobResult, TrialResult
from plural.metrics import MetricSpec
from plural.project.layout import BENCHMARK, SCORECARD, VERIFIER, ProjectError, ResourceRef
from plural.project.manifests import read_yaml_mapping
from plural.project.resources import Workspace
from plural.scorecards import (
    Calibration,
    Decision,
    Label,
    Scorecard,
    ScorecardMetric,
    calibrate,
    labels_path,
    pass_rate,
    read_labels,
    rescore,
    write_labels,
)

CALIBRATIONS_DIR = "calibrations"


def load_scorecard(workspace: Workspace, name: str) -> Scorecard:
    """A project's Scorecard, by name.

    Returns:
        The Scorecard.

    Raises:
        ProjectError: When it is not in the project or does not load.
    """
    return workspace.load(ResourceRef(SCORECARD.name, name)).value  # type: ignore[no-any-return]


def metric_specs(workspace: Workspace) -> dict[str, MetricSpec]:
    """Every metric the project's Tasks' Verifiers declare, by name.

    Returns:
        Each metric's spec; the first Verifier to declare a name wins.
    """
    specs: dict[str, MetricSpec] = {}
    for name in workspace.project.names(VERIFIER):
        try:
            verifier = workspace.get("verifier", name)
        except (ProjectError, ValueError):
            continue
        for item in verifier.metric_specs:
            specs.setdefault(item.name, item)
    return specs


def job_trials(workspace: Workspace, job_id: str) -> list[dict[str, Any]]:
    """A local Job's finished Trials, as Scorecards read them.

    Returns:
        One mapping per Trial: ``trial_id``, ``task``, ``agent``, ``status``,
        ``score``, ``metrics``, and ``passed``.

    Raises:
        ProjectError: When there is no such local Job, or it has not finished.
    """
    directory = workspace.project.jobs_dir / job_id
    path = directory / "result.json"
    if not path.is_file():
        known = sorted(item.name for item in workspace.project.jobs_dir.glob("*") if item.is_dir())
        hint = f" Local Jobs: {', '.join(known[-5:])}." if known else ""
        raise ProjectError(
            f"No finished local Job {job_id!r}.{hint}\n"
            "Next: plural job list shows your Jobs; run one with plural run."
        )
    result = JobResult.model_validate_json(path.read_text("utf-8"))
    names = {item.agent_digest: item.agent_name for item in result.aggregates}
    return [_trial_row(item, names) for item in result.trials]


def _trial_row(trial: TrialResult, names: Mapping[str, str]) -> dict[str, Any]:
    digest = trial.receipt.agent_digest
    return {
        "trial_id": trial.receipt.trial_id,
        "task": trial.receipt.task_pin.name,
        "agent": names.get(digest) or trial.receipt.model.catalog_model_id,
        "status": trial.status,
        "score": trial.score,
        "metrics": dict(trial.metrics),
        "passed": trial.passed,
    }


def trial_metrics(workspace: Workspace, trial_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Each local Trial's stored metric values, wherever its Job is.

    Returns:
        Metric values by Trial id; a Trial not found locally is left out.
    """
    wanted = set(trial_ids)
    found: dict[str, dict[str, Any]] = {}
    root = workspace.project.jobs_dir
    if not root.is_dir():
        return found
    for job in root.iterdir():
        for trial_id in list(wanted):
            path = job / "trials" / trial_id / "result.json"
            if path.is_file():
                result = TrialResult.model_validate_json(path.read_text("utf-8"))
                found[trial_id] = dict(result.metrics)
                wanted.discard(trial_id)
    return found


def labels(workspace: Workspace, name: str) -> list[Label]:
    """The labels on a Scorecard's local Trials.

    Returns:
        The latest label from each labeler on each Trial.
    """
    return read_labels(labels_path(workspace.project.root, name))


def save_labels(workspace: Workspace, name: str, items: Iterable[Label]) -> int:
    """Append labels on local Trials; a later one from the same labeler replaces the earlier.

    Returns:
        How many were written.
    """
    return write_labels(labels_path(workspace.project.root, name), items)


def import_labels(
    workspace: Workspace, name: str, path: Path, job_id: str
) -> tuple[list[Label], list[str]]:
    """Attach labels keyed by Task and Agent to one local Job's Trials, and save them.

    Each line of ``path`` is a JSON object with ``task``, ``agent``,
    ``labeler``, ``values``, and optionally ``verdict``, ``reason`` and
    ``reasons``. A line whose Task and Agent match no Trial of the Job is
    skipped and reported; one that matches several Trials (repeated attempts)
    labels each.

    Returns:
        The labels saved, and one line per skipped row.

    Raises:
        ProjectError: When the file cannot be read.
    """
    scorecard = load_scorecard(workspace, name)
    trials = job_trials(workspace, job_id)
    by_key: dict[tuple[str, str], list[str]] = {}
    for trial in trials:
        by_key.setdefault((trial["task"], trial["agent"]), []).append(trial["trial_id"])
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(
            f"Cannot read labels from {path}: {exc}\n"
            "Next: give a JSONL file with task, agent, labeler, and values on each line."
        ) from exc
    known = {item.name for item in scorecard.metrics}
    saved: list[Label] = []
    skipped: list[str] = []
    for number, row in enumerate(rows, start=1):
        key = (str(row.get("task")), str(row.get("agent")))
        unknown = sorted(set(row.get("values") or {}) - known)
        if unknown:
            skipped.append(f"line {number}: {', '.join(unknown)} not on {scorecard.reference}")
            continue
        matches = by_key.get(key)
        if not matches:
            skipped.append(f"line {number}: no Trial of {key[0]} by {key[1]} in Job {job_id}")
            continue
        for trial_id in matches:
            saved.append(
                Label(
                    scorecard=name,
                    trial_id=trial_id,
                    labeler=str(row.get("labeler") or "unknown"),
                    values=row.get("values") or {},
                    verdict=row.get("verdict") or "unsure",
                    reason=str(row.get("reason") or ""),
                    reasons=row.get("reasons") or {},
                    task=key[0],
                )
            )
    save_labels(workspace, name, saved)
    return saved, skipped


def pick_for_labeling(
    trials: Sequence[Mapping[str, Any]],
    *,
    count: int = 20,
    labeled: Iterable[str] = (),
) -> list[Mapping[str, Any]]:
    """Choose Trials to label: half the grader passed, half it failed, one per Task first.

    Returns:
        Up to ``count`` Trials not yet labeled, alternating passed and failed.

    Examples:
        >>> rows = [
        ...     {"trial_id": "a", "task": "t1", "score": 1.0},
        ...     {"trial_id": "b", "task": "t1", "score": 0.0},
        ...     {"trial_id": "c", "task": "t2", "score": 1.0},
        ... ]
        >>> [item["trial_id"] for item in pick_for_labeling(rows, count=2)]
        ['a', 'b']
    """
    done = set(labeled)
    fresh = [item for item in trials if item["trial_id"] not in done]

    def graded(item: Mapping[str, Any]) -> bool:
        passed = item.get("passed")
        return bool(passed) if passed is not None else (item.get("score") or 0) >= 1

    passing = [item for item in fresh if graded(item)]
    failing = [item for item in fresh if not graded(item)]
    chosen: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    # One Trial per Task first, so the labels are not near-duplicates; then the rest.
    for distinct in (True, False):
        for pair in _interleave(passing, failing):
            if len(chosen) >= count:
                return chosen
            if pair in chosen or (distinct and pair["task"] in seen):
                continue
            chosen.append(pair)
            seen.add(str(pair["task"]))
    return chosen


def _interleave(
    first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    merged: list[Mapping[str, Any]] = []
    for index in range(max(len(first), len(second))):
        merged.extend(group[index] for group in (first, second) if index < len(group))
    return merged


def calibrate_scorecard(workspace: Workspace, name: str) -> Calibration:
    """Check a Scorecard's graders against the labels on local Trials, and save the result.

    Returns:
        The calibration, also written to ``.plural/calibrations/<name>@<version>.json``.

    Raises:
        ProjectError: When the Scorecard has no labels yet.
    """
    scorecard = load_scorecard(workspace, name)
    given = labels(workspace, name)
    if not given:
        raise ProjectError(
            f"Scorecard {name} has no labels yet.\n"
            f"Next: plural scorecard label {name} --job JOB labels its Trials."
        )
    graders = trial_metrics(workspace, {item.trial_id for item in given})
    result = calibrate(scorecard, given, graders, metric_specs(workspace))
    path = calibration_path(workspace, scorecard)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def calibration_path(workspace: Workspace, scorecard: Scorecard) -> Path:
    """Where a Scorecard version's latest calibration is saved.

    Returns:
        ``.plural/calibrations/<name>@<version>.json``.
    """
    return workspace.project.state_dir / CALIBRATIONS_DIR / f"{scorecard.reference}.json"


def latest_calibration(workspace: Workspace, name: str) -> Calibration | None:
    """The calibration saved for the Scorecard's current version.

    Returns:
        The calibration, or ``None`` when it has not been calibrated.
    """
    path = calibration_path(workspace, load_scorecard(workspace, name))
    if not path.is_file():
        return None
    return Calibration.model_validate_json(path.read_text("utf-8"))


def with_targets(scorecard: Scorecard, targets: Mapping[str, str]) -> Scorecard:
    """The Scorecard with some metrics' targets changed, to see what a change would do.

    Returns:
        A copy; the version is unchanged, since nothing was saved.

    Raises:
        ProjectError: When a target names a metric the Scorecard does not have.
    """
    unknown = sorted(set(targets) - {item.name for item in scorecard.metrics})
    if unknown:
        raise ProjectError(
            f"--target names {', '.join(unknown)}, which {scorecard.reference} does not "
            f"have.\nNext: name one of {', '.join(item.name for item in scorecard.metrics)}."
        )
    metrics = [
        ScorecardMetric.model_validate(
            {**item.model_dump(), "target": targets.get(item.name, item.target)}
        )
        for item in scorecard.metrics
    ]
    return Scorecard.model_validate({**scorecard.model_dump(), "metrics": metrics})


def rescore_job(
    workspace: Workspace,
    name: str,
    job_id: str,
    *,
    targets: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Apply a Scorecard's gates and targets to a local Job's stored metrics, without a rerun.

    Returns:
        ``scorecard``, ``job_id``, each Trial's ``rows``, each Agent's
        ``pass_rate`` under this Scorecard, and ``recorded``: the rate the
        Trials recorded when they ran, where they ran under a Scorecard.
    """
    scorecard = load_scorecard(workspace, name)
    if targets:
        scorecard = with_targets(scorecard, targets)
    trials = job_trials(workspace, job_id)
    groups = _task_categories(workspace, {str(item["task"]) for item in trials})
    rows = rescore(scorecard, trials, categories=groups)
    agents: dict[str, list[dict[str, Any]]] = {}
    recorded: dict[str, list[bool]] = {}
    for trial, row in zip(trials, rows, strict=True):
        row["agent"] = trial["agent"]
        agents.setdefault(trial["agent"], []).append(row)
        if trial["passed"] is not None:
            recorded.setdefault(trial["agent"], []).append(bool(trial["passed"]))
    return {
        "scorecard": scorecard.reference,
        "targets": dict(targets or {}),
        "job_id": job_id,
        "rows": rows,
        "pass_rate": {agent: pass_rate(items) for agent, items in agents.items()},
        "recorded": {
            agent: sum(values) / len(values) for agent, values in recorded.items() if values
        },
    }


def _task_categories(workspace: Workspace, tasks: set[str]) -> dict[str, tuple[str, ...]]:
    """Each Task's categories in the project's Benchmarks, for ``applies_to``.

    Returns:
        Task name to category ids.
    """
    found: dict[str, tuple[str, ...]] = {}
    for benchmark in workspace.project.names(BENCHMARK):
        try:
            payload = read_yaml_mapping(
                workspace.project.manifest_path(ResourceRef(BENCHMARK.name, benchmark))
            )
        except (ProjectError, OSError):
            continue
        for group in payload.get("categories") or ():
            for task in group.get("tasks") or ():
                if task in tasks and group.get("id") not in found.get(task, ()):
                    found[task] = (*found.get(task, ()), str(group.get("id")))
    return found


def record_decision(
    workspace: Workspace,
    name: str,
    decision: Decision,
    *,
    description: str | None = None,
) -> Scorecard:
    """Append a decision to a Scorecard and bump its patch version.

    ``description``, with the decision's ``metric``, also rewrites that
    metric's description. The rest of ``scorecard.yaml``, comments included,
    is kept as written.

    Returns:
        The new Scorecard version.

    Raises:
        ProjectError: When the decision names a metric the Scorecard does not have.
    """
    scorecard = load_scorecard(workspace, name)
    if decision.metric is not None and scorecard.metric(decision.metric) is None:
        raise ProjectError(
            f"The decision names metric {decision.metric}, which {scorecard.reference} does "
            "not have.\nNext: leave --metric out, or name one of its metrics."
        )
    bumped = scorecard.bumped("patch")
    path = workspace.project.manifest_path(ResourceRef(SCORECARD.name, name))
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^version:.*$", f"version: {bumped.version}", text, count=1, flags=re.MULTILINE)
    entry = {key: value for key, value in decision.model_dump().items() if value is not None}
    block = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, width=88)
    block = "".join(f"  {line}\n" for line in block.splitlines())
    if re.search(r"^decisions:\s*\[\]\s*$", text, flags=re.MULTILINE):
        text = re.sub(
            r"^decisions:\s*\[\]\s*$\n?", "decisions:\n" + block, text, count=1, flags=re.MULTILINE
        )
    elif re.search(r"^decisions:\s*$", text, flags=re.MULTILINE):
        lines = text.splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if re.match(r"^decisions:\s*$", line))
        end = start + 1
        while end < len(lines) and (lines[end].startswith((" ", "-")) or not lines[end].strip()):
            end += 1
        lines.insert(end, block)
        text = "".join(lines)
    else:
        text = text.rstrip("\n") + "\ndecisions:\n" + block
    if description is not None and decision.metric is not None:
        text = _set_description(text, decision.metric, description)
    path.write_text(text, encoding="utf-8")
    workspace.invalidate(ResourceRef(SCORECARD.name, name))
    return load_scorecard(workspace, name)


def _set_description(text: str, metric: str, description: str) -> str:
    data = yaml.safe_load(text)
    for item in data.get("metrics") or ():
        if item.get("name") == metric:
            item["description"] = description
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if re.match(r"^metrics:\s*$", line))
    end = start + 1
    while end < len(lines) and (lines[end].startswith((" ", "-")) or not lines[end].strip()):
        end += 1
    block = yaml.safe_dump(data["metrics"], sort_keys=False, allow_unicode=True, width=88)
    lines[start + 1 : end] = ["".join(f"  {line}\n" for line in block.splitlines())]
    return "".join(lines)


def render_good(scorecard: Scorecard) -> str:
    """``GOOD.md`` for a Scorecard: what good means, its metrics by role, and its decisions.

    Returns:
        The Markdown text.

    Examples:
        >>> card = Scorecard(name="x", good="Right.", metrics=[{"name": "ok", "role": "gate"}])
        >>> "## Must pass" in render_good(card)
        True
    """
    title = scorecard.name.replace("-", " ").capitalize()
    lines = [f"# {title}: what good means", ""]
    if scorecard.owner:
        lines += [f"Owner: {scorecard.owner}", ""]
    if scorecard.good.strip():
        lines += [scorecard.good.strip(), ""]
    for role, heading in (
        ("gate", "Must pass"),
        ("objective", "Aim for"),
        ("guardrail", "Keep an eye on"),
    ):
        chosen = [item for item in scorecard.metrics if item.role == role]
        if not chosen:
            continue
        lines += [f"## {heading}", ""]
        for item in chosen:
            target = f" ({item.target})" if item.target else ""
            about = f": {item.description}" if item.description else ""
            lines.append(f"- **{item.name}**{target}{about}")
        lines.append("")
    if scorecard.decisions:
        lines += ["## Decisions", ""]
        for decision in scorecard.decisions:
            by = ", ".join(part for part in (decision.decided_by, decision.date) if part)
            lines.append(f"- *{decision.question}*")
            lines.append(f"  {decision.answer}" + (f" ({by})" if by else ""))
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "CALIBRATIONS_DIR",
    "calibrate_scorecard",
    "calibration_path",
    "import_labels",
    "job_trials",
    "labels",
    "latest_calibration",
    "load_scorecard",
    "metric_specs",
    "pick_for_labeling",
    "record_decision",
    "render_good",
    "rescore_job",
    "save_labels",
    "trial_metrics",
    "with_targets",
]
