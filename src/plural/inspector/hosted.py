"""Upload a local Job's inspection and report to the hosted Job it was recorded as.

Hosted Trials have their own ids, so every local Trial id is translated first,
matched on Task, Agent definition hash, and attempt, so the hosted page links
each Finding and each number to a hosted Trial.
"""

from __future__ import annotations

import json
from typing import Any

from plural.inspector.findings import InspectionRecord
from plural.inspector.report import JobReport
from plural.project.resources import Workspace
from plural.project.runs import RUN_RECORD, local_job_spec
from plural.studio import Studio


def hosted_job_id(workspace: Workspace, job_id: str) -> str | None:
    """The hosted Job a local Job was recorded as, or ``None``.

    Returns:
        The hosted Job id.
    """
    path = workspace.project.jobs_dir / job_id / RUN_RECORD
    if not path.is_file():
        return None
    value = json.loads(path.read_text("utf-8")).get("hosted_job_id")
    return str(value) if value else None


def hosted_trial_ids(
    workspace: Workspace, studio: Studio, job_id: str, hosted: str
) -> dict[str, str]:
    """Each local Trial id of a recorded Job, mapped to its hosted Trial id.

    Returns:
        Hosted id by local id, for the Trials the hosted Job holds.
    """
    spec = local_job_spec(workspace, job_id)
    tasks = {item.content_hash: item.task_id for item in spec.tasks}
    agents = {item.name: item.agent.content_hash for item in spec.agents}
    remote: dict[tuple[str, str, int], str] = {}
    for item in studio.jobs.trials(hosted):
        pins = _object(item.get("pins"))
        task = _object(pins.get("task"))
        key = (str(task.get("name")), str(pins.get("agent")), int(item.get("attempt") or 0))
        remote[key] = str(item["id"])
    found: dict[str, str] = {}
    for trial in spec.plan().trials:
        key = (
            tasks.get(trial.task_digest, ""),
            agents.get(trial.agent_name, ""),
            trial.attempt,
        )
        if key in remote:
            found[trial.trial_id] = remote[key]
    return found


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _translate(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        return ids.get(value, value)
    if isinstance(value, list):
        return [_translate(item, ids) for item in value]
    if isinstance(value, dict):
        return {key: _translate(item, ids) for key, item in value.items()}
    return value


def upload_inspection(workspace: Workspace, studio: Studio, record: InspectionRecord) -> str | None:
    """Replace the hosted Job's inspection, when the Job was recorded.

    Returns:
        The hosted Job id, or ``None`` when the Job isn't recorded.
    """
    hosted = hosted_job_id(workspace, record.job_id)
    if hosted is None:
        return None
    ids = hosted_trial_ids(workspace, studio, record.job_id, hosted)
    payload = _translate(record.model_dump(mode="json"), ids)
    payload["job_id"] = hosted
    studio.jobs.put_inspection(hosted, payload)
    return hosted


def upload_report(workspace: Workspace, studio: Studio, report: JobReport) -> str | None:
    """Replace the hosted Job's report, when the Job was recorded.

    Returns:
        The hosted Job id, or ``None`` when the Job isn't recorded.
    """
    hosted = hosted_job_id(workspace, report.job_id)
    if hosted is None:
        return None
    ids = hosted_trial_ids(workspace, studio, report.job_id, hosted)
    if report.compare_job_id is not None:
        other = hosted_job_id(workspace, report.compare_job_id)
        if other is not None:
            ids.update(hosted_trial_ids(workspace, studio, report.compare_job_id, other))
            ids[report.compare_job_id] = other
    ids[report.job_id] = hosted
    payload = _translate(report.model_dump(mode="json"), ids)
    studio.jobs.put_report(hosted, payload)
    return hosted


__all__ = ["hosted_job_id", "hosted_trial_ids", "upload_inspection", "upload_report"]
