"""``plural models``: the models you may run."""

from __future__ import annotations

from typing import Any

import typer

from plural.catalog import ModelCatalog
from plural.cli.common import JSON_OPTION, emit, handled, rows, session

models_app = typer.Typer(help="List the models you may run.", no_args_is_help=True)


@models_app.command("list")
@handled
def list_models(
    provider: str | None = typer.Option(None, "--provider", help="Only this provider."),
    as_json: bool = JSON_OPTION,
) -> None:
    """List models your account may use.

    Signed in, the hosted service returns only the models your organization
    permits, and enforces that list when a run starts. Signed out, the bundled
    catalog is shown without any organization policy.
    """
    current = session()
    if current.token is not None:
        studio = current.studio(project=False)
        items: list[dict[str, Any]] = [dict(item) for item in studio.models.list(provider=provider)]
        source = "hosted"
    else:
        items = [
            {"id": spec.id, "name": spec.name, "context_length": spec.context_length}
            for spec in ModelCatalog().models()
            if provider is None or spec.id.split("/", 1)[0] == provider
        ]
        source = "catalog"

    def text() -> None:
        if not items:
            typer.echo("No models available" + (f" from {provider}." if provider else "."))
        else:
            rows(
                (
                    (item.get("id"), item.get("name") or "", item.get("context_length") or "")
                    for item in items
                ),
                ("model", "name", "context"),
            )
        if source == "catalog":
            typer.echo(
                "Signed out: showing the bundled catalog. Your organization may restrict it; "
                "run `plural auth login` to see what you may use."
            )

    emit({"source": source, "models": items}, as_json=as_json, text=text)
