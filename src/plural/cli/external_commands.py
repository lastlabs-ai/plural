"""``plural external``: register an agent that runs elsewhere, and trace it to Plural.

Run these in the agent's own repository. ``init`` writes ``plural-agent.yaml``,
``register`` adds the Agent to Plural from it, and ``check`` confirms that the
config, the keys, and the service all work before a Job relies on them.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml

from plural.cli.common import JSON_OPTION, details, emit, handled, note, session, signed_in, success
from plural.errors import ConfigurationError
from plural.external.config import CONFIG_FILE, AgentConfig, render_template
from plural.project import ProjectError
from plural.studio import Studio

external_app = typer.Typer(
    help=(
        "Register an agent that runs as its own service, and trace its runs to Plural.\n\n"
        "In the agent's repository, `plural external init` writes plural-agent.yaml. Edit "
        "it, then `plural external register` adds the Agent to Plural, and `plural "
        "external check` confirms the keys and the service work. In the agent's code, "
        "`plural.external.Tracer` and the adapters for OpenTelemetry, LangChain, and the "
        "OpenAI Agents SDK trace each run."
    ),
    no_args_is_help=True,
)

CONFIG_OPTION = typer.Option(
    None, "--config", "-c", help=f"The config file. Defaults to ./{CONFIG_FILE}."
)


def _load(path: Path | None) -> AgentConfig:
    try:
        return AgentConfig.load(path)
    except ConfigurationError as exc:
        raise ProjectError(str(exc)) from None


def _studio(config: AgentConfig) -> Studio:
    if os.environ.get(config.plural.api_key):
        return config.studio()
    return signed_in(session()).studio(project=config.plural.project)


@external_app.command("init")
@handled
def init(
    name: str = typer.Argument(..., help="The Agent's name in Plural."),
    version: str = typer.Option("0.1.0", "--version", help="Your release label."),
    model: str = typer.Option("", "--model", help="The label runs report as their model."),
    url: str | None = typer.Option(
        None, "--url", help="Where Plural Jobs send episodes, over https."
    ),
    path: Path = typer.Option(Path(CONFIG_FILE), "--path", help="Where to write the file."),
    force: bool = typer.Option(False, "--force", help="Replace an existing file."),
) -> None:
    """Write a plural-agent.yaml with every field explained."""
    if path.exists() and not force:
        raise ProjectError(f"{path} exists. Pass --force to replace it.")
    text = render_template(name=name, version=version, model=model, url=url)
    path.write_text(text, encoding="utf-8")
    success(f"Wrote {path}.")
    config = AgentConfig.model_validate(yaml.safe_load(text))
    steps = [
        "Edit it: the capture section decides what leaves this service.",
        "Export PLURAL_API_KEY, a key for the project the traces go to, or set "
        "tracing.production to false to trace only Plural Jobs.",
    ]
    if url:
        steps += [
            "Make a signing key with `plural agent key`. Export it here as "
            f"PLURAL_SIGNING_KEY; the project that runs Jobs keeps it as "
            f"{config.agent.signing_key}.",
            "`plural external register`, then `plural external check`.",
        ]
    typer.echo("Next:")
    for number, step in enumerate(steps, start=1):
        typer.echo(f"  {number}. {step}")


@external_app.command("register")
@handled
def register(config_path: Path | None = CONFIG_OPTION, as_json: bool = JSON_OPTION) -> None:
    """Add the Agent to Plural, or a new revision when its url or version changed."""
    from plural.agents import Agent, ExternalAgent

    config = _load(config_path)
    agent = config.agent
    if not agent.url:
        raise ProjectError(
            "agent.url is not set. Registering is for Agents that Plural Jobs evaluate; "
            "tracing alone works without it."
        )
    if not agent.model:
        raise ProjectError("agent.model is not set: the label runs report as their model.")
    definition = Agent(
        name=agent.name,
        model=agent.model,
        external=ExternalAgent(
            url=agent.url,
            signing_key=agent.signing_key,
            version=agent.version,
            ca_bundle=agent.ca_bundle,
        ),
    )
    revision = _studio(config).agents.push(definition)
    payload = {
        "agent": agent.name,
        "agent_id": revision.get("agent_id"),
        "revision_id": revision.get("id"),
        "url": agent.url,
        "version": agent.version,
    }

    def text() -> None:
        success(f"Registered Agent {agent.name} ({agent.version}).")
        details((key, str(value)) for key, value in payload.items() if key != "agent")

    emit(payload, as_json=as_json, text=text)


@external_app.command("check")
@handled
def check(config_path: Path | None = CONFIG_OPTION, as_json: bool = JSON_OPTION) -> None:
    """Check the config, the API key, the Agent's registration, and a signed ping."""
    from plural.external.client import KEY_VARIABLE, ping
    from plural.studio import slugify

    config = _load(config_path)
    checks: list[dict[str, Any]] = [{"check": "config", "ok": True, "detail": "valid"}]
    tracing = config.tracing
    if (tracing.enabled and tracing.production) or config.agent.url:
        variable = config.plural.api_key
        try:
            found = _studio(config).agents.find(slugify(config.agent.name, fallback="agent"))
        except (ProjectError, ConfigurationError, httpx.HTTPError) as exc:
            checks.append({"check": "api key", "ok": False, "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001 - reported as a failed check
            checks.append({"check": "api key", "ok": False, "detail": f"{variable}: {exc}"})
        else:
            checks.append({"check": "api key", "ok": True, "detail": f"{variable} works"})
            checks.append(
                {
                    "check": "registered",
                    "ok": found is not None,
                    "detail": f"Agent {found['id']}"
                    if found
                    else "not yet; run `plural external register`",
                }
            )
    if config.agent.url:
        key = os.environ.get(KEY_VARIABLE) or os.environ.get(config.agent.signing_key, "")
        if not key:
            checks.append(
                {
                    "check": "signed ping",
                    "ok": False,
                    "detail": f"export {KEY_VARIABLE} first, the key from `plural agent key`",
                }
            )
        else:
            started = time.monotonic()
            try:
                status = ping(config.agent.url, key, ca_bundle=config.agent.ca_bundle)
            except (ValueError, httpx.HTTPError) as exc:
                checks.append({"check": "signed ping", "ok": False, "detail": str(exc)})
            else:
                elapsed = time.monotonic() - started
                checks.append(
                    {
                        "check": "signed ping",
                        "ok": 200 <= status < 300,
                        "detail": f"{status} in {elapsed:.2f}s",
                    }
                )
    ok = all(item["ok"] for item in checks)

    def text() -> None:
        for item in checks:
            if item["ok"]:
                success(f"{item['check']}: {item['detail']}")
            else:
                note(f"{item['check']}: {item['detail']}")

    emit({"ok": ok, "checks": checks}, as_json=as_json, text=text)
    if not ok:
        raise typer.Exit(1)


__all__ = ["external_app"]
