"""``plural job report``: how an Agent performs, why it fails, what changed, and why to trust it.

Every number is computed here, as a :class:`Fact` that names the Trials it
comes from. A model may write the summary, but only by referring to facts by
id, such as ``{N3}``; :func:`validate_summary` rejects a summary that writes
any number itself, and the ids are replaced with the computed values.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plural.common import FrozenModel
from plural.inspector.evidence import JobEvidence
from plural.inspector.findings import breakdown, load_findings
from plural.jobs import BenchmarkJobSource, JobResult, JobSpec, TrialResult
from plural.metrics import MetricSpec
from plural.project.checks import saved_checks
from plural.project.layout import ProjectError
from plural.project.resources import Workspace
from plural.project.runs import _load_local, _success_threshold
from plural.stats import clustered_bootstrap, paired_bootstrap, seed_for

REPORT_FILE = "report.md"
REPORT_DATA = "report.json"
SUMMARY_MODEL = "openai/gpt-5.6-terra"
"""The model that writes a report's summary, by default."""

_PLACEHOLDER = re.compile(r"\{(N[0-9]+)\}")
_DIGIT = re.compile(r"[0-9]")


class Fact(FrozenModel):
    """One computed number in a report.

    Attributes:
        fact_id: Its id, such as ``N3``, which a summary refers to.
        label: What it measures.
        value: The number.
        display: The number as the report prints it.
        trial_ids: The Trials it was computed from.
    """

    fact_id: str
    label: str
    value: float | int | None
    display: str
    trial_ids: tuple[str, ...] = ()


class JobReport(FrozenModel):
    """A Job's report: its sections, the facts they cite, and an optional summary.

    Attributes:
        job_id: The Job reported on.
        compare_job_id: The Job it was compared with, if any.
        generated_at: When.
        performance: Per Agent: pass and success rates, score, every metric.
        failures: The breakdown by cause and the Findings, when inspected.
        changes: The paired comparison, on dev and held-out Tasks.
        trust: Trust tiers, Task checks, and integrity findings.
        facts: Every number, with the Trials behind it.
        summary: A model's summary, with each fact id replaced by its value.
        summary_problems: Why a summary was rejected, when it was.
    """

    job_id: str
    compare_job_id: str | None = None
    generated_at: datetime
    performance: list[dict[str, Any]]
    failures: dict[str, Any] | None = None
    changes: dict[str, Any] | None = None
    trust: dict[str, Any]
    facts: tuple[Fact, ...]
    summary: str | None = None
    summary_problems: tuple[str, ...] = ()


class _Facts:
    def __init__(self) -> None:
        self.items: list[Fact] = []

    def add(
        self, label: str, value: float | int | None, display: str, trials: Iterable[str]
    ) -> str:
        fact = Fact(
            fact_id=f"N{len(self.items) + 1}",
            label=label,
            value=value,
            display=display,
            trial_ids=tuple(sorted(set(trials))),
        )
        self.items.append(fact)
        return fact.fact_id

    def rate(self, label: str, hits: Sequence[str], total: Sequence[str]) -> str | None:
        if not total:
            return None
        value = len(hits) / len(total)
        return self.add(label, value, f"{value:.0%} ({len(hits)} of {len(total)})", total)


class _Loaded:
    def __init__(self, workspace: Workspace, job_id: str) -> None:
        directory = workspace.project.jobs_dir / job_id
        self.spec: JobSpec
        self.spec, record = _load_local(workspace, job_id)
        path = directory / "result.json"
        if not path.is_file():
            raise ProjectError(f"Job {job_id} hasn't finished, so it has no report yet.")
        self.job_id = job_id
        self.root = workspace.project.root
        self.directory = directory
        self.result = JobResult.model_validate_json(path.read_text("utf-8"))
        source = self.spec.source
        benchmark = source.benchmark if isinstance(source, BenchmarkJobSource) else None
        self.heldout = set(benchmark.heldout) if benchmark is not None else set()
        self.threshold = _success_threshold(workspace, record.source)
        self.tasks = {item.content_hash: item for item in self.spec.tasks}
        names = {item.content_hash: item.name for item in self.spec.agents}
        names.update({item.agent.content_hash: item.name for item in self.spec.agents})
        self.agent_names = names

    def task(self, trial: TrialResult) -> str:
        task = self.tasks.get(trial.receipt.task_digest)
        return task.task_id if task is not None else trial.receipt.task_digest

    def agent(self, trial: TrialResult) -> str:
        return self.agent_names.get(trial.receipt.agent_digest, trial.receipt.agent_digest)

    def finished(self) -> list[TrialResult]:
        return [item for item in self.result.trials if item.status == "succeeded"]

    def metrics(self) -> dict[str, MetricSpec]:
        specs: dict[str, MetricSpec] = {}
        for task in self.spec.tasks:
            for binding in task.verifiers:
                for metric in getattr(binding.verifier, "metrics", ()) or ():
                    specs.setdefault(metric.name, metric)
        return specs


