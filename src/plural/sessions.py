"""Portable agent session snapshots.

A session snapshot captures everything needed to stop an agent instance and
redeploy it later as a separate instance: the agent revision, the environment
revision, the accumulated environment state, data references, and provenance
pointing back at the source job or trial.

Snapshots travel as plain directory bundles so they stay inspectable without
new formats to learn::

    <bundle>/
        agent.yaml
        environment.yaml
        state.json
        data/            # optional bundled files referenced by ``data``
        manifest.json

There is deliberately no backend table and no Studio surface yet: snapshots
move as files until a Sessions home exists.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from plural.common import FrozenModel

JsonObject = dict[str, Any]


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("plural")
    except Exception:
        return "0.0.0"


AGENT_FILENAME = "agent.yaml"
ENVIRONMENT_FILENAME = "environment.yaml"
STATE_FILENAME = "state.json"
DATA_DIRNAME = "data"
MANIFEST_FILENAME = "manifest.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionProvenance(FrozenModel):
    """Where a snapshot came from."""

    source: Literal["trial", "local"] = "local"
    job_id: str | None = None
    trial_id: str | None = None
    exported_at: datetime = Field(default_factory=_utcnow)
    package_version: str = Field(default_factory=_package_version)


class SessionSnapshot(FrozenModel):
    """A portable, redeployable agent instance."""

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    agent: JsonObject = Field(default_factory=dict)
    environment: JsonObject = Field(default_factory=dict)
    state: JsonObject = Field(default_factory=dict)
    data: list[str] = Field(default_factory=list)
    provenance: SessionProvenance = Field(default_factory=SessionProvenance)

    def save(self, directory: str | Path, *, data_dir: str | Path | None = None) -> Path:
        """Write the bundle to ``directory``.

        Returns:
            The bundle directory path.
        """
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        if data_dir is not None:
            shutil.copytree(data_dir, root / DATA_DIRNAME, dirs_exist_ok=True)
        (root / AGENT_FILENAME).write_text(
            yaml.safe_dump(self.agent, sort_keys=False), encoding="utf-8"
        )
        (root / ENVIRONMENT_FILENAME).write_text(
            yaml.safe_dump(self.environment, sort_keys=False), encoding="utf-8"
        )
        (root / STATE_FILENAME).write_text(
            json.dumps(self.state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "created_at": _utcnow().isoformat(),
            "provenance": self.provenance.model_dump(mode="json"),
            "data": self.data,
            "files": [AGENT_FILENAME, ENVIRONMENT_FILENAME, STATE_FILENAME],
        }
        data_dir = root / DATA_DIRNAME
        if self.data and data_dir.is_dir():
            manifest["files"].append(DATA_DIRNAME)
        (root / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return root

    @classmethod
    def load(cls, directory: str | Path) -> SessionSnapshot:
        """Read a bundle written by :meth:`save`.

        Returns:
            The loaded snapshot.
        """
        root = Path(directory)
        manifest = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        agent = yaml.safe_load((root / AGENT_FILENAME).read_text(encoding="utf-8"))
        environment = yaml.safe_load((root / ENVIRONMENT_FILENAME).read_text(encoding="utf-8"))
        state = json.loads((root / STATE_FILENAME).read_text(encoding="utf-8"))
        provenance = manifest.get("provenance", {})
        return cls(
            name=manifest.get("name", root.name),
            version=manifest.get("version", "0.1.0"),
            agent=agent or {},
            environment=environment or {},
            state=state or {},
            data=list(manifest.get("data", [])),
            provenance=SessionProvenance.model_validate(provenance),
        )


def export_from_parts(
    name: str,
    *,
    agent: JsonObject,
    environment: JsonObject,
    state: JsonObject | None = None,
    data: list[str] | None = None,
    version: str = "0.1.0",
) -> SessionSnapshot:
    """Build a snapshot from local definitions.

    Returns:
        The new snapshot (call :meth:`save` to write it).
    """
    return SessionSnapshot(
        name=name,
        version=version,
        agent=dict(agent),
        environment=dict(environment),
        state=dict(state or {}),
        data=list(data or []),
    )


def _find_revision(api: Any, revision_id: str, *, resource: str) -> tuple[JsonObject, JsonObject]:
    """Return ``(parent, revision)`` for a revision id by scanning parents."""
    parents = api.list()
    if isinstance(parents, dict):
        parents = parents.get("items", [])
    for parent in parents:
        revisions = api.revisions(parent["id"])
        if isinstance(revisions, dict):
            revisions = revisions.get("items", [])
        for revision in revisions:
            if revision.get("id") == revision_id:
                return parent, revision
    raise KeyError(f"{resource} revision {revision_id!r} not found in project")


def _latest_trace_state(studio: Any, trial_id: str) -> JsonObject:
    """Best-effort accumulated state from the newest trace.

    Returns:
        The trace state payload, or ``{}`` when unavailable.
    """
    try:
        traces = studio.traces.list(trial_id=trial_id)
    except Exception:
        return {}
    if isinstance(traces, dict):
        traces = traces.get("items", [])
    for trace in reversed(list(traces)):
        if not isinstance(trace, dict):
            continue
        for key in ("state", "final_state", "environment_state"):
            value = trace.get(key)
            if isinstance(value, dict) and value:
                return value
    return {}


def export_from_trial(studio: Any, trial_id: str) -> SessionSnapshot:
    """Snapshot the agent, environment, and latest state of a hosted trial.

    Returns:
        The new snapshot.
    """
    trial = studio.trials.get(trial_id)
    _, agent_revision = _find_revision(studio.agents, trial["agent_revision_id"], resource="agent")
    _, environment_revision = _find_revision(
        studio.environments, trial["environment_revision_id"], resource="environment"
    )
    data: list[str] = []
    try:
        _, task_revision = _find_revision(studio.tasks, trial["task_revision_id"], resource="task")
        definition = task_revision.get("definition", {})
        for resource in definition.get("resources", []) or []:
            path = resource.get("path") or resource.get("name")
            if path:
                data.append(str(path))
    except KeyError:
        pass
    agent_name = agent_revision.get("definition", {}).get("name") or trial.get("agent_name")
    return SessionSnapshot(
        name=f"{agent_name or 'agent'}-session",
        agent=agent_definition(agent_revision),
        environment=dict(environment_revision.get("definition", {})),
        state=_latest_trace_state(studio, trial_id),
        data=data,
        provenance=SessionProvenance(
            source="trial",
            job_id=trial.get("job_id"),
            trial_id=trial.get("id"),
        ),
    )


def agent_definition(agent_revision: JsonObject) -> JsonObject:
    """Extract the portable agent definition from a hosted revision.

    Returns:
        The agent definition mapping.
    """
    definition = agent_revision.get("definition", {})
    return dict(definition) if isinstance(definition, dict) else {}


def import_bundle(directory: str | Path, dest: str | Path | None = None) -> Path:
    """Redeploy a bundle as a separate instance directory.

    Copies the bundle to ``dest/<name>-<timestamp>`` (default: a ``sessions/``
    folder next to the bundle) and records the import in ``instance.json``.

    Returns:
        The new instance path.
    """
    source = Path(directory)
    snapshot = SessionSnapshot.load(source)
    base = Path(dest) if dest else source.parent / "sessions"
    stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
    target = base / f"{snapshot.name}-{stamp}"
    suffix = 1
    while target.exists():
        suffix += 1
        target = base / f"{snapshot.name}-{stamp}-{suffix}"
    if target.exists():
        raise FileExistsError(f"Session instance already exists: {target}")
    shutil.copytree(source, target)
    (target / "instance.json").write_text(
        json.dumps(
            {
                "instance": target.name,
                "name": snapshot.name,
                "version": snapshot.version,
                "imported_at": _utcnow().isoformat(),
                "source_bundle": str(source),
                "trial_id": snapshot.provenance.trial_id,
                "job_id": snapshot.provenance.job_id,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return target
