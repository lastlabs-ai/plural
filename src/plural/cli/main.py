"""The ``plural`` command: one entry point composing each command group."""

from __future__ import annotations

import typer

from plural.cli.auth_commands import auth_app
from plural.cli.models_commands import models_app
from plural.cli.project_commands import project_app
from plural.cli.resource_commands import resource_app
from plural.cli.run_commands import job_app, review_app, run, trial_app
from plural.cli.session import session_app
from plural.project import KINDS

app = typer.Typer(
    name="plural",
    help=(
        "Build, push, and run Plural projects.\n\n"
        "Start with `plural project init <name>`, add resources with "
        "`plural <env|task|verifier|harness|agent|benchmark> init <name>`, and run them "
        "with `plural run --task <name> --model <model>`."
    ),
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(auth_app, name="auth")
app.add_typer(project_app, name="project")
for _kind in KINDS:
    app.add_typer(resource_app(_kind), name=_kind.cli)
app.command("run")(run)
app.add_typer(job_app, name="job")
app.add_typer(trial_app, name="trial")
app.add_typer(review_app, name="review")
app.add_typer(models_app, name="models")
app.add_typer(session_app, name="session")


def main() -> None:
    """Run the CLI."""
    app()


__all__ = ["app", "main"]
