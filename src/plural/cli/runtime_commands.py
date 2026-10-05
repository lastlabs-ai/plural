"""``plural runtime``: where Environments run.

A provider (Daytona, E2B, Modal, ...) is somewhere a sandbox can start. A
Runtime template is an account's approved configuration of one provider,
credentials included, that admins manage. A project Runtime is what an
Environment uses: created from a template, or from a provider directly when
the account's policy allows. `plural runtime use` copies a project Runtime's
settings into an Environment.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import typer

from plural.auth import Session
from plural.cli.common import (
    JSON_OPTION,
    details,
    emit,
    fail,
    handled,
    heading,
    muted,
    note,
    project_studio,
    rows,
    session,
    signed_in,
    success,
    workspace,
)
from plural.project import ProjectError, Workspace
from plural.project.layout import ENVIRONMENT
from plural.project.runtimes import use_runtime
from plural.sandbox.catalog import RUNTIME_PROVIDERS
from plural.studio import Studio

runtime_app = typer.Typer(
    help=(
        "Choose where Environments run.\n\n"
        "Start with `plural runtime providers` to see what each provider needs, then "
        "`plural runtime create` to add a Runtime to your project and "
        "`plural runtime use <runtime> <environment>` to run an Environment on it."
    ),
    no_args_is_help=True,
)
template_app = typer.Typer(
    help="Runtime templates: an account's approved provider configurations. Admins only.",
    no_args_is_help=True,
)
policy_app = typer.Typer(
    help="Which Runtimes an organization's members may create and run on.",
    invoke_without_command=True,
)
runtime_app.add_typer(template_app, name="template")
runtime_app.add_typer(policy_app, name="policy")

SET_OPTION = typer.Option(
    None,
    "--set",
    help="A setting as key=value, such as --set cpus=2. Repeat for more. "
    "See `plural runtime provider <id>` for every key.",
)
CREDENTIAL_OPTION = typer.Option(
    None,
    "--credential",
    help="A credential name, such as DAYTONA_API_KEY, to be prompted for without "
    "echoing; KEY=VALUE also works but leaves the value in your shell history.",
)
FROM_ENV_OPTION = typer.Option(
    False,
    "--credentials-from-env",
    help="Read every credential the provider needs from environment variables of the same name.",
)
NO_INPUT_OPTION = typer.Option(
    False, "--no-input", help="Never prompt; fail when something required is missing."
)
CATEGORY_LABELS = {
    "sandbox": "Cloud sandbox",
    "self_managed": "Your machine",
    "cloud": "Your cloud",
}


def _interactive(no_input: bool) -> bool:
    return not no_input and sys.stdin.isatty()


def _account_studio() -> Studio:
    """Hosted access to the account that owns the current project, or the scoped account."""
    current = signed_in(session())
    space = _workspace_or_none()
    if space is not None and space.project.read_binding() is not None:
        return project_studio(space, current)[0].with_project(None)
    return current.studio(project=False)


def _project_studio() -> tuple[Studio, str]:
    """Hosted access to the current project: the bound directory, else the scoped project.

    Raises:
        ProjectError: When no project is selected.
    """
    current = signed_in(session())
    space = _workspace_or_none()
    if space is not None and space.project.read_binding() is not None:
        studio, binding = project_studio(space, current)
        return studio, binding.project_slug
    if current.project:
        return current.studio(), current.project_slug or current.project
    raise ProjectError(
        "No project selected. Run this inside a project directory bound to a hosted "
        "project, or select one with `plural auth scope --project <slug>`."
    )


def _workspace_or_none() -> Workspace | None:
    try:
        return workspace()
    except ProjectError:
        return None


def _catalog() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in RUNTIME_PROVIDERS]


def _provider(providers: list[dict[str, Any]], provider_id: str) -> dict[str, Any]:
    for item in providers:
        if item["id"] == provider_id:
            return item
    known = ", ".join(item["id"] for item in providers if item["status"] == "available")
    raise ProjectError(f"Unknown provider {provider_id!r}. Choose one of: {known}.")


def _usable(providers: list[dict[str, Any]], provider_id: str) -> dict[str, Any]:
    spec = _provider(providers, provider_id)
    if spec["status"] != "available":
        known = ", ".join(item["id"] for item in providers if item["status"] == "available")
        raise ProjectError(f"{spec['name']} Runtimes are coming soon. Choose one of: {known}.")
    return spec


def _parse_settings(values: list[str] | None) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for item in values or []:
        key, separator, value = item.partition("=")
        if not separator or not key.strip():
            raise ProjectError(f"--set {item!r} must look like key=value.")
        settings[key.strip()] = value
    return settings


def _parse_credentials(
    spec: dict[str, Any], values: list[str] | None, *, from_env: bool
) -> dict[str, str]:
    known = {item["key"]: item for item in spec["credentials"]}
    credentials: dict[str, str] = {}
    if from_env:
        for key in known:
            if os.environ.get(key):
                credentials[key] = os.environ[key]
    for item in values or []:
        key, separator, value = item.partition("=")
        key = key.strip()
        if key not in known:
            names = ", ".join(known) or "none"
            raise ProjectError(
                f"{spec['name']} has no credential {key!r}. Its credentials are: {names}."
            )
        credentials[key] = (
            value
            if separator
            else typer.prompt(known[key]["label"], hide_input=True, default="", show_default=False)
        )
    return credentials


def _option_label(field: dict[str, Any], value: Any) -> str:
    for option in field["options"]:
        if option["value"] == value:
            return str(option["label"])
    return str(value)


def _display(field: dict[str, Any], value: Any) -> str:
    if value is None or value == "" or value == []:
        return muted(field["placeholder"] or "Provider default")
    if field["kind"] == "select":
        return _option_label(field, value)
    if field["kind"] == "hosts" and isinstance(value, list):
        return ", ".join(value)
    if field["kind"] == "boolean":
        return "Yes" if value else "No"
    unit = f" {field['unit']}" if field["unit"] else ""
    return f"{value}{unit}"


def _ask_field(field: dict[str, Any], current: Any) -> Any:
    """Prompt for one setting, explaining it first. Enter keeps ``current``."""
    unit = f" ({field['unit']})" if field["unit"] else ""
    typer.echo("")
    typer.echo(typer.style(field["label"] + unit, bold=True))
    typer.echo("  " + muted(field["help"]))
    if field["kind"] == "boolean":
        return typer.confirm("  Turn on?", default=bool(current))
    if field["kind"] == "select":
        options = field["options"]
        for index, option in enumerate(options, start=1):
            marker = "•" if option["value"] == current else " "
            hint = f"  {muted(option['help'])}" if option["help"] else ""
            typer.echo(f"  {marker} {index}. {option['label']}{hint}")
        default = next(
            (str(index) for index, option in enumerate(options, 1) if option["value"] == current),
            "",
        )
        while True:
            answer = typer.prompt("  Choose", default=default, show_default=bool(default)).strip()
            if not answer and not field["required"]:
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1]["value"]
            if any(option["value"] == answer for option in options):
                return answer
            typer.echo(f"  Enter a number from 1 to {len(options)}.")
    shown = ", ".join(current) if isinstance(current, list) else current
    answer = typer.prompt(
        "  Value" if not field["placeholder"] else f"  Value (e.g. {field['placeholder']})",
        default="" if shown is None else str(shown),
        show_default=shown not in (None, ""),
    ).strip()
    return answer or None


def _ask_settings(
    spec: dict[str, Any],
    current: dict[str, Any],
    *,
    locked: frozenset[str] = frozenset(),
    advanced: bool = False,
) -> dict[str, Any]:
    """Prompt for every setting the person may change, in catalog order."""
    chosen = dict(current)
    for field in spec["fields"]:
        key = field["key"]
        if key in locked:
            continue
        if field["advanced"] and not advanced:
            continue
        if key == "allowed_hosts" and chosen.get("network") != "allowlist":
            continue
        value = _ask_field(field, chosen.get(key, field["default"]))
        if value is None:
            chosen.pop(key, None)
        else:
            chosen[key] = value
    return chosen


def _ask_credentials(
    spec: dict[str, Any], given: dict[str, str], *, keeping: bool
) -> dict[str, str]:
    credentials = dict(given)
    for item in spec["credentials"]:
        key = item["key"]
        if key in credentials:
            continue
        typer.echo("")
        typer.echo(typer.style(f"{item['label']} ({key})", bold=True))
        typer.echo("  " + muted(item["help"]))
        if spec.get("credentials_url"):
            typer.echo("  " + muted(f"Get one at {spec['credentials_url']}"))
        if os.environ.get(key) and typer.confirm(
            f"  Use {key} from your environment?", default=True
        ):
            credentials[key] = os.environ[key]
            continue
        hint = "  Leave empty to keep the saved value" if keeping else "  Value"
        value = typer.prompt(hint, hide_input=item["secret"], default="", show_default=False)
        if value.strip():
            credentials[key] = value.strip()
    return credentials


def _choose(prompt: str, choices: list[tuple[str, str, str]]) -> str:
    """Pick one of ``(value, label, detail)`` by number."""
    typer.echo("")
    typer.echo(typer.style(prompt, bold=True))
    for index, (_, label, detail) in enumerate(choices, start=1):
        typer.echo(f"  {index}. {label}" + (f"  {muted(detail)}" if detail else ""))
    while True:
        answer = typer.prompt("  Choose", default="1").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1][0]
        typer.echo(f"  Enter a number from 1 to {len(choices)}.")


def _available(providers: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = policy.get("allowed_providers")
    return [
        item
        for item in providers
        if item["status"] == "available" and (allowed is None or item["id"] in allowed)
    ]


def _needs(item: dict[str, Any]) -> str:
    if item["status"] != "available":
        return "coming soon"
    if item["credentials"]:
        return ", ".join(credential["key"] for credential in item["credentials"])
    return "Docker on the runner" if item["id"] == "docker" else "nothing"


def _print_settings(spec: dict[str, Any], settings: dict[str, Any], locked: list[str]) -> None:
    pairs = []
    for field in spec["fields"]:
        if field["key"] not in settings:
            continue
        label = field["label"] + (" (locked)" if field["key"] in locked else "")
        pairs.append((label, _display(field, settings[field["key"]])))
    if pairs:
        details(pairs)
    else:
        typer.echo("  " + muted("Provider defaults"))


def _credential_line(item: dict[str, Any]) -> str:
    hints = item.get("credential_hints") or {}
    if not hints:
        return "none saved"
    return ", ".join(f"{key} {hint}" for key, hint in sorted(hints.items()))


# Providers


@runtime_app.command("providers")
@handled
def providers_command(as_json: bool = JSON_OPTION) -> None:
    """List the providers a Runtime can use and what each needs."""
    items = _catalog()

    def text() -> None:
        rows(
            (
                (
                    item["id"],
                    item["name"],
                    CATEGORY_LABELS.get(item["category"], item["category"]),
                    _needs(item),
                )
                for item in items
            ),
            ("provider", "name", "runs on", "needs"),
        )
        typer.echo("")
        typer.echo("See every setting with `plural runtime provider <provider>`.")

    emit(items, as_json=as_json, text=text)


@runtime_app.command("provider")
@handled
def provider_command(
    provider: str = typer.Argument(help="Provider id, such as daytona or docker."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Explain one provider: its credentials and every setting."""
    spec = _provider(_catalog(), provider)

    def text() -> None:
        heading(f"{spec['name']}: {spec['tagline']}")
        typer.echo(spec["description"])
        if spec["status"] != "available":
            note(f"{spec['name']} Runtimes are coming soon.")
            return
        if spec["runner"] != "built_in":
            note(
                f"This SDK does not start {spec['name']} sandboxes yet. You can configure "
                "Runtimes now; local runs need a provider plugin that registers "
                f"{spec['id']!r}."
            )
        for line in spec["notes"]:
            note(line)
        if spec["credentials"]:
            typer.echo("")
            heading("Credentials")
            for item in spec["credentials"]:
                typer.echo(f"  {item['key']}  {item['label']}")
                typer.echo(f"    {muted(item['help'])}")
        typer.echo("")
        heading("Settings (--set key=value)")
        for field in spec["fields"]:
            default = (
                f" [default: {field['default']}]" if field["default"] not in (None, "") else ""
            )
            required = " (required)" if field["required"] else ""
            typer.echo(f"  {field['key']}  {field['label']}{required}{default}")
            typer.echo(f"    {muted(field['help'])}")
            if field["options"]:
                values = ", ".join(option["value"] for option in field["options"])
                typer.echo(f"    {muted('One of: ' + values)}")
        links = [url for url in (spec.get("docs_url"), spec.get("credentials_url")) if url]
        if links:
            typer.echo("")
            details(
                (("Docs", spec.get("docs_url") or ""), ("Keys", spec.get("credentials_url") or ""))
            )

    emit(spec, as_json=as_json, text=text)