def build_report(
    workspace: Workspace,
    job_id: str,
    *,
    compare: str | None = None,
    findings: bool = True,
) -> JobReport:
    """Compute a Job's report.

    Returns:
        The report, without a summary.
    """
    job = _Loaded(workspace, job_id)
    facts = _Facts()
    performance = [
        _performance(job, agent, trials, facts)
        for agent, trials in _by_agent(job, job.finished()).items()
    ]
    failures = _failures(job, facts, include=findings)
    changes = None
    if compare is not None:
        changes = _changes(job, _Loaded(workspace, compare), facts)
    trust = _trust(workspace, job, facts)
    return JobReport(
        job_id=job_id,
        compare_job_id=compare,
        generated_at=datetime.now(timezone.utc),
        performance=performance,
        failures=failures,
        changes=changes,
        trust=trust,
        facts=tuple(facts.items),
    )


def _by_agent(job: _Loaded, trials: Iterable[TrialResult]) -> dict[str, list[TrialResult]]:
    grouped: dict[str, list[TrialResult]] = defaultdict(list)
    for item in trials:
        grouped[job.agent(item)].append(item)
    return dict(grouped)


def _performance(
    job: _Loaded, agent: str, trials: list[TrialResult], facts: _Facts
) -> dict[str, Any]:
    ids = [item.receipt.trial_id for item in trials]
    judged = [item for item in trials if item.passed is not None]
    passed = [item.receipt.trial_id for item in judged if item.passed]
    succeeded = [
        item.receipt.trial_id
        for item in trials
        if item.score is not None and item.score >= job.threshold
    ]
    split = {
        "dev": [item for item in trials if job.task(item) not in job.heldout],
        "heldout": [item for item in trials if job.task(item) in job.heldout],
    }
    row: dict[str, Any] = {
        "agent": agent,
        "trials": facts.add(f"{agent}: Trials", len(trials), str(len(trials)), ids),
        "pass_rate": facts.rate(
            f"{agent}: pass rate", passed, [item.receipt.trial_id for item in judged]
        ),
        "success_rate": facts.rate(f"{agent}: success rate", succeeded, ids),
        "score": _interval(
            facts,
            f"{agent}: mean score",
            _grouped(job, trials, lambda item: item.score),
            ids,
            seed_for(job.job_id, agent, "score"),
        ),
        "splits": {
            name: facts.rate(
                f"{agent}: pass rate on {name} Tasks",
                [item.receipt.trial_id for item in members if item.passed],
                [item.receipt.trial_id for item in members if item.passed is not None],
            )
            for name, members in split.items()
            if members
        },
        "metrics": [],
    }
    for name, spec in sorted(job.metrics().items()):
        values = _grouped(job, trials, lambda item, key=name: item.metrics.get(key))
        if not values:
            continue
        contributing = [
            item.receipt.trial_id for item in trials if item.metrics.get(name) is not None
        ]
        entry: dict[str, Any] = {
            "name": name,
            "kind": spec.kind,
            "unit": spec.unit,
            "gate": bool(spec.gate),
            "applicable": facts.add(
                f"{agent}: Trials where {name} applies",
                len(contributing),
                str(len(contributing)),
                contributing,
            ),
            "mean": _interval(
                facts, f"{agent}: {name}", values, contributing, seed_for(job.job_id, agent, name)
            ),
        }
        if spec.gate:
            hits = [item.receipt.trial_id for item in trials if item.gates.get(name) is True]
            entry["gate_pass_rate"] = facts.rate(f"{agent}: gate {name} passed", hits, contributing)
        row["metrics"].append(entry)
    return row


