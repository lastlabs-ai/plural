"""The ``plural`` command: one entry point composing each command group."""

from __future__ import annotations

import typer

from plural.apps.mcp import use_secret_source
from plural.cli.app_commands import app_app
from plural.cli.auth_commands import auth_app
from plural.cli.common import deprecated
from plural.cli.credential_commands import credential_app
from plural.cli.models_commands import models_app
from plural.cli.project_commands import project_app
from plural.cli.resource_commands import resource_app
from plural.cli.reward_commands import rewards_app, verifier_apply, verifier_try
from plural.cli.run_commands import job_app, review_app, run, trial_app
from plural.cli.runtime_commands import runtime_app
from plural.cli.secret_commands import project_secret_source, secret_app
from plural.cli.session import session_app
from plural.project import KINDS

app = typer.Typer(
    name="plural",
    help=(
        "Build, push, and run Plural projects.\n\n"
        "Start with `plural project init <name>`, add resources with "
        "`plural <env|task|verifier|harness|agent|benchmark> init <name>`, and run them "
        "with `plural run --task <name> --model <model>`.\n\n"
        "Objects:\n\n"
        "  Environment  `plural env init`: Apps, where they run, and limits.\n"
        "  App          `plural app add ENV`: one system the Agent works with.\n"
        "  Task         `plural task init`: instructions, an Environment, Verifiers.\n"
        "  Verifier     `plural verifier init`: decides what counts as good work.\n"
        "  Harness      `plural harness init`: the loop that drives the model.\n"
        "  Agent        `plural agent init --model`: model, instructions, Harness.\n"
        "  Benchmark    `plural benchmark init`: Tasks to rank Agents on.\n"
        "  Runtime      `plural runtime create`: where Environments run.\n"
        "  secret       `plural secret set`: a project value for Apps and Verifiers.\n"
        "  credential   `plural credential set`: your own value, carried by an Agent."
    ),
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(auth_app, name="auth")
app.add_typer(project_app, name="project")
app.add_typer(credential_app, name="credential")
app.add_typer(app_app, name="app")
for _kind in KINDS:
    _group = resource_app(_kind)
    if _kind.name == "verifier":
        _group.command("try")(verifier_try)
        _group.command("apply")(verifier_apply)
    app.add_typer(_group, name=_kind.cli)
app.command("run")(run)
app.add_typer(job_app, name="job")
app.add_typer(trial_app, name="trial")
app.add_typer(review_app, name="review")
app.add_typer(rewards_app, name="reward")
app.add_typer(models_app, name="model")
app.add_typer(runtime_app, name="runtime")
app.add_typer(secret_app, name="secret")
app.add_typer(session_app, name="session")


def _deprecated_rewards() -> None:
    deprecated("plural rewards", "plural reward")


def _deprecated_models() -> None:
    deprecated("plural models", "plural model")


app.add_typer(rewards_app, name="rewards", hidden=True, callback=_deprecated_rewards)
app.add_typer(models_app, name="models", hidden=True, callback=_deprecated_models)


def main() -> None:
    """Run the CLI."""
    use_secret_source(project_secret_source())
    app()


__all__ = ["app", "main"]
