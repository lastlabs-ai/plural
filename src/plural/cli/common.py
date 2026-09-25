"""Shared CLI plumbing: errors, output, the current project, and hosted access.

Command handlers stay thin: they parse options, call :mod:`plural.project`
or :mod:`plural.auth`, and print the result with the helpers here.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, NoReturn, ParamSpec, TypeVar

import httpx
import typer
from pydantic import BaseModel, ValidationError

from plural.auth import AuthHTTPError, Session, resolve_session
from plural.errors import PluralError
from plural.project import Project, ProjectBinding, ProjectError, Workspace
from plural.studio import Studio

P = ParamSpec("P")
R = TypeVar("R")

JSON_OPTION = typer.Option(False, "--json", help="Print machine-readable JSON.")


def fail(message: str, problems: Iterable[str] = (), *, code: int = 1) -> NoReturn:
    """Print an error and exit."""
    typer.echo(f"Error: {message}", err=True)
    for problem in problems:
        typer.echo(f"  - {problem}", err=True)
    raise typer.Exit(code)


def handled(function: Callable[P, R]) -> Callable[P, R]:
    """Turn expected failures into a readable message and a nonzero exit."""

    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except ProjectError as exc:
            fail(exc.message, exc.problems)
        except AuthHTTPError as exc:
            fail(str(exc))
        except PluralError as exc:
            fail(str(exc))
        except ValidationError as exc:
            fail("invalid input", [error["msg"] for error in exc.errors()])
        except httpx.HTTPError as exc:
            fail(f"could not reach the hosted service: {exc}")

    return wrapper


def emit(payload: Any, *, as_json: bool, text: Callable[[], None] | None = None) -> None:
    """Print ``payload`` as JSON, or call ``text`` for human output."""
    if as_json or text is None:
        value = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        typer.echo(json.dumps(value, indent=2, sort_keys=True, default=str))
        return
    text()


def rows(items: Iterable[Iterable[Any]], header: Iterable[str]) -> None:
    """Print a left-aligned table."""
    table = [[str(cell) for cell in header], *([str(cell) for cell in row] for row in items)]
    widths = [max(len(row[index]) for row in table) for index in range(len(table[0]))]
    for row in table:
        typer.echo(
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        )


def success(message: str) -> None:
    """Print a one-line outcome, marked done."""
    typer.echo(typer.style("✓ ", fg="green", bold=True) + typer.style(message, bold=True))


def heading(message: str) -> None:
    """Print a bold section heading."""
    typer.echo(typer.style(message, bold=True))


def muted(message: str) -> str:
    """``message`` styled as secondary text."""
    return typer.style(message, dim=True)


def details(pairs: Iterable[tuple[str, str]]) -> None:
    """Print labeled values in an indented, aligned block."""
    items = list(pairs)
    width = max((len(label) for label, _ in items), default=0)
    for label, value in items:
        typer.echo(f"  {muted(label.ljust(width))}  {value}")


def note(message: str) -> None:
    """Print a caution the user should act on."""
    typer.echo(typer.style("! ", fg="yellow", bold=True) + message)


def workspace() -> Workspace:
    """The project containing the working directory.

    Raises:
        ProjectError: Outside a project.
    """
    return Workspace(Project.find())


def session() -> Session:
    """The effective hosted context."""
    return resolve_session()


def signed_in(current: Session) -> Session:
    """Require a credential.

    Raises:
        ProjectError: When no credential is available.
    """
    if current.token is None:
        raise ProjectError("You are not signed in. Run `plural auth login` or set PLURAL_API_KEY.")
    return current


def project_studio(space: Workspace, current: Session) -> tuple[Studio, ProjectBinding]:
    """Hosted access to the project this directory is bound to.

    The active scope must agree with the binding. Account scope may reach any
    project the credential can; a project scope must name this project.

    Raises:
        ProjectError: When the directory is unbound or the scope disagrees.
    """
    signed_in(current)
    binding = space.project.read_binding()
    name = space.project.name
    if binding is None:
        raise ProjectError(
            f"This directory is not registered with a hosted project. Run "
            f"`plural project init {name} --push` in {space.project.root}."
        )
    if binding.api_url.rstrip("/") != current.api_url.rstrip("/"):
        raise ProjectError(
            f"This directory is bound to {binding.api_url}, but you are signed in to "
            f"{current.api_url}. Set PLURAL_API_URL={binding.api_url} or sign in there."
        )
    if current.account_id and binding.account_id and current.account_id != binding.account_id:
        raise ProjectError(
            f"Your scope selects a different account than the one project "
            f"{binding.project_slug!r} belongs to. Run "
            f"`plural auth scope --project {binding.project_slug}` to switch, then retry."
        )
    if current.project and current.project not in {binding.project_id, binding.project_slug}:
        selected = current.project_slug or current.project
        raise ProjectError(
            f"Your scope selects project {selected!r}, but this directory is bound to "
            f"{binding.project_slug!r}. Run `plural auth scope --project "
            f"{binding.project_slug}` (or `plural auth scope .` for account scope), then retry."
        )
    studio = current.studio(project=binding.project_id)
    studio.account = binding.account_id or studio.account
    return studio, binding


def relative(path: Path, root: Path) -> str:
    """``path`` relative to ``root`` when inside it."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


__all__ = [
    "JSON_OPTION",
    "details",
    "emit",
    "fail",
    "handled",
    "heading",
    "muted",
    "note",
    "project_studio",
    "relative",
    "rows",
    "session",
    "signed_in",
    "success",
    "workspace",
]