def _grouped(job: _Loaded, trials: Iterable[TrialResult], read: Any) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in trials:
        value = read(item)
        if value is not None:
            grouped[job.task(item)].append(float(value))
    return dict(grouped)


def _interval(
    facts: _Facts, label: str, values: Mapping[str, list[float]], trials: Sequence[str], seed: int
) -> dict[str, str] | None:
    interval = clustered_bootstrap([(1.0, items) for items in values.values()], seed=seed)
    if interval is None:
        return None
    return {
        "estimate": facts.add(label, interval.estimate, _number(interval.estimate), trials),
        "interval": facts.add(
            f"{label}, 95% interval",
            None,
            f"{_number(interval.low)} to {_number(interval.high)}",
            trials,
        ),
    }


def _failures(job: _Loaded, facts: _Facts, *, include: bool) -> dict[str, Any] | None:
    record = load_findings(job.directory)
    if record is None:
        return None
    rows = []
    for row in breakdown(record):
        rows.append(
            {
                "cause": row.cause,
                "count": facts.add(
                    f"failed Trials caused by {row.cause}",
                    row.findings,
                    f"{row.findings} of {record.failed}",
                    row.trial_ids,
                ),
                "confirmed": facts.add(
                    f"confirmed Findings for {row.cause}",
                    row.confirmed,
                    str(row.confirmed),
                    row.trial_ids,
                ),
            }
        )
    failed_ids = [item.trial_id for item in JobEvidence(job.root, job.job_id).failed()]
    return {
        "failed": facts.add("failed dev Trials", record.failed, str(record.failed), failed_ids),
        "inspected_at": record.inspected_at.isoformat(),
        "depth": record.depth,
        "breakdown": rows,
        "findings": [
            {
                "finding_id": item.finding_id,
                "trial_id": item.trial_id,
                "task": item.task,
                "cause": item.cause,
                "status": item.status,
                "critical_step": item.critical_step,
                "summary": item.summary,
                "evidence": list(item.evidence),
                "forks": [test.test_id for test in item.forks],
            }
            for item in record.findings
        ]
        if include
        else [],
    }


MEASURES = {"pass_rate": "pass rate", "success_rate": "success rate"}
"""What a comparison is on: never one word for the other."""


def _changes(job: _Loaded, other: _Loaded, facts: _Facts) -> dict[str, Any]:
    splits: dict[str, Any] = {}
    for name in ("dev", "heldout"):
        measures: dict[str, Any] = {}
        for measure, words in MEASURES.items():
            new = _outcomes(job, name, measure)
            old = _outcomes(other, name, measure)
            if not new or not old:
                continue
            trials = [
                trial for grouped in (new, old) for _, ids in grouped.values() for trial in ids
            ]
            comparison = paired_bootstrap(
                {key: values for key, (values, _) in new.items()},
                {key: values for key, (values, _) in old.items()},
                metric=measure,
                seed=seed_for(job.job_id, other.job_id, name, measure),
            )
            entry: dict[str, Any] = {
                "verdict": comparison.verdict,
                "shared_tasks": facts.add(
                    f"Tasks both Jobs ran ({name}, {words})",
                    comparison.shared_tasks,
                    str(comparison.shared_tasks),
                    trials,
                ),
                "new": _rate_of(facts, f"{words} of {job.job_id} ({name})", new),
                "old": _rate_of(facts, f"{words} of {other.job_id} ({name})", old),
            }
            if comparison.delta is not None:
                entry["delta"] = facts.add(
                    f"change in {words} ({name})",
                    comparison.delta,
                    f"{comparison.delta:+.0%}",
                    trials,
                )
            if comparison.low is not None and comparison.high is not None:
                entry["interval"] = facts.add(
                    f"change in {words} ({name}), 95% interval",
                    None,
                    f"{comparison.low:+.0%} to {comparison.high:+.0%}",
                    trials,
                )
            measures[measure] = entry
        if measures:
            splits[name] = measures
    return {
        "new": job.job_id,
        "old": other.job_id,
        "new_agents": sorted({job.agent(item) for item in job.result.trials}),
        "old_agents": sorted({other.agent(item) for item in other.result.trials}),
        "splits": splits,
    }


