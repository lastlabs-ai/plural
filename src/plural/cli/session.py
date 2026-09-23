"""Portable session snapshot commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml

from plural.cli.common import fail as _error
from plural.cli.common import handled, session, signed_in
from plural.sessions import (
    SessionSnapshot,
    export_from_parts,
    export_from_trial,
    import_bundle,
)

session_app = typer.Typer(help="Export and redeploy portable agent sessions.", no_args_is_help=True)


def _emit(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


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
@handled
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
        current = signed_in(session())
        if current.project is None:
            _error("Select the Trial's project first with `plural auth scope --project <name>`.")
        snapshot = export_from_trial(current.studio(), trial)
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
@handled
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
