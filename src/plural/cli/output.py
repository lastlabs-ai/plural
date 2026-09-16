"""Shared CLI output, validation, and client helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, NoReturn

import typer
import yaml
from pydantic import BaseModel, ValidationError

from plural.cli.config import default_credential_store, resolve_context
from plural.client import Client
from plural.config import resolve_gateway_url
from plural.errors import PluralError


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def _emit(value: Any, fmt: str = "json") -> None:
    payload = _dump(value)
    if fmt == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif fmt == "yaml":
        typer.echo(yaml.safe_dump(payload, sort_keys=False).rstrip())
    else:
        typer.echo(str(payload))


def _error(message: str) -> NoReturn:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(2)


def _validated(loader: Any, path: Path) -> Any:
    try:
        return loader(path)
    except (OSError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        _error(str(exc))


def _client() -> Client:
    try:
        ctx = resolve_context(credentials=default_credential_store())
        if not ctx.api_key:
            raise PluralError("not authenticated; run `plural auth login` or set PLURAL_API_KEY")
        gateway = os.environ.get("PLURAL_GATEWAY_URL") or ctx.api_url
        return Client(
            api_key=ctx.api_key,
            base_url=resolve_gateway_url(gateway),
            project=ctx.project,
        )
    except (OSError, ValueError, PluralError) as exc:
        _error(str(exc))


def _emit_event(event: Any, *, json_events: bool) -> None:
    payload = _dump(event)
    if json_events:
        typer.echo(json.dumps(payload, separators=(",", ":"), default=str))
        return
    if not isinstance(payload, dict):
        typer.echo(str(payload))
        return
    nested = payload.get("payload")
    event_data = nested if isinstance(nested, dict) else {}
    sequence = payload.get("sequence", 0)
    status = payload.get("status") or payload.get("phase") or payload.get("kind") or ""
    trial_id = payload.get("trial_id") or event_data.get("trial_id")
    target = f" {trial_id}" if trial_id else ""
    message = payload.get("message") or ""
    try:
        sequence_text = f"{int(sequence):>5}"
    except (TypeError, ValueError):
        sequence_text = str(sequence)
    typer.echo(f"{sequence_text} {str(status):<16}{target} {message}".rstrip())