def _outcomes(job: _Loaded, split: str, measure: str) -> dict[str, tuple[list[float], list[str]]]:
    """Each Task's outcomes on a split: passed, for judged Trials, or reached the threshold.

    Returns:
        Outcome values and Trial ids, by Task.
    """
    grouped: dict[str, tuple[list[float], list[str]]] = {}
    for item in job.finished():
        task = job.task(item)
        if (task in job.heldout) != (split == "heldout"):
            continue
        if measure == "pass_rate":
            if item.passed is None:
                continue
            value = float(item.passed)
        else:
            value = float(item.score is not None and item.score >= job.threshold)
        values, ids = grouped.setdefault(task, ([], []))
        values.append(value)
        ids.append(item.receipt.trial_id)
    return grouped


def _rate_of(
    facts: _Facts, label: str, grouped: Mapping[str, tuple[list[float], list[str]]]
) -> str:
    values = [value for items, _ in grouped.values() for value in items]
    ids = [trial for _, trials in grouped.values() for trial in trials]
    hits = sum(1 for value in values if value)
    rate = hits / len(values)
    return facts.add(label, rate, f"{rate:.0%} ({hits} of {len(values)})", ids)


def _trust(workspace: Workspace, job: _Loaded, facts: _Facts) -> dict[str, Any]:
    tiers: dict[str, list[str]] = defaultdict(list)
    for item in job.result.trials:
        tier = item.trust.tier if item.trust is not None else "unknown"
        tiers[tier].append(item.receipt.trial_id)
    flagged = [item.receipt.trial_id for item in job.result.trials if item.integrity]
    codes = Counter(finding.code for item in job.result.trials for finding in item.integrity)
    tasks = sorted({task.task_id for task in job.spec.tasks})
    checks = saved_checks(workspace, tasks)
    checked = [name for name, check in checks.items() if check is not None]
    clean = [name for name in checked if not checks[name].problems]  # type: ignore[union-attr]
    return {
        "tiers": {
            tier: facts.add(f"Trials at trust tier {tier}", len(ids), str(len(ids)), ids)
            for tier, ids in sorted(tiers.items())
        },
        "integrity": {
            "flagged": facts.add(
                "Trials with an integrity finding", len(flagged), str(len(flagged)), flagged
            ),
            "codes": dict(sorted(codes.items())),
        },
        "validation": {
            "tasks": len(tasks),
            "checked": facts.add(
                "Tasks with a saved check", len(checked), f"{len(checked)} of {len(tasks)}", []
            ),
            "clean": facts.add(
                "checked Tasks with no problems", len(clean), f"{len(clean)} of {len(checked)}", []
            ),
            "problems": {
                name: list(checks[name].problems)  # type: ignore[union-attr]
                for name in checked
                if name not in clean
            },
        },
    }


def validate_summary(text: str, facts: Sequence[Fact]) -> list[str]:
    """Why a summary is rejected: it names an unknown fact, or writes a number itself.

    Returns:
        One line per problem; empty when the summary is accepted.

    Examples:
        >>> facts = [Fact(fact_id="N1", label="pass rate", value=0.5, display="50% (1 of 2)")]
        >>> validate_summary("Half passed: {N1}.", facts)
        []
        >>> validate_summary("It passed 3 times; see {N9}.", facts)
        ['it refers to N9, which is not a computed fact', "it writes a number itself: '3'"]
    """
    known = {item.fact_id for item in facts}
    problems = [
        f"it refers to {name}, which is not a computed fact"
        for name in dict.fromkeys(_PLACEHOLDER.findall(text))
        if name not in known
    ]
    rest = _PLACEHOLDER.sub("", text)
    numbers = re.findall(r"[0-9][0-9.,%]*", rest)
    if numbers:
        problems.append(
            "it writes a number itself: " + ", ".join(repr(item) for item in dict.fromkeys(numbers))
        )
    return problems


