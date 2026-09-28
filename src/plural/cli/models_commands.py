"""``plural models``: the models you may run."""

from __future__ import annotations

from typing import Any

import typer

from plural.catalog import ModelCatalog
from plural.cli.common import JSON_OPTION, emit, handled, rows, session

models_app = typer.Typer(help="List the models you may run.", no_args_is_help=True)


_SCOPE_NOTES = {
    "organization": (
        "Showing the models your organization offers. "
        "Run `plural models list --all` for the whole catalog."
    ),
    "catalog": "Your organization has not configured models yet; showing the whole catalog.",
}


@models_app.command("list")
@handled
def list_models(
    provider: str | None = typer.Option(None, "--provider", help="Only this provider."),
    include_all: bool = typer.Option(
        False,
        "--all",
        help="Every catalog model, not only the ones your organization offers.",
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """List models your account may use.

    Signed in to an organization, this lists the models the organization offers:
    its own endpoints and private models, and any it explicitly allows. `--all`
    lists the whole catalog and marks models the organization does not permit.
    Outside an organization, or signed out, it lists the whole catalog.
    """
    current = session()
    scope: str | None
    if current.token is not None:
        studio = current.studio(project=False)
        listing = studio.models.listing(provider=provider, include_all=include_all)
        items: list[dict[str, Any]] = [dict(item) for item in listing.models]
        source, scope = "hosted", listing.scope
    else:
        items = [
            {"id": spec.id, "name": spec.name, "context_length": spec.context_length}
            for spec in ModelCatalog().models()
            if provider is None or spec.id.split("/", 1)[0] == provider
        ]
        source, scope = "catalog", None

    def text() -> None:
        if not items:
            typer.echo("No models available" + (f" from {provider}." if provider else "."))
        else:
            rows(
                (
                    (
                        item.get("id"),
                        item.get("name") or "",
                        item.get("context_length") or "",
                        "" if item.get("permitted", True) else "not permitted",
                    )
                    for item in items
                ),
                ("model", "name", "context", "access"),
            )
        if source == "catalog":
            typer.echo(
                "Signed out: showing the bundled catalog. Your organization may restrict it; "
                "run `plural auth login` to see what you may use."
            )
        elif scope in _SCOPE_NOTES:
            typer.echo(_SCOPE_NOTES[scope])

    emit({"source": source, "scope": scope, "models": items}, as_json=as_json, text=text)
