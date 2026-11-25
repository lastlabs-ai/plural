"""``plural agent revise``: a confirmed Finding, or a winning fork, becomes a new Agent version.

For a model and Harness Agent, the Finding's remedy, or the one the fork
tested, is applied to
``agent.yaml`` (model, instructions, Harness config, ``tool_overrides``), the
minor version goes up, and ``CHANGELOG.md`` beside it notes the evidence. An
External Agent's code isn't Plural's to edit, so ``fixes/F1.md`` is written for
its team instead. Proving the fix is a Job: run both versions on the dev Tasks,
then the held-out Tasks, and compare.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from plural.agents.models import context_into_harness_config
from plural.inspector.causes import load_causes
from plural.inspector.evidence import JobEvidence
from plural.inspector.findings import (
    Finding,
    ForkTest,
    InspectionRecord,
    Remedy,
    load_findings,
)
from plural.project.layout import AGENT, ProjectError, ResourceRef
from plural.project.resources import Workspace

CHANGELOG = "CHANGELOG.md"
FIXES = "fixes"


@dataclass(frozen=True)
class Revision:
    """What ``plural agent revise`` did.

    Attributes:
        agent: The Agent's name.
        finding: The Finding it came from, or the fork's test id.
        job_id: The inspected Job the Finding belongs to.
        previous: The version before.
        version: The new version, or ``None`` for an External Agent.
        changed: What changed, a line each.
        path: The file written: ``agent.yaml``, or the fix note.
        changelog: The changelog entry, or the fix note's text.
        fork_job_id: The fork Job, when it came from a fork.
    """

    agent: str
    finding: str
    job_id: str
    previous: str
    version: str | None
    changed: tuple[str, ...]
    path: Path
    changelog: str
    fork_job_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """The revision as JSON.

        Returns:
            Its fields.
        """
        return {
            "agent": self.agent,
            "finding": self.finding,
            "job_id": self.job_id,
            "previous": self.previous,
            "version": self.version,
            "changed": list(self.changed),
            "path": str(self.path),
            "changelog": self.changelog,
            "fork_job_id": self.fork_job_id,
        }


def find_finding(
    workspace: Workspace, agent: str, finding_id: str, job_id: str | None = None
) -> tuple[InspectionRecord, Finding]:
    """A Finding by id: in the named Job, or the latest inspected Job of this Agent with one.

    Returns:
        The inspection and the Finding.

    Raises:
        ProjectError: When no inspected Job holds it.
    """
    jobs = workspace.project.jobs_dir
    folders = [jobs / job_id] if job_id else sorted(jobs.glob("*")) if jobs.is_dir() else []
    found: list[tuple[InspectionRecord, Finding]] = []
    for folder in folders:
        record = load_findings(folder)
        if record is None:
            continue
        for item in record.findings:
            if item.finding_id == finding_id and item.agent == agent:
                found.append((record, item))
    if not found:
        where = f"Job {job_id}" if job_id else "any inspected Job of this project"
        raise ProjectError(
            f"No Finding {finding_id} for Agent {agent} in {where}.\n"
            "Next: plural job inspect JOB, which lists each Finding with its id."
        )
    return max(found, key=lambda pair: pair[0].inspected_at)


def revise_agent(
    workspace: Workspace, agent: str, finding_id: str, *, job_id: str | None = None
) -> Revision:
    """Apply a confirmed Finding's remedy to an Agent, as a new version.

    Returns:
        What changed.

    Raises:
        ProjectError: When the Finding isn't confirmed, its cause isn't one an
            Agent change fixes, or it proposes no change.
    """
    record, finding = find_finding(workspace, agent, finding_id, job_id)
    causes = {item.name: item for item in load_causes(workspace.project.root)}
    cause = causes.get(finding.cause)
    if cause is None or not cause.agent:
        raise ProjectError(
            f"Finding {finding_id} blames {finding.cause}, which a change to the Agent doesn't "
            "fix. Fix the "
            + {"grader": "Verifier's code", "task": "Task or its answer key"}.get(
                finding.cause, finding.cause
            )
            + " instead."
        )
    manifest, text, payload = _manifest(workspace, agent)
    previous = str(payload.get("version") or "0.1.0")
    remedy = finding.remedy
    if payload.get("external") is not None:
        # Plural can't run an External Agent with a change, so no fork confirms one.
        return _external_fix(manifest.parent, agent, record, finding, previous)
    if finding.status != "confirmed":
        raise ProjectError(
            f"Finding {finding_id} is {finding.status}, not confirmed: no fork showed its "
            "remedy beat the controls. Inspect again with --depth deep, or fork it yourself "
            "with plural trial fork."
        )
    if remedy is None or remedy.empty:
        raise ProjectError(
            f"Finding {finding_id} proposes no change to the Agent to apply. Edit agent.yaml "
            "yourself, guided by its evidence."
        )
    changed = _apply(
        workspace,
        agent,
        remedy,
        job_id=record.job_id,
        trial_id=finding.trial_id,
        source=f"Finding {finding_id}",
    )
    version = str(yaml.safe_load(manifest.read_text("utf-8"))["version"])
    entry = _changelog_entry(version, record, finding, changed)
    _log(manifest.parent, agent, entry)
    return Revision(
        agent=agent,
        finding=finding_id,
        job_id=record.job_id,
        previous=previous,
        version=version,
        changed=changed,
        path=manifest,
        changelog=entry,
    )


def find_fork(
    workspace: Workspace, fork: str, job_id: str | None = None
) -> tuple[InspectionRecord, ForkTest]:
    """A fork the Inspector ran, by its fork Job id, or by test id within one inspected Job.

    Returns:
        The inspection and the fork.

    Raises:
        ProjectError: When no inspection ran it, or a test id names several forks.
    """
    jobs = workspace.project.jobs_dir
    folders = [jobs / job_id] if job_id else sorted(jobs.glob("*")) if jobs.is_dir() else []
    found: dict[str, tuple[InspectionRecord, ForkTest]] = {}
    for folder in folders:
        record = load_findings(folder)
        if record is None:
            continue
        cited = [
            test.model_copy(update={"trial_id": test.trial_id or item.trial_id})
            for item in record.findings
            for test in item.forks
        ]
        for test in (*record.forks, *cited):
            if fork in (test.job_id, test.test_id):
                found.setdefault(f"{record.job_id}:{test.job_id}", (record, test))
    if not found:
        where = f"Job {job_id}" if job_id else "any inspected Job of this project"
        raise ProjectError(
            f"No fork {fork} in {where}.\n"
            "Next: plural job inspect JOB, which lists each fork with its Job id."
        )
    if len(found) > 1:
        jobs_named = ", ".join(sorted(test.job_id for _, test in found.values()))
        raise ProjectError(f"{fork} names several forks: {jobs_named}. Pass the fork's Job id.")
    return next(iter(found.values()))


def revise_from_fork(
    workspace: Workspace, agent: str, fork: str, *, job_id: str | None = None
) -> Revision:
    """Apply the exact remedy a winning fork tested to an Agent, as a new version.

    Returns:
        What changed.

    Raises:
        ProjectError: When the fork didn't beat its controls, changed something
            other than the Agent, or forked another Agent's Trial.
    """
    record, test = find_fork(workspace, fork, job_id)
    label = f"fork {test.test_id} (Job {test.job_id})"
    if test.remedy is None or test.remedy.empty:
        raise ProjectError(
            f"The {label} changed what the Agent saw ({test.change or 'nothing'}), not the "
            "Agent, so there is nothing to ship. It explains a cause; fork the fix itself."
        )
    if not test.beat_controls:
        raise ProjectError(
            f"The {label} didn't beat its controls ({test.verdict.replace('_', ' ')}), so it "
            "proves nothing to ship. Fork again with --depth deep or a refined change."
        )
    forked: str | None = None
    if test.trial_id is not None:
        with suppress(ProjectError, KeyError, FileNotFoundError):
            trial = JobEvidence(workspace.project.root, record.job_id).trial(test.trial_id)
            forked = trial.agent.name
    if forked is not None and forked != agent:
        raise ProjectError(f"The {label} forked Trial {test.trial_id} of {forked}, not {agent}.")
    manifest, _, payload = _manifest(workspace, agent)
    if payload.get("external") is not None:
        raise ProjectError(
            f"{agent} is an External Agent, which Plural can't fork, so no fork tested it."
        )
    previous = str(payload.get("version") or "0.1.0")
    changed = _apply(
        workspace,
        agent,
        test.remedy,
        job_id=record.job_id,
        trial_id=test.trial_id,
        source=f"The {label}",
    )
    version = str(yaml.safe_load(manifest.read_text("utf-8"))["version"])
    day = datetime.now(timezone.utc).date().isoformat()
    entry = "\n".join(
        [
            f"## {version} ({day})",
            "",
            f"From {label} of Trial {test.trial_id or 'unknown'} in Job {record.job_id}, "
            "which beat its controls.",
            "",
            "Changed:",
            *[f"- {item}" for item in changed],
            "",
            "Evidence:",
            f"- {fork_line(test)}",
            "",
            "",
        ]
    )
    _log(manifest.parent, agent, entry)
    return Revision(
        agent=agent,
        finding=test.test_id,
        job_id=record.job_id,
        previous=previous,
        version=version,
        changed=changed,
        path=manifest,
        changelog=entry,
        fork_job_id=test.job_id,
    )


def _manifest(workspace: Workspace, agent: str) -> tuple[Path, str, dict[str, Any]]:
    ref = ResourceRef(AGENT.name, agent)
    if not workspace.project.has(ref):
        raise ProjectError(f"There is no Agent {agent} in this project.")
    manifest = workspace.project.manifest_path(ref)
    text = manifest.read_text("utf-8")
    return manifest, text, yaml.safe_load(text) or {}


def _apply(
    workspace: Workspace,
    agent: str,
    remedy: Remedy,
    *,
    job_id: str,
    trial_id: str | None,
    source: str,
) -> tuple[str, ...]:
    """Write a remedy into the Agent's manifest with the minor version bumped.

    Returns:
        What changed, a line each.

    Raises:
        ProjectError: When the remedy would undo a later change to the
            instructions, or the result doesn't load.
    """
    ref = ResourceRef(AGENT.name, agent)
    manifest, text, payload = _manifest(workspace, agent)
    previous = str(payload.get("version") or "0.1.0")
    if remedy.instructions is not None and trial_id is not None:
        ran = _instructions_ran(workspace, job_id, trial_id)
        if ran is not None and ran.strip() != str(payload.get("instructions") or "").strip():
            raise ProjectError(
                f"{agent}'s instructions changed since Trial {trial_id} ran, and "
                f"{source} replaces them whole, which would undo that change. "
                "Edit agent.yaml yourself, guided by its remedy, or inspect a Job of the "
                "current version."
            )
    if remedy.model is not None:
        payload["model"] = remedy.model
    if remedy.instructions is not None:
        payload["instructions"] = remedy.instructions
    if remedy.harness_config:
        current = context_into_harness_config(payload)
        payload.pop("context", None)
        config = {**dict(current.get("harness_config") or {}), **remedy.harness_config}
        if remedy.context is not None:
            config["context"] = remedy.context.model_dump(mode="json", exclude_none=True)
        payload["harness_config"] = config
    if remedy.tool_overrides:
        overrides = dict(payload.get("tool_overrides") or {})
        for name, item in remedy.tool_overrides.items():
            overrides[name] = {"hidden": True} if item.hidden else item.description
        payload["tool_overrides"] = overrides
    version = bump_minor(previous)
    payload["version"] = version
    manifest.write_text(_header(text) + yaml.safe_dump(payload, sort_keys=False, width=88), "utf-8")
    try:
        workspace.load(ref)
    except ProjectError:
        manifest.write_text(text, "utf-8")
        raise
    return tuple(remedy.describe())


def _log(folder: Path, agent: str, entry: str) -> None:
    changelog = folder / CHANGELOG
    existing = changelog.read_text("utf-8") if changelog.is_file() else f"# {agent}\n"
    head, _, rest = existing.partition("\n")
    changelog.write_text(f"{head}\n\n{entry}{rest.lstrip(chr(10))}".rstrip() + "\n", "utf-8")


def _instructions_ran(workspace: Workspace, job_id: str, trial_id: str) -> str | None:
    try:
        trial = JobEvidence(workspace.project.root, job_id).trial(trial_id)
    except (ProjectError, KeyError, FileNotFoundError):
        return None
    value = trial.agent_config().get("instructions")
    return value if isinstance(value, str) else None


def bump_minor(version: str) -> str:
    """The next minor version.

    Returns:
        ``MAJOR.(MINOR+1).0``.

    Examples:
        >>> bump_minor("1.0.0")
        '1.1.0'
        >>> bump_minor("1.4.2")
        '1.5.0'
    """
    parts = version.split("-")[0].split(".")
    major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    return f"{major}.{minor + 1}.0"


def fork_line(test: ForkTest) -> str:
    """A fork's outcome as one line, with its counts.

    Returns:
        The line.
    """
    candidate = round((test.candidate or 0.0) * test.candidates)
    control = round((test.control or 0.0) * test.controls)
    judged = f" on {', '.join(test.gates)}" if test.gates else ""
    return (
        f"fork {test.test_id} (Job {test.job_id}, after step {test.step}){judged}: "
        f"the change passed "
        f"{candidate} of {test.candidates}, the controls {control} of {test.controls}; "
        f"{test.verdict.replace('_', ' ')}"
    )


def _changelog_entry(
    version: str, record: InspectionRecord, finding: Finding, changed: tuple[str, ...]
) -> str:
    day = datetime.now(timezone.utc).date().isoformat()
    lines = [
        f"## {version} ({day})",
        "",
        f"From Finding {finding.finding_id} of Job {record.job_id}: Trial {finding.trial_id}, "
        f"Task {finding.task}, critical step {finding.critical_step}.",
        "",
        f"Cause ({finding.cause}, {finding.status}): {finding.summary}",
        "",
        "Changed:",
        *[f"- {item}" for item in changed],
        "",
        "Evidence:",
        *[f"- {item}" for item in finding.evidence],
        *[f"- {fork_line(test)}" for test in finding.forks],
        "",
        "",
    ]
    return "\n".join(lines)


def _external_fix(
    folder: Path, agent: str, record: InspectionRecord, finding: Finding, previous: str
) -> Revision:
    path = folder / FIXES / f"{finding.finding_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    remedy = finding.remedy.describe() if finding.remedy is not None else []
    lines = [
        f"# {finding.finding_id}: {finding.cause}",
        "",
        f"{agent} {previous} runs as its own service, so Plural can't change it. This is what "
        "the Inspector found, for the team that owns it.",
        "",
        f"- Job {record.job_id}, Trial {finding.trial_id}, Task {finding.task}",
        f"- Critical step: {finding.critical_step}",
        f"- Status: {finding.status}",
        "",
        f"Cause: {finding.summary}",
        "",
        "Evidence:",
        *[f"- {item}" for item in finding.evidence],
        *[f"- {fork_line(test)}" for test in finding.forks],
        "",
        "Suggested change:",
        *([f"- {item}" for item in remedy] or ["- none proposed"]),
        "",
        "After you ship it, give the service a new version label in agent.yaml and run the "
        "dev and held-out Tasks again to compare.",
        "",
    ]
    text = "\n".join(lines)
    path.write_text(text, "utf-8")
    return Revision(
        agent=agent,
        finding=finding.finding_id,
        job_id=record.job_id,
        previous=previous,
        version=None,
        changed=tuple(remedy),
        path=path,
        changelog=text,
    )


def _header(text: str) -> str:
    """The comment lines a manifest starts with, kept when it is rewritten.

    Returns:
        The leading comment block.
    """
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines) + "\n" if lines else ""


__all__ = [
    "CHANGELOG",
    "FIXES",
    "Revision",
    "bump_minor",
    "find_finding",
    "find_fork",
    "fork_line",
    "revise_agent",
    "revise_from_fork",
]
