"""``plural app add|list|remove``: the Apps in an Environment.

An App is one system the Agent works with. ``add`` connects an MCP server, an
OpenAPI document, recorded traces, or Plural's files server; ``remove`` takes
an App's entry out of ``environment.yaml`` and leaves every file in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml

from plural.cli.common import JSON_OPTION, emit, handled, relative, rows, success, workspace
from plural.cli.generate_commands import app_add
from plural.project import ProjectError, ResourceRef
from plural.project.layout import ENVIRONMENT

app_app = typer.Typer(
    help=(
        "Add, list, and remove the Apps in an Environment.\n\n"
        "An App is one system the Agent works with: an MCP server, an HTTP API, recorded "
        "traces, Plural's files server, or a Python App class."
    ),
    no_args_is_help=True,
)
app_app.command("add")(app_add)

ENV_HELP = "The Environment."
SOURCES = ("python", "mcp", "openapi", "replay")


def _manifest(name: str) -> tuple[Path, Path, dict[str, Any]]:
    space = workspace()
    directory = space.project.resource_dir(ResourceRef(ENVIRONMENT.name, name))
    path = directory / "environment.yaml"
    if not path.is_file():
        raise ProjectError(
            f"No Environment {name}. Create it with `plural env init {name}`, or add a "
            f"system to a new one with `plural app add {name} --mcp URL_OR_COMMAND`."
        )
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        shown = relative(path, space.project.root)
        raise ProjectError(f"{shown} is not valid YAML: {exc}") from None
    if not isinstance(payload, dict):
        raise ProjectError(f"{relative(path, space.project.root)} must be a mapping.")
    return space.project.root, path, payload


def _kind(entry: dict[str, Any]) -> str:
    return next((key for key in SOURCES if entry.get(key)), "?")


def _source(entry: dict[str, Any]) -> str:
    kind = _kind(entry)
    value = entry.get(kind)
    if isinstance(value, dict):
        for key in ("server", "url", "command", "spec", "recordings"):
            if value.get(key):
                item = value[key]
                return " ".join(map(str, item)) if isinstance(item, list) else str(item)
        return ""
    return str(value or "")


def _entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if payload.get("python"):
        items.append(
            {"name": None, "kind": "python", "source": str(payload["python"]), "field": "python"}
        )
    for index, entry in enumerate(payload.get("apps") or []):
        if isinstance(entry, dict):
            items.append(
                {
                    "name": entry.get("name"),
                    "kind": _kind(entry),
                    "source": _source(entry),
                    "field": f"apps.{index}",
                }
            )
    return items


@app_app.command("list")
@handled
def app_list(
    environment: str = typer.Argument(help=ENV_HELP),
    as_json: bool = JSON_OPTION,
) -> None:
    """List the Apps an Environment's environment.yaml declares.

    This reads the file only. `plural env validate ENV` loads each App and lists
    the actions the Agent is offered.
    """
    _root, _path, payload = _manifest(environment)
    items = _entries(payload)

    def text() -> None:
        if not items:
            typer.echo(
                f"Environment {environment} has no Apps. Add one with "
                f"`plural app add {environment} --mcp URL_OR_COMMAND`."
            )
            return
        rows(
            ((item["name"] or "-", item["kind"], item["source"]) for item in items),
            ("app", "kind", "source"),
        )
        if any(item["field"] == "python" for item in items):
            typer.echo(
                "python: names the Environment's own class: one Python App, or an "
                "Environment subclass over the Apps listed after it."
            )
        typer.echo(f"Run `plural env validate {environment}` to see each App's actions.")

    emit(items, as_json=as_json, text=text)


def _without_item(text: str, index: int) -> str | None:
    """``text`` with item ``index`` of the top-level ``apps:`` list cut out.

    Only lines are removed, so comments and formatting elsewhere stay as written.
    Removing the only item removes the ``apps:`` key with it.

    Returns:
        The new text, or ``None`` when the list is not laid out one item per block.
    """
    lines = text.splitlines(keepends=True)
    key = next(
        (n for n, line in enumerate(lines) if line.split("#", 1)[0].rstrip() == "apps:"), None
    )
    if key is None:
        return None
    starts: list[int] = []
    end = len(lines)
    indent: int | None = None
    for number in range(key + 1, len(lines)):
        line = lines[number]
        stripped = line.lstrip()
        if not stripped.strip() or stripped.startswith("#"):
            continue
        width = len(line) - len(stripped)
        if stripped.startswith("- ") or stripped.rstrip() == "-":
            if indent is None:
                indent = width
            if width == indent:
                starts.append(number)
                continue
        if width == 0 or (indent is not None and width < indent):
            end = number
            break
    if index >= len(starts):
        return None
    stop = starts[index + 1] if index + 1 < len(starts) else end
    while stop > starts[index] + 1 and (
        not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith("#")
    ):
        stop -= 1
    first = key if len(starts) == 1 else starts[index]
    return "".join(lines[:first] + lines[stop:])


def _referenced_files(entry: dict[str, Any], directory: Path) -> list[Path]:
    settings = entry.get(_kind(entry))
    values = list(settings.values()) if isinstance(settings, dict) else [settings]
    found = []
    for value in values:
        if not isinstance(value, str):
            continue
        path = directory / value.partition(":")[0]
        if path.is_file() and path.resolve().is_relative_to(directory.resolve()):
            found.append(path)
    return found


@app_app.command("remove")
@handled
def app_remove(
    environment: str = typer.Argument(help=ENV_HELP),
    app: str = typer.Argument(help="The App to remove, by its name in environment.yaml."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Remove an App from an Environment (a local edit until you push).

    Only the App's entry under apps: in environment.yaml is removed. Files it
    used, such as a server, an OpenAPI document, or recordings, stay in place.
    A Python App class is yours to remove by hand.
    """
    root, path, payload = _manifest(environment)
    shown = relative(path, root)
    entries = [item for item in payload.get("apps") or [] if isinstance(item, dict)]
    index = next((n for n, item in enumerate(entries) if item.get("name") == app), None)
    if index is None:
        names = ", ".join(str(item.get("name")) for item in entries if item.get("name")) or "none"
        hint = (
            f" Its python: {payload['python']} class may be the App you mean; edit {shown} "
            "and that file yourself."
            if payload.get("python")
            else ""
        )
        raise ProjectError(
            f"Environment {environment} has no App named {app!r} (named Apps: {names}).{hint}"
        )
    entry = entries[index]
    if entry.get("python"):
        raise ProjectError(
            f"App {app} is a Python App ({entry['python']}). Remove its entry under apps: "
            f"in {shown} yourself, and its class if nothing else uses it."
        )
    if len(entries) == 1 and not payload.get("python"):
        raise ProjectError(
            f"App {app} is the only App in Environment {environment}, and an Environment "
            f"needs one. Add another with `plural app add {environment}` first, or delete "
            f"the Environment with `plural env delete {environment}`."
        )
    raw = payload.get("apps") or []
    if len(raw) != len(entries):
        raise ProjectError(f"apps: in {shown} has entries that are not mappings. Edit it yourself.")
    original = path.read_text(encoding="utf-8")
    edited = _without_item(original, index)
    remaining = [item for n, item in enumerate(entries) if n != index]
    expected = {key: value for key, value in payload.items() if key != "apps"}
    if remaining:
        expected["apps"] = remaining
    if edited is None or (yaml.safe_load(edited) or {}) != expected:
        raise ProjectError(
            f"{shown} lays out apps: in a way this command does not edit safely. "
            f"Remove the App named {app} from it yourself."
        )
    path.write_text(edited, encoding="utf-8")
    kept = [relative(item, root) for item in _referenced_files(entry, path.parent)]
    result = {"environment": environment, "app": app, "file": shown, "kept": kept}

    def text() -> None:
        success(f"Removed App {app} from Environment {environment} ({shown}).")
        if kept:
            typer.echo("Files it used are still there; delete them if nothing else needs them:")
            for item in kept:
                typer.echo(f"  {item}")
        typer.echo(f"Check what the Agent is offered now with `plural env validate {environment}`.")

    emit(result, as_json=as_json, text=text)


__all__ = ["app_app"]
