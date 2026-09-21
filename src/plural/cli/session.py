"""Portable session snapshot commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml

from plural.cli.output import _client, _emit, _error
from plural.sessions import (
    SessionSnapshot,
    export_from_parts,
    export_from_trial,
    import_bundle,
)

session_app = typer.Typer(help="Export and redeploy portable agent sessions.")


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _error(f"cannot read {path}: {exc}")
    value = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        _error(f"{path} must contain a mapping")
    return value


@session_app.command("export")
def session_export(
    trial: str | None = typer.Option(None, "--trial", help="Hosted trial id."),
    agent: Path | None = typer.Option(None, "--agent", help="Agent YAML or JSON file."),
    environment: Path | None = typer.Option(
        None, "--environment", help="Environment YAML or JSON file."
    ),
    state: Path | None = typer.Option(None, "--state", help="State JSON file."),
    data: list[str] = typer.Option([], "--data", help="Data reference to record."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Directory bundled into data/."),
    name: str | None = typer.Option(None, "--name", help="Snapshot name."),
    out: Path = typer.Option(Path("sessions"), "--out", help="Bundle directory."),
) -> None:
    """Export a session bundle from a hosted trial or local files."""
    if trial:
        with _client() as client:
            snapshot = export_from_trial(client.studio, trial)
        if name:
            snapshot = snapshot.model_copy(update={"name": name})
        path = snapshot.save(out)
        _emit({"bundle": str(path), "trial_id": trial, "name": snapshot.name})
        return
    if agent is None or environment is None:
        _error("pass --trial or both --agent and --environment")
    snapshot = export_from_parts(
        name or agent.stem,
        agent=_load_mapping(agent),
        environment=_load_mapping(environment),
        state=_load_mapping(state) if state else None,
        data=data or None,
    )
    path = snapshot.save(out, data_dir=data_dir)
    _emit({"bundle": str(path), "name": snapshot.name})


@session_app.command("import")
def session_import(
    bundle: Path = typer.Argument(help="Session bundle directory."),
    dest: Path | None = typer.Option(None, "--dest", help="Parent directory for the new instance."),
) -> None:
    """Redeploy a bundle as a separate instance directory."""
    try:
        path = import_bundle(bundle, dest)
    except (OSError, ValueError) as exc:
        _error(str(exc))
    snapshot = SessionSnapshot.load(path)
    _emit(
        {
            "instance": str(path),
            "name": snapshot.name,
            "trial_id": snapshot.provenance.trial_id,
        }
    )