def render_summary(text: str, facts: Sequence[Fact]) -> str:
    """A validated summary with each fact id replaced by its value.

    Returns:
        The summary as a person reads it.
    """
    values = {item.fact_id: item.display for item in facts}
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], text)


def write_summary(
    report: JobReport,
    environ: Mapping[str, str],
    *,
    model: str = SUMMARY_MODEL,
    attempts: int = 2,
) -> JobReport:
    """Ask a model for a summary that refers only to facts, and keep it if it validates.

    Returns:
        The report with a summary, or with the reasons the last one was rejected.
    """
    base = (environ.get("PLURAL_GATEWAY_URL") or "").rstrip("/")
    key = environ.get("PLURAL_API_KEY") or ""
    if not base or not key:
        return report.model_copy(
            update={"summary_problems": ("no model gateway is configured, so no summary",)}
        )
    facts = report.facts
    outline = report.model_dump(mode="json", exclude={"facts", "summary", "summary_problems"})
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You summarize an AI agent evaluation report for an engineer, in three to five "
                "sentences: how the agent performs, why it fails, what changed, and how far "
                "the numbers can be trusted. Never write a number or a digit yourself. Every "
                "number must be a fact id in braces, such as {N3}, which is replaced by the "
                "computed value. Use only the fact ids listed, and name what each one measures "
                "next to it, as in 'held-out pass rate rose to {N12} from {N13}'. Cite the "
                "few facts that matter most, never a list of them."
            ),
        },
        {
            "role": "user",
            "content": "Facts:\n"
            + "\n".join(f"{item.fact_id}: {item.label}" for item in facts)
            + "\n\nReport outline (values are fact ids):\n"
            + json.dumps(outline, indent=1)[:12000],
        },
    ]
    problems: list[str] = []
    for _ in range(max(1, attempts)):
        text = _complete(base, key, model, messages)
        problems = validate_summary(text, facts)
        if not problems:
            return report.model_copy(
                update={"summary": render_summary(text, facts), "summary_problems": ()}
            )
        messages += [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": "Rejected: " + "; ".join(problems) + ". Write it again.",
            },
        ]
    return report.model_copy(update={"summary": None, "summary_problems": tuple(problems)})


def _complete(base: str, key: str, model: str, messages: list[dict[str, str]]) -> str:
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": model, "messages": messages}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ProjectError(f"The gateway refused the summary request: {detail}") from None
    choices = payload.get("choices") or [{}]
    return str((choices[0].get("message") or {}).get("content") or "").strip()