# Project Runtimes


@runtime_app.command("list")
@handled
def list_command(as_json: bool = JSON_OPTION) -> None:
    """List the current project's Runtimes."""
    studio, project = _project_studio()
    items = studio.runtimes.list()

    def text() -> None:
        if not items:
            typer.echo(
                f"Project {project} has no Runtimes yet. Add one with `plural runtime create`."
            )
            return
        rows(
            (
                (
                    item["slug"],
                    item["name"],
                    item["provider"],
                    item["template"]["slug"] if item.get("template") else "custom",
                    "ready" if item["credentials_ready"] else "missing",
                    item["environment_count"],
                )
                for item in items
            ),
            ("runtime", "name", "provider", "template", "credentials", "environments"),
        )

    emit(items, as_json=as_json, text=text)


@runtime_app.command("show")
@handled
def show_command(
    runtime: str = typer.Argument(help="Runtime slug or id."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show one project Runtime and the settings Environments copy from it."""
    studio, _ = _project_studio()
    item = studio.runtimes.get(runtime)

    def text() -> None:
        spec = _provider(studio.runtimes.providers(), item["provider"])
        heading(f"{item['name']} ({item['slug']})")
        if item["description"]:
            typer.echo(item["description"])
        template = item.get("template")
        details(
            (
                ("Provider", spec["name"]),
                (
                    "Template",
                    f"{template['name']} ({template['slug']})" if template else "None (custom)",
                ),
                (
                    "Credentials",
                    ("ready" if item["credentials_ready"] else "missing")
                    + f" · from the {item['credential_source']}",
                ),
                ("Environments", str(item["environment_count"])),
            )
        )
        typer.echo("")
        heading("Settings")
        _print_settings(spec, item["settings"], item.get("locked_fields") or [])

    emit(item, as_json=as_json, text=text)


@runtime_app.command("create")
@handled
def create_command(
    name: str | None = typer.Argument(None, help="Runtime name, such as 'GPU sandbox'."),
    template: str | None = typer.Option(
        None, "--template", "-t", help="Start from this Runtime template (slug or id)."
    ),
    provider: str | None = typer.Option(
        None, "--provider", "-p", help="Configure a provider directly instead of a template."
    ),
    settings: list[str] | None = SET_OPTION,
    credential: list[str] | None = CREDENTIAL_OPTION,
    credentials_from_env: bool = FROM_ENV_OPTION,
    description: str = typer.Option("", "--description", help="What this Runtime is for."),
    advanced: bool = typer.Option(False, "--advanced", help="Also prompt for advanced settings."),
    no_input: bool = NO_INPUT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Add a Runtime to the current project.

    Run it with no options for a guided setup that explains each setting. In a
    script, pass --template or --provider with --set and --credentials-from-env.
    """
    if template and provider:
        fail("Choose --template or --provider, not both.")
    studio, project = _project_studio()
    interactive = _interactive(no_input)
    providers = studio.runtimes.providers()
    policy = studio.runtimes.policy()
    templates = [item for item in studio.runtimes.templates() if item["status"] == "active"]
    if interactive and not name:
        name = typer.prompt("Name this Runtime").strip()
    if not name:
        fail("Name the Runtime, for example `plural runtime create 'GPU sandbox'`.")
    chosen_template: dict[str, Any] | None = None
    if not template and not provider:
        choices = [
            (f"template:{item['slug']}", item["name"], f"{item['provider']} template")
            for item in templates
        ]
        if policy["mode"] == "open":
            choices += [
                (f"provider:{item['id']}", item["name"], item["tagline"])
                for item in _available(providers, policy)
            ]
        if not choices:
            fail(
                "Your organization only allows Runtimes from templates, and it has none yet. "
                "Ask an admin to add one."
            )
        if not interactive:
            fail("Pass --template or --provider. List them with `plural runtime template list`.")
        picked = _choose("Start from", choices)
        kind, _, value = picked.partition(":")
        template, provider = (value, None) if kind == "template" else (None, value)
    if template:
        chosen_template = next(
            (item for item in templates if template in {item["slug"], item["id"]}), None
        ) or studio.runtimes.template(template)
        provider = chosen_template["provider"]
    assert provider is not None
    spec = _usable(providers, provider)
    chosen = _parse_settings(settings)
    locked = frozenset(chosen_template["locked_fields"]) if chosen_template else frozenset()
    if interactive and not settings:
        base = dict(chosen_template["settings"]) if chosen_template else {}
        if chosen_template and locked:
            typer.echo("")
            typer.echo(muted("Locked by the template: " + ", ".join(sorted(locked))))
        answered = _ask_settings(spec, base, locked=locked, advanced=advanced)
        chosen = {key: value for key, value in answered.items() if base.get(key) != value}
    credentials: dict[str, str] = {}
    if chosen_template is None:
        credentials = _parse_credentials(spec, credential, from_env=credentials_from_env)
        if interactive and spec["credentials"]:
            credentials = _ask_credentials(spec, credentials, keeping=False)
    elif credential or credentials_from_env:
        fail("A Runtime from a template uses the template's credentials.")
    payload: dict[str, Any] = {
        "name": name,
        "description": description,
        "settings": chosen,
        "credentials": credentials,
    }
    if chosen_template is not None:
        payload["template_id"] = chosen_template["id"]
    else:
        payload["provider"] = provider
    item = studio.runtimes.create(payload)

    def text() -> None:
        origin = f"from template {chosen_template['slug']}" if chosen_template else "custom"
        success(f"Created Runtime {item['slug']} in project {project} ({spec['name']}, {origin}).")
        if not item["credentials_ready"]:
            note(
                "It has no credentials yet. Add them with `plural runtime edit "
                f"{item['slug']} --credential <KEY>`."
            )
        typer.echo(
            f"Run an Environment on it with `plural runtime use {item['slug']} <environment>`."
        )

    emit(item, as_json=as_json, text=text)


@runtime_app.command("edit")
@handled
def edit_command(
    runtime: str = typer.Argument(help="Runtime slug or id."),
    settings: list[str] | None = SET_OPTION,
    unset: list[str] | None = typer.Option(
        None, "--unset", help="Return a setting to its default."
    ),
    credential: list[str] | None = CREDENTIAL_OPTION,
    credentials_from_env: bool = FROM_ENV_OPTION,
    name: str | None = typer.Option(None, "--name", help="A new name."),
    description: str | None = typer.Option(None, "--description", help="A new description."),
    advanced: bool = typer.Option(False, "--advanced", help="Also prompt for advanced settings."),
    no_input: bool = NO_INPUT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Change a project Runtime's settings or credentials.

    Environments keep the settings they copied. Run `plural runtime use` again
    to update them.
    """
    studio, _ = _project_studio()
    item = studio.runtimes.get(runtime)
    spec = _provider(studio.runtimes.providers(), item["provider"])
    overrides = dict(item["overrides"])
    for key in unset or []:
        overrides.pop(key, None)
    overrides.update(_parse_settings(settings))
    custom = item.get("template") is None
    changed_anything = any((settings, unset, credential, credentials_from_env, name, description))
    credentials = (
        _parse_credentials(spec, credential, from_env=credentials_from_env) if custom else {}
    )
    if not custom and (credential or credentials_from_env):
        fail("This Runtime uses its template's credentials. Ask an admin to change them.")
    if _interactive(no_input) and not changed_anything:
        locked = frozenset(item.get("locked_fields") or [])
        answered = _ask_settings(spec, dict(item["settings"]), locked=locked, advanced=advanced)
        base = item["template"]["settings"] if not custom else {}
        overrides = {key: value for key, value in answered.items() if base.get(key) != value}
        if custom and spec["credentials"] and typer.confirm("\nChange credentials?", default=False):
            credentials = _ask_credentials(spec, {}, keeping=True)
    payload: dict[str, Any] = {"settings": overrides}
    if credentials:
        payload["credentials"] = credentials
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description
    updated = studio.runtimes.update(item["slug"], payload)

    def text() -> None:
        success(f"Updated Runtime {updated['slug']}.")
        if updated["environment_count"]:
            typer.echo(
                f"{updated['environment_count']} Environment(s) use it. Copy the change into "
                f"each with `plural runtime use {updated['slug']} <environment>`, then push."
            )

    emit(updated, as_json=as_json, text=text)


@runtime_app.command("delete")
@handled
def delete_command(
    runtime: str = typer.Argument(help="Runtime slug or id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Delete a project Runtime and its saved credentials."""
    studio, project = _project_studio()
    item = studio.runtimes.get(runtime)
    if not yes:
        usage = (
            f" {item['environment_count']} Environment(s) use it and will need another Runtime."
            if item["environment_count"]
            else ""
        )
        typer.confirm(f"Delete Runtime {item['slug']} from {project}?{usage}", abort=True)
    studio.runtimes.delete(item["slug"])
    success(f"Deleted Runtime {item['slug']}.")


@runtime_app.command("use")
@handled
def use_command(
    runtime: str = typer.Argument(help="Runtime slug or id."),
    environments: list[str] | None = typer.Argument(
        None, help="Environments to run on it. Defaults to the only Environment, if there is one."
    ),
    every: bool = typer.Option(False, "--all", help="Every Environment in the project."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Run Environments on a project Runtime by copying its settings into environment.yaml."""
    space = workspace()
    current: Session = signed_in(session())
    studio, _ = project_studio(space, current)
    item = studio.runtimes.get(runtime)
    if item.get("environment_runtime") is None:
        fail(
            f"Runtime {item['slug']}'s settings no longer validate against its template. "
            f"Fix them with `plural runtime edit {item['slug']}`."
        )
    names = space.project.names(ENVIRONMENT)
    targets = names if every else list(environments or [])
    if not targets:
        if len(names) != 1:
            listed = ", ".join(names) or "none"
            fail(f"Name the Environments to update, or pass --all. This project has: {listed}.")
        targets = names
    changed = [
        name for name in targets if use_runtime(space.project, name, item["environment_runtime"])
    ]

    def text() -> None:
        if not changed:
            typer.echo(f"Already up to date with Runtime {item['slug']}.")
            return
        for name in changed:
            success(f"environments/{name}/environment.yaml now runs on {item['slug']}.")
        typer.echo("Push to save: " + " ".join(f"`plural env push {name}`" for name in changed))

    emit({"runtime": item["slug"], "updated": changed}, as_json=as_json, text=text)


# Templates


@template_app.command("list")
@handled
def template_list(as_json: bool = JSON_OPTION) -> None:
    """List the account's Runtime templates."""
    items = _account_studio().runtimes.templates()

    def text() -> None:
        if not items:
            typer.echo(
                "No Runtime templates yet. Admins add them with `plural runtime template create`."
            )
            return
        rows(
            (
                (
                    item["slug"],
                    item["name"],
                    item["provider"],
                    item["status"],
                    ", ".join(item["locked_fields"]) or "—",
                    item["project_runtime_count"],
                )
                for item in items
            ),
            ("template", "name", "provider", "status", "locked", "runtimes"),
        )

    emit(items, as_json=as_json, text=text)


@template_app.command("show")
@handled
def template_show(
    template: str = typer.Argument(help="Template slug or id."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Show one Runtime template."""
    studio = _account_studio()
    item = studio.runtimes.template(template)

    def text() -> None:
        spec = _provider(studio.runtimes.providers(), item["provider"])
        heading(f"{item['name']} ({item['slug']})")
        if item["description"]:
            typer.echo(item["description"])
        details(
            (
                ("Provider", spec["name"]),
                ("Status", item["status"]),
                ("Credentials", _credential_line(item)),
                (
                    "Local runs",
                    "may use these credentials"
                    if item["share_credentials"]
                    else "bring their own credentials",
                ),
                ("Project Runtimes", str(item["project_runtime_count"])),
            )
        )
        typer.echo("")
        heading("Settings")
        _print_settings(spec, item["settings"], item["locked_fields"])

    emit(item, as_json=as_json, text=text)


@template_app.command("create")
@handled
def template_create(
    name: str | None = typer.Argument(None, help="Template name, such as 'Daytona US'."),
    provider: str | None = typer.Option(None, "--provider", "-p", help="Provider id."),
    settings: list[str] | None = SET_OPTION,
    credential: list[str] | None = CREDENTIAL_OPTION,
    credentials_from_env: bool = FROM_ENV_OPTION,
    lock: list[str] | None = typer.Option(
        None, "--lock", help="A setting project Runtimes may not change. Repeat for more."
    ),
    share_credentials: bool = typer.Option(
        False,
        "--share-credentials/--no-share-credentials",
        help="Let members' local runs use this template's credentials.",
    ),
    description: str = typer.Option("", "--description", help="What this template is for."),
    advanced: bool = typer.Option(False, "--advanced", help="Also prompt for advanced settings."),
    no_input: bool = NO_INPUT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Add a Runtime template to the account. Organization owners and admins only."""
    studio = _account_studio()
    interactive = _interactive(no_input)
    providers = studio.runtimes.providers()
    policy = studio.runtimes.policy()
    if not policy["can_manage"]:
        fail("Only organization owners and admins can manage Runtime templates.")
    if interactive and not name:
        name = typer.prompt("Name this template").strip()
    if not name:
        fail("Name the template, for example `plural runtime template create 'Daytona US'`.")
    if not provider:
        if not interactive:
            fail("Pass --provider. List providers with `plural runtime providers`.")
        provider = _choose(
            "Provider",
            [(item["id"], item["name"], item["tagline"]) for item in _available(providers, policy)],
        )
    spec = _usable(providers, provider)
    chosen = _parse_settings(settings)
    credentials = _parse_credentials(spec, credential, from_env=credentials_from_env)
    locked = list(lock or [])
    if interactive and not settings:
        chosen = _ask_settings(spec, {}, advanced=advanced)
    if interactive and spec["credentials"]:
        credentials = _ask_credentials(spec, credentials, keeping=False)
    if interactive and not lock and spec["fields"]:
        typer.echo("")
        typer.echo(typer.style("Lock settings", bold=True))
        typer.echo(
            "  "
            + muted(
                "Locked settings cannot be changed by project Runtimes made from this template."
            )
        )
        answer = typer.prompt(
            "  Settings to lock, comma separated (e.g. network,allowed_hosts)",
            default="",
            show_default=False,
        )
        locked = [item.strip() for item in answer.split(",") if item.strip()]
    if interactive and spec["credentials"] and not share_credentials:
        share_credentials = typer.confirm(
            "\nLet members' local `plural run` use these credentials?", default=False
        )
    item = studio.runtimes.create_template(
        {
            "name": name,
            "description": description,
            "provider": provider,
            "settings": chosen,
            "credentials": credentials,
            "locked_fields": locked,
            "share_credentials": share_credentials,
        }
    )

    def text() -> None:
        success(f"Created Runtime template {item['slug']} ({spec['name']}).")
        typer.echo(
            f"Members can now run `plural runtime create --template {item['slug']}` in a project."
        )

    emit(item, as_json=as_json, text=text)


@template_app.command("edit")
@handled
def template_edit(
    template: str = typer.Argument(help="Template slug or id."),
    settings: list[str] | None = SET_OPTION,
    unset: list[str] | None = typer.Option(
        None, "--unset", help="Return a setting to its default."
    ),
    credential: list[str] | None = CREDENTIAL_OPTION,
    credentials_from_env: bool = FROM_ENV_OPTION,
    lock: list[str] | None = typer.Option(None, "--lock", help="Replace the locked settings."),
    share_credentials: bool | None = typer.Option(
        None,
        "--share-credentials/--no-share-credentials",
        help="Whether members' local runs may use this template's credentials.",
    ),
    name: str | None = typer.Option(None, "--name", help="A new name."),
    description: str | None = typer.Option(None, "--description", help="A new description."),
    as_json: bool = JSON_OPTION,
) -> None:
    """Change a Runtime template. Project Runtimes made from it follow the change."""
    studio = _account_studio()
    item = studio.runtimes.template(template)
    spec = _provider(studio.runtimes.providers(), item["provider"])
    values = dict(item["settings"])
    for key in unset or []:
        values.pop(key, None)
    values.update(_parse_settings(settings))
    payload: dict[str, Any] = {"settings": values}
    credentials = _parse_credentials(spec, credential, from_env=credentials_from_env)
    if credentials:
        payload["credentials"] = credentials
    if lock is not None:
        payload["locked_fields"] = lock
    if share_credentials is not None:
        payload["share_credentials"] = share_credentials
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description
    updated = studio.runtimes.update_template(item["slug"], payload)
    emit(
        updated,
        as_json=as_json,
        text=lambda: success(f"Updated Runtime template {updated['slug']}."),
    )


def _set_template_status(template: str, status: str, as_json: bool) -> None:
    studio = _account_studio()
    updated = studio.runtimes.update_template(template, {"status": status})
    message = (
        f"Disabled Runtime template {updated['slug']}. New project Runtimes cannot use it, "
        "and Jobs on Runtimes made from it are refused."
        if status == "disabled"
        else f"Enabled Runtime template {updated['slug']}."
    )
    emit(updated, as_json=as_json, text=lambda: success(message))


@template_app.command("disable")
@handled
def template_disable(
    template: str = typer.Argument(help="Template slug or id."), as_json: bool = JSON_OPTION
) -> None:
    """Stop a template from being used, without deleting it."""
    _set_template_status(template, "disabled", as_json)


@template_app.command("enable")
@handled
def template_enable(
    template: str = typer.Argument(help="Template slug or id."), as_json: bool = JSON_OPTION
) -> None:
    """Allow a disabled template to be used again."""
    _set_template_status(template, "active", as_json)


@template_app.command("delete")
@handled
def template_delete(
    template: str = typer.Argument(help="Template slug or id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Delete a template and its credentials. Refused while project Runtimes use it."""
    studio = _account_studio()
    item = studio.runtimes.template(template)
    if not yes:
        typer.confirm(f"Delete Runtime template {item['slug']} and its credentials?", abort=True)
    studio.runtimes.delete_template(item["slug"])
    success(f"Deleted Runtime template {item['slug']}.")


# Policy


def _print_policy(policy: dict[str, Any]) -> None:
    allowed = policy.get("allowed_providers")
    details(
        (
            (
                "Members may create",
                "any Runtime" if policy["mode"] == "open" else "only Runtimes from templates",
            ),
            ("Allowed providers", "all" if allowed is None else ", ".join(allowed) or "none"),
        )
    )
    if policy["account_type"] == "user":
        typer.echo(muted("Personal accounts are always open; policy applies to organizations."))


@policy_app.callback()
@handled
def policy_show(ctx: typer.Context, as_json: bool = JSON_OPTION) -> None:
    """Show the account's Runtime policy."""
    if ctx.invoked_subcommand is not None:
        return
    policy = _account_studio().runtimes.policy()
    emit(policy, as_json=as_json, text=lambda: _print_policy(policy))


@policy_app.command("set")
@handled
def policy_set(
    mode: str = typer.Option(
        ...,
        "--mode",
        help="open lets members configure any allowed provider; templates-only "
        "limits them to the account's templates.",
    ),
    allow: list[str] | None = typer.Option(
        None, "--allow", help="A provider members may use. Repeat for more. Omit for all."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Set the organization's Runtime policy. Owners and admins only."""
    normalized = mode.replace("-", "_")
    if normalized not in {"open", "templates_only"}:
        fail("--mode must be open or templates-only.")
    policy = _account_studio().runtimes.set_policy(
        mode=normalized, allowed_providers=list(allow) if allow else None
    )

    def text() -> None:
        success("Updated the Runtime policy.")
        _print_policy(policy)

    emit(policy, as_json=as_json, text=text)


__all__ = ["runtime_app"]