def render_markdown(report: JobReport) -> str:
    """The report as ``report.md``.

    Returns:
        Markdown, with every number from a fact and a table of the facts at the end.
    """
    values = {item.fact_id: item.display for item in report.facts}

    def v(fact_id: str | None) -> str:
        return values.get(fact_id or "", "n/a")

    lines = [f"# Job {report.job_id}", ""]
    if report.summary:
        lines += ["## Summary", "", report.summary, ""]
    elif report.summary_problems:
        lines += ["## Summary", "", "No summary: " + "; ".join(report.summary_problems) + ".", ""]
    lines += ["## How the Agent performs", ""]
    for row in report.performance:
        score = row["score"] or {}
        lines += [
            f"### {row['agent']}",
            "",
            f"- Trials: {v(row['trials'])}",
            f"- Pass rate: {v(row['pass_rate'])}",
            f"- Success rate: {v(row['success_rate'])}",
            f"- Mean score: {v(score.get('estimate'))} (95% {v(score.get('interval'))})",
            *[f"- Pass rate on {name} Tasks: {v(fact)}" for name, fact in row["splits"].items()],
            "",
            "| Metric | Kind | Applies | Mean | 95% interval | Gate passed |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for metric in row["metrics"]:
            mean = metric["mean"] or {}
            lines.append(
                f"| {metric['name']} | {metric['kind']} | {v(metric['applicable'])} | "
                f"{v(mean.get('estimate'))} | {v(mean.get('interval'))} | "
                f"{v(metric.get('gate_pass_rate')) if metric['gate'] else ''} |"
            )
        lines.append("")
    lines += ["## Why it fails", ""]
    failures = report.failures
    if failures is None:
        lines += ["Not inspected yet. Next: `plural job inspect " + report.job_id + "`.", ""]
    else:
        lines += [
            f"Failed dev Trials: {v(failures['failed'])} (inspected at {failures['depth']} depth).",
            "",
            "| Cause | Failed Trials | Confirmed |",
            "| --- | --- | --- |",
            *[
                f"| {row['cause']} | {v(row['count'])} | {v(row['confirmed'])} |"
                for row in failures["breakdown"]
            ],
            "",
        ]
        for item in failures["findings"]:
            lines += [
                f"- **{item['finding_id']}** {item['cause']}, {item['status']} (Trial "
                f"{item['trial_id']}, Task {item['task']}, "
                + (
                    "no critical step"
                    if item["critical_step"] is None
                    else f"step {item['critical_step']}"
                )
                + "): "
                f"{_escape(item['summary'])}",
            ]
        if failures["findings"]:
            lines.append("")
    lines += ["## What changed", ""]
    changes = report.changes
    if changes is None:
        lines += ["No comparison. Add `--compare OTHER_JOB`.", ""]
    else:
        lines += [
            f"Job {changes['new']} ({', '.join(changes['new_agents'])}) against "
            f"{changes['old']} ({', '.join(changes['old_agents'])}):",
            "",
        ]
        for name, measures in changes["splits"].items():
            for measure, entry in measures.items():
                lines.append(
                    f"- {name} Tasks, {MEASURES[measure]}: "
                    f"**{entry['verdict'].replace('_', ' ')}**, "
                    f"{v(entry['new'])} against {v(entry['old'])}, "
                    f"change {v(entry.get('delta'))} (95% {v(entry.get('interval'))}), "
                    f"over {v(entry['shared_tasks'])} shared Tasks"
                )
        if not changes["splits"]:
            lines.append("- The two Jobs share no Tasks.")
        lines.append("")
    trust = report.trust
    lines += [
        "## Why the numbers can be trusted",
        "",
        "- Trust tiers: "
        + (", ".join(f"{tier} {v(fact)}" for tier, fact in trust["tiers"].items()) or "none"),
        f"- Integrity: {v(trust['integrity']['flagged'])} Trials flagged"
        + (
            " (" + ", ".join(trust["integrity"]["codes"]) + ")"
            if trust["integrity"]["codes"]
            else ""
        ),
        f"- Task checks: {v(trust['validation']['checked'])} checked, "
        f"{v(trust['validation']['clean'])} clean",
        *[
            f"  - {name}: {_escape('; '.join(problems))}"
            for name, problems in trust["validation"]["problems"].items()
        ],
        "",
        "## Facts",
        "",
        "Every number above, and the Trials it was computed from.",
        "",
        "| Id | Fact | Value | Trials |",
        "| --- | --- | --- | --- |",
        *[
            f"| {item.fact_id} | {item.label} | {item.display} | {_trials(item.trial_ids)} |"
            for item in report.facts
        ],
        "",
    ]
    return "\n".join(lines)


def save_report(directory: Path, report: JobReport) -> Path:
    """Write ``report.md`` and ``report.json`` beside a Job's result.

    Returns:
        The Markdown file.
    """
    (directory / REPORT_DATA).write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    path = directory / REPORT_FILE
    path.write_text(render_markdown(report), "utf-8")
    return path


def _number(value: float) -> str:
    """A measured value as the report prints it.

    Returns:
        Thousands with separators, smaller values to three significant figures.

    Examples:
        >>> _number(3991.5), _number(0.66666), _number(1.0)
        ('3,992', '0.667', '1')
    """
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.3g}"


def _trials(ids: Sequence[str]) -> str:
    if len(ids) <= 4:
        return ", ".join(ids)
    return ", ".join(ids[:3]) + f" and {len(ids) - 3} more (report.json lists all)"


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


__all__ = [
    "REPORT_DATA",
    "REPORT_FILE",
    "SUMMARY_MODEL",
    "Fact",
    "JobReport",
    "build_report",
    "render_markdown",
    "render_summary",
    "save_report",
    "validate_summary",
    "write_summary",
]
