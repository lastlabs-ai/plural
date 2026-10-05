"""The Runtime providers Plural knows how to configure, and what each one needs.

Every provider declares the credentials it needs and the settings a person may
choose, each with a label and a plain-language explanation. The hosted service
serves this catalog, the web app renders its forms from it, and the CLI prompts
from it, so a field is described once.

A setting whose key is an :class:`~plural.environments.definition.EnvironmentRuntime`
field (``image``, ``cpus``, ``network``, ...) maps onto that field. Every other
setting is provider-specific and is stored in ``placement`` as a string.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from plural.sandbox.models import NetworkMode, ResourceRequirements, SandboxModel

if TYPE_CHECKING:
    from plural.environments.definition import EnvironmentRuntime, RuntimeVariable

RUNTIME_KEYS = frozenset(
    {
        "image",
        "snapshot",
        "cpus",
        "memory_mb",
        "storage_mb",
        "pids",
        "timeout_seconds",
        "network",
        "allowed_hosts",
        "read_only_root",
    }
)
"""Setting keys that map onto ``EnvironmentRuntime`` fields rather than ``placement``."""

FieldKind = Literal["text", "url", "integer", "number", "select", "boolean", "hosts"]
FieldGroup = Literal["image", "machine", "network", "placement"]

_HOST = re.compile(
    r"^(?=.{1,253}$)(\*\.)?([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_NETWORK_LABELS = {
    "public": ("Open internet", "The sandbox can reach any public host."),
    "no-network": ("No network", "No outbound connections. Model calls will fail."),
    "allowlist": ("Named hosts only", "Only the hosts you list below are reachable."),
}
MAX_CREDENTIAL_LENGTH = 4096


class RuntimeFieldOption(SandboxModel):
    """One choice for a ``select`` field."""

    value: str
    label: str
    help: str = ""


class RuntimeField(SandboxModel):
    """One setting a person chooses for a Runtime, and how to explain it."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    help: str
    kind: FieldKind = "text"
    group: FieldGroup = "machine"
    required: bool = False
    default: str | int | float | bool | None = None
    provider_default: str | int | float | None = Field(
        default=None,
        description="What the provider itself uses when the field is left unset. Shown "
        "to people, never applied: unlike default, it does not enter resolved settings.",
    )
    placeholder: str = ""
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = Field(
        default=None,
        description="Increment between allowed values, counted from zero. "
        "None means 1 for integers and any value for numbers.",
    )
    options: tuple[RuntimeFieldOption, ...] = ()
    advanced: bool = False

    @property
    def placement(self) -> bool:
        """Whether the value is stored in ``placement`` rather than a Runtime field."""
        return self.key not in RUNTIME_KEYS


class RuntimeCredential(SandboxModel):
    """A credential the provider needs, supplied as the environment variable ``key``."""

    key: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    label: str
    help: str
    secret: bool = True
    required: bool = True
    placeholder: str = ""


class RuntimeProviderSpec(SandboxModel):
    """A provider a Runtime can run on."""

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    name: str
    tagline: str
    description: str
    category: Literal["sandbox", "self_managed", "cloud"]
    status: Literal["available", "coming_soon"] = "available"
    runner: Literal["built_in", "plugin"] = Field(
        default="plugin",
        description="built_in when this SDK ships the adapter that starts sandboxes here; "
        "plugin when an installed provider plugin must register it.",
    )
    target: Literal["local", "docker", "remote"] = "remote"
    docs_url: str | None = None
    credentials_url: str | None = None
    network_modes: tuple[str, ...] = ("public",)
    credentials: tuple[RuntimeCredential, ...] = ()
    fields: tuple[RuntimeField, ...] = ()
    notes: tuple[str, ...] = ()

    def field(self, key: str) -> RuntimeField | None:
        """The setting named ``key``, if this provider has one."""
        return next((item for item in self.fields if item.key == key), None)


def _image(default: str | None, help: str, placeholder: str = "") -> RuntimeField:
    return RuntimeField(
        key="image",
        label="Container image",
        help=help,
        group="image",
        default=default,
        placeholder=placeholder or (default or ""),
    )


def _cpus(help: str = "Virtual CPU cores for each sandbox.", **extra: Any) -> RuntimeField:
    options: dict[str, Any] = {"kind": "integer", "minimum": 1, "maximum": 64, **extra}
    return RuntimeField(key="cpus", label="CPU cores", help=help, unit="cores", **options)


def _memory(help: str = "Memory for each sandbox.", **extra: Any) -> RuntimeField:
    options: dict[str, Any] = {"minimum": 1024, "maximum": 524288, "step": 1024, **extra}
    return RuntimeField(
        key="memory_mb", label="Memory", help=help, kind="integer", unit="MB", **options
    )


def _timeout(maximum: float = 86400, default: int = 300) -> RuntimeField:
    return RuntimeField(
        key="timeout_seconds",
        label="Command timeout",
        help="How long one command in the sandbox may run before Plural stops it. "
        "The Environment's episode budget limits the whole run separately.",
        kind="integer",
        unit="seconds",
        minimum=1,
        maximum=maximum,
        default=default,
    )


def _network(modes: tuple[str, ...]) -> tuple[RuntimeField, ...]:
    network = RuntimeField(
        key="network",
        label="Network access",
        help="What the sandbox may reach. The Agent's model calls run inside it, so "
        "keep the model endpoint reachable unless the Environment needs no model.",
        kind="select",
        group="network",
        default="public",
        options=tuple(
            RuntimeFieldOption(
                value=mode, label=_NETWORK_LABELS[mode][0], help=_NETWORK_LABELS[mode][1]
            )
            for mode in modes
        ),
    )
    if "allowlist" not in modes:
        return (network,)
    hosts = RuntimeField(
        key="allowed_hosts",
        label="Allowed hosts",
        help="Host names the sandbox may reach when network access is limited to "
        "named hosts, such as api.openai.com. Use *.example.com for subdomains.",
        kind="hosts",
        group="network",
        placeholder="api.openai.com",
    )
    return (network, hosts)


RUNTIME_PROVIDERS: tuple[RuntimeProviderSpec, ...] = (
    RuntimeProviderSpec(
        id="daytona",
        name="Daytona",
        tagline="Fast, stateful cloud sandboxes",
        description="Secure sandboxes that start in well under a second, from any OCI "
        "image or a prebuilt snapshot. Supports compute limits and host allowlists.",
        category="sandbox",
        runner="built_in",
        docs_url="https://www.daytona.io/docs",
        credentials_url="https://app.daytona.io/dashboard/keys",
        network_modes=("public", "no-network", "allowlist"),
        credentials=(
            RuntimeCredential(
                key="DAYTONA_API_KEY",
                label="API key",
                help="Create one under Keys in the Daytona dashboard. It needs permission "
                "to create and delete sandboxes.",
                placeholder="dtn_…",
            ),
        ),
        fields=(
            RuntimeField(
                key="target",
                label="Region",
                help="Where Daytona runs the sandbox. Pick the region closest to the "
                "model endpoint to keep latency low, or leave it unset for your Daytona "
                "organization's default.",
                kind="select",
                group="placement",
                options=(
                    RuntimeFieldOption(value="us", label="United States"),
                    RuntimeFieldOption(value="eu", label="Europe"),
                ),
            ),
            _image(
                "python:3.12-slim",
                "Any public or registry image Daytona can pull. Leave empty when you "
                "use a snapshot instead.",
            ),
            RuntimeField(
                key="snapshot",
                label="Snapshot",
                help="A snapshot you created in Daytona. Snapshots start faster than "
                "images because dependencies are already installed. Use either an "
                "image or a snapshot, not both.",
                group="image",
                placeholder="my-snapshot",
            ),
            _cpus(provider_default=1),
            _memory(provider_default=1024),
            *_network(("public", "no-network", "allowlist")),
            _timeout(),
            RuntimeField(
                key="api_url",
                label="API URL",
                help="Only for self-hosted or dedicated Daytona deployments. Leave empty "
                "to use Daytona Cloud.",
                kind="url",
                group="placement",
                placeholder="https://app.daytona.io/api",
                advanced=True,
            ),
        ),
    ),
    RuntimeProviderSpec(
        id="e2b",
        name="E2B",
        tagline="Open-source sandboxes built for AI agents",
        description="Firecracker microVM sandboxes started from templates. CPU and memory "
        "are fixed when a template is built, so pick a template sized for the work.",
        category="sandbox",
        status="coming_soon",
        docs_url="https://e2b.dev/docs",
        credentials_url="https://e2b.dev/dashboard?tab=keys",
        network_modes=("public", "no-network"),
        credentials=(
            RuntimeCredential(
                key="E2B_API_KEY",
                label="API key",
                help="Copy it from the API Keys tab of the E2B dashboard.",
                placeholder="e2b_…",
            ),
        ),
        fields=(
            RuntimeField(
                key="template",
                label="Template",
                help="The E2B template every sandbox starts from, by name or ID. Build "
                "your own with `e2b template build` to preinstall dependencies and set "
                "CPU and memory.",
                group="image",
                default="base",
                placeholder="base",
            ),
            *_network(("public", "no-network")),
            _timeout(),
            RuntimeField(
                key="domain",
                label="Domain",
                help="Only for self-hosted or bring-your-own-cloud E2B. Leave empty to "
                "use E2B's cloud.",
                group="placement",
                placeholder="e2b.dev",
                advanced=True,
            ),
        ),
    ),
    RuntimeProviderSpec(
        id="modal",
        name="Modal",
        tagline="Serverless containers with GPUs on demand",
        description="Sandboxes on Modal's serverless platform, from any registry image, "
        "with optional GPUs. Good for Environments that train or serve models.",
        category="sandbox",
        status="coming_soon",
        docs_url="https://modal.com/docs/guide/sandbox",
        credentials_url="https://modal.com/settings/tokens",
        network_modes=("public", "no-network"),
        credentials=(
            RuntimeCredential(
                key="MODAL_TOKEN_ID",
                label="Token ID",
                help="Create a token under Settings, then API Tokens, in Modal. The ID "
                "starts with ak-.",
                placeholder="ak-…",
            ),
            RuntimeCredential(
                key="MODAL_TOKEN_SECRET",
                label="Token secret",
                help="Shown once, next to the token ID, when you create the token. It "
                "starts with as-.",
                placeholder="as-…",
            ),
        ),
        fields=(
            RuntimeField(
                key="app",
                label="Modal app",
                help="The Modal app sandboxes are created under. Plural creates it if it "
                "does not exist, so you can find every Plural sandbox in one place.",
                group="placement",
                default="plural-sandboxes",
            ),
            RuntimeField(
                key="environment",
                label="Modal environment",
                help="The Modal environment, such as main or dev. Leave empty for your "
                "workspace's default environment.",
                group="placement",
                placeholder="main",
                advanced=True,
            ),
            _image("python:3.12-slim", "A registry image Modal pulls for each sandbox."),
            _cpus(
                "CPU cores reserved for each sandbox, in steps of a quarter core.",
                kind="number",
                minimum=0.25,
                step=0.25,
                placeholder="Modal default",
            ),
            _memory(minimum=256, step=256, placeholder="Modal default"),
            RuntimeField(
                key="gpu",
                label="GPU",
                help="Attach a GPU to each sandbox. GPUs are billed by Modal while the "
                "sandbox runs.",
                kind="select",
                group="machine",
                default="none",
                options=tuple(
                    RuntimeFieldOption(value=value, label=label)
                    for value, label in (
                        ("none", "No GPU"),
                        ("T4", "NVIDIA T4"),
                        ("L4", "NVIDIA L4"),
                        ("A10G", "NVIDIA A10G"),
                        ("L40S", "NVIDIA L40S"),
                        ("A100", "NVIDIA A100 40 GB"),
                        ("A100-80GB", "NVIDIA A100 80 GB"),
                        ("H100", "NVIDIA H100"),
                        ("H200", "NVIDIA H200"),
                        ("B200", "NVIDIA B200"),
                    )
                ),
            ),
            RuntimeField(
                key="region",
                label="Region",
                help="Pin sandboxes to a region, such as us-east or eu-west. Leave empty "
                "to let Modal choose, which starts fastest.",
                group="placement",
                placeholder="us-east",
                advanced=True,
            ),
            *_network(("public", "no-network")),
            _timeout(),
        ),
    ),
    RuntimeProviderSpec(
        id="blaxel",
        name="Blaxel",
        tagline="Perpetual sandboxes that resume in milliseconds",
        description="Sandboxes that suspend when idle and resume almost instantly, "
        "close to your agents. Good for long-lived, interactive Environments.",
        category="sandbox",
        status="coming_soon",
        docs_url="https://docs.blaxel.ai/Sandboxes/Overview",
        credentials_url="https://app.blaxel.ai",
        credentials=(
            RuntimeCredential(
                key="BL_API_KEY",
                label="API key",
                help="Create one in the Blaxel console under your profile, then API keys.",
            ),
        ),
        fields=(
            RuntimeField(
                key="workspace",
                label="Workspace",
                help="The Blaxel workspace sandboxes are created in. It appears in the "
                "console's URL and workspace switcher.",
                group="placement",
                required=True,
                placeholder="my-workspace",
            ),
            _image(
                None,
                "A Blaxel sandbox image. Leave empty for Blaxel's base image.",
                placeholder="blaxel/base-image:latest",
            ),
            _memory(
                "Memory for each sandbox. CPU scales with memory on Blaxel.",
                minimum=2048,
                default=4096,
            ),
            RuntimeField(
                key="region",
                label="Region",
                help="Where sandboxes run, such as us-pdx-1. Leave empty for your "
                "workspace's default region.",
                group="placement",
                placeholder="us-pdx-1",
            ),
            *_network(("public",)),
            _timeout(),
        ),
    ),
    RuntimeProviderSpec(
        id="cloudflare",
        name="Cloudflare",
        tagline="Sandboxes on Cloudflare's global network",
        description="Containers started by a Worker you deploy with the Cloudflare "
        "Sandbox SDK. Plural talks to that Worker, so sandboxes run in your own "
        "Cloudflare account.",
        category="sandbox",
        status="coming_soon",
        docs_url="https://developers.cloudflare.com/sandbox/",
        credentials_url="https://dash.cloudflare.com/profile/api-tokens",
        credentials=(
            RuntimeCredential(
                key="CLOUDFLARE_SANDBOX_TOKEN",
                label="Worker token",
                help="A shared secret your Sandbox Worker checks on every request. Set "
                "the same value as a secret on the Worker with `wrangler secret put`.",
            ),
        ),
        fields=(
            RuntimeField(
                key="worker_url",
                label="Worker URL",
                help="The HTTPS address of the Worker that hosts your sandboxes, built "
                "with @cloudflare/sandbox and deployed with `wrangler deploy`.",
                kind="url",
                group="placement",
                required=True,
                placeholder="https://plural-sandbox.example.workers.dev",
            ),
            *_network(("public",)),
            _timeout(),
        ),
        notes=(
            "Instance size and the container image are set in the Worker's wrangler "
            "configuration, not here.",
        ),
    ),
    RuntimeProviderSpec(
        id="docker",
        name="Docker",
        tagline="A container on the machine that runs the Job",
        description="Runs each Trial in a fresh container on the worker or your laptop. "
        "Needs Docker installed there; no account or credentials.",
        category="self_managed",
        runner="built_in",
        target="docker",
        docs_url="https://docs.docker.com/get-started/",
        network_modes=("public", "no-network"),
        fields=(
            _image("python:3.12-slim", "The image each Trial's container starts from."),
            _cpus(
                "CPU cores the container may use, in steps of half a core. Leave empty "
                "for no limit.",
                kind="number",
                minimum=0.5,
                step=0.5,
                placeholder="No limit",
            ),
            _memory(
                "Memory the container may use. Leave empty for no limit.",
                minimum=128,
                step=128,
                placeholder="No limit",
            ),
            RuntimeField(
                key="pids",
                label="Process limit",
                help="The most processes the container may run at once. Guards against "
                "runaway forks.",
                kind="integer",
                minimum=16,
                maximum=65536,
                placeholder="Docker default",
                advanced=True,
            ),
            *_network(("public", "no-network")),
            RuntimeField(
                key="read_only_root",
                label="Read-only root filesystem",
                help="Stop the Agent from changing the image. The workspace stays writable.",
                kind="boolean",
                default=False,
            ),
            _timeout(),
        ),
    ),
    RuntimeProviderSpec(
        id="local",
        name="Local process",
        tagline="Trusted code on the machine that runs the Job",
        description="Runs the Environment as a plain process with that machine's "
        "software and network. Not a sandbox: use it only for code you trust.",
        category="self_managed",
        runner="built_in",
        target="local",
        fields=(_timeout(),),
        notes=("Local runs cannot limit network access, CPU, or memory.",),
    ),
    RuntimeProviderSpec(
        id="aws",
        name="AWS",
        tagline="Sandboxes in your own AWS account",
        description="Private deployments on infrastructure your organization runs.",
        category="cloud",
        status="coming_soon",
    ),
    RuntimeProviderSpec(
        id="gcp",
        name="Google Cloud",
        tagline="Sandboxes in your own Google Cloud project",
        description="Private deployments on infrastructure your organization runs.",
        category="cloud",
        status="coming_soon",
    ),
    RuntimeProviderSpec(
        id="azure",
        name="Azure",
        tagline="Sandboxes in your own Azure subscription",
        description="Private deployments on infrastructure your organization runs.",
        category="cloud",
        status="coming_soon",
    ),
)
"""Every provider, in the order a person should see them."""

_BY_ID = {item.id: item for item in RUNTIME_PROVIDERS}


class RuntimeSettingsError(ValueError):
    """A Runtime setting or credential is missing or malformed."""


def runtime_provider(provider: str) -> RuntimeProviderSpec | None:
    """The catalog entry for ``provider``, if Plural knows it."""
    return _BY_ID.get(provider)


def require_provider(provider: str) -> RuntimeProviderSpec:
    """The catalog entry for an available provider.

    Raises:
        RuntimeSettingsError: When the provider is unknown or not yet available.
    """
    spec = _BY_ID.get(provider)
    if spec is None:
        known = ", ".join(item.id for item in RUNTIME_PROVIDERS if item.status == "available")
        raise RuntimeSettingsError(
            f"Unknown Runtime provider {provider!r}. Choose one of: {known}."
        )
    if spec.status != "available":
        raise RuntimeSettingsError(
            f"{spec.name} Runtimes are coming soon and cannot be created yet."
        )
    return spec


def _number(field: RuntimeField, value: Any) -> int | float:
    if isinstance(value, bool):
        raise RuntimeSettingsError(f"{field.label} must be a number")
    try:
        number: int | float = int(value) if field.kind == "integer" else float(value)
    except (TypeError, ValueError) as exc:
        kind = "a whole number" if field.kind == "integer" else "a number"
        raise RuntimeSettingsError(f"{field.label} must be {kind}") from exc
    if field.kind == "integer" and isinstance(value, float) and not value.is_integer():
        raise RuntimeSettingsError(f"{field.label} must be a whole number")
    if field.minimum is not None and number < field.minimum:
        raise RuntimeSettingsError(
            f"{field.label} must be at least {field.minimum:g}{_unit(field)}"
        )
    if field.maximum is not None and number > field.maximum:
        raise RuntimeSettingsError(f"{field.label} must be at most {field.maximum:g}{_unit(field)}")
    if field.step and abs(number / field.step - round(number / field.step)) > 1e-9:
        raise RuntimeSettingsError(
            f"{field.label} must be a multiple of {field.step:g}{_unit(field)}"
        )
    return number


def _unit(field: RuntimeField) -> str:
    return f" {field.unit}" if field.unit else ""


def _boolean(field: RuntimeField, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "on"}:
        return True
    if text in {"false", "no", "0", "off"}:
        return False
    raise RuntimeSettingsError(f"{field.label} must be true or false")


def _hosts(field: RuntimeField, value: Any) -> list[str]:
    items = value.replace(",", "\n").split("\n") if isinstance(value, str) else list(value or ())
    hosts: list[str] = []
    for item in items:
        host = str(item).strip().lower()
        if not host:
            continue
        try:
            ipaddress.ip_network(host, strict=False)
        except ValueError:
            if not _HOST.match(host):
                raise RuntimeSettingsError(
                    f"{field.label}: {host!r} is not a host name such as api.openai.com"
                ) from None
        if host not in hosts:
            hosts.append(host)
    return hosts


def _url(field: RuntimeField, value: Any) -> str:
    text = str(value).strip()
    if not re.match(r"^https?://[^\s/]+", text):
        raise RuntimeSettingsError(f"{field.label} must be a URL starting with https://")
    return text.rstrip("/")


def _clean_value(field: RuntimeField, value: Any) -> Any:
    if field.kind in {"integer", "number"}:
        return _number(field, value)
    if field.kind == "boolean":
        return _boolean(field, value)
    if field.kind == "hosts":
        return _hosts(field, value)
    if field.kind == "url":
        return _url(field, value)
    text = str(value).strip()
    if len(text) > 300:
        raise RuntimeSettingsError(f"{field.label} must be at most 300 characters")
    if field.kind == "select":
        allowed = [option.value for option in field.options]
        if text not in allowed:
            raise RuntimeSettingsError(f"{field.label} must be one of: {', '.join(allowed)}")
    return text


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def clean_settings(
    provider: str, settings: Mapping[str, Any], *, partial: bool = False
) -> dict[str, Any]:
    """Validate and normalize the settings a person chose for ``provider``.

    Empty values are dropped, so the result holds only what was chosen; defaults
    are applied later by :func:`resolved_settings`.

    Args:
        provider: A catalog provider id.
        settings: Chosen values keyed by field ``key``.
        partial: Skip the required-field check, for overrides layered on a template.

    Returns:
        The cleaned settings.

    Raises:
        RuntimeSettingsError: For an unknown key or a malformed value.
    """
    spec = require_provider(provider)
    cleaned: dict[str, Any] = {}
    for key, value in settings.items():
        field = spec.field(key)
        if field is None:
            known = ", ".join(item.key for item in spec.fields) or "none"
            raise RuntimeSettingsError(
                f"{spec.name} has no setting {key!r}. Its settings are: {known}."
            )
        if _empty(value):
            continue
        cleaned[key] = _clean_value(field, value)
    if not partial:
        missing = [
            item.label for item in spec.fields if item.required and _empty(cleaned.get(item.key))
        ]
        if missing:
            raise RuntimeSettingsError(f"{spec.name} needs: {', '.join(missing)}")
    return cleaned


def resolved_settings(provider: str, settings: Mapping[str, Any]) -> dict[str, Any]:
    """Cleaned settings with every unset field's default filled in.

    Raises:
        RuntimeSettingsError: When settings are invalid or inconsistent.
    """
    spec = require_provider(provider)
    cleaned = clean_settings(provider, settings)
    for field in spec.fields:
        if field.key in cleaned or field.default is None:
            continue
        if field.key == "image" and "snapshot" in cleaned:
            continue
        cleaned[field.key] = field.default
    if "image" in cleaned and "snapshot" in cleaned:
        raise RuntimeSettingsError("Use either a container image or a snapshot, not both")
    network = cleaned.get("network", "public")
    if network not in spec.network_modes:
        raise RuntimeSettingsError(f"{spec.name} does not support network={network!r}")
    hosts = cleaned.get("allowed_hosts") or []
    if network == "allowlist" and not hosts:
        raise RuntimeSettingsError("List at least one allowed host, or choose another network mode")
    if hosts and network != "allowlist":
        cleaned.pop("allowed_hosts", None)
    if cleaned.get("gpu") == "none":
        cleaned.pop("gpu")
    return cleaned


def clean_credentials(
    provider: str,
    values: Mapping[str, str | None],
    *,
    stored: frozenset[str] = frozenset(),
    required: bool = True,
) -> dict[str, str]:
    """Validate credential values for ``provider``.

    Args:
        provider: A catalog provider id.
        values: Values keyed by credential ``key``. Empty values are dropped.
        stored: Keys that already have a saved value, which an empty value keeps.
        required: Whether every required credential must end up with a value.

    Returns:
        The non-empty values.

    Raises:
        RuntimeSettingsError: For an unknown key, an oversized value, or a
            missing required credential.
    """
    spec = require_provider(provider)
    known = {item.key: item for item in spec.credentials}
    cleaned: dict[str, str] = {}
    for key, value in values.items():
        if key not in known:
            names = ", ".join(known) or "none"
            raise RuntimeSettingsError(
                f"{spec.name} has no credential {key!r}. Its credentials are: {names}."
            )
        text = (value or "").strip()
        if not text:
            continue
        if len(text) > MAX_CREDENTIAL_LENGTH or any(char in text for char in "\r\n\x00"):
            raise RuntimeSettingsError(f"{known[key].label} is not a valid credential")
        cleaned[key] = text
    if required:
        missing = [
            item.label
            for item in spec.credentials
            if item.required and item.key not in cleaned and item.key not in stored
        ]
        if missing:
            raise RuntimeSettingsError(f"{spec.name} needs: {', '.join(missing)}")
    return cleaned


def runtime_environ(provider: str, settings: Mapping[str, Any]) -> dict[str, str]:
    """Non-secret environment variables a provider's client reads from settings.

    Returns:
        Variables such as ``DAYTONA_TARGET``, for the process that starts sandboxes.
    """
    names = {
        "daytona": {"target": "DAYTONA_TARGET", "api_url": "DAYTONA_API_URL"},
        "e2b": {"domain": "E2B_DOMAIN"},
        "modal": {"environment": "MODAL_ENVIRONMENT"},
        "blaxel": {"workspace": "BL_WORKSPACE", "region": "BL_REGION"},
    }.get(provider, {})
    return {env: str(settings[key]) for key, env in names.items() if not _empty(settings.get(key))}


def runtime_from_settings(
    provider: str,
    settings: Mapping[str, Any],
    *,
    ref: str | None = None,
    variables: tuple[RuntimeVariable, ...] = (),
) -> EnvironmentRuntime:
    """Build the Environment Runtime a provider and its settings describe.

    Returns:
        A validated Runtime, with provider-specific settings in ``placement``.

    Raises:
        RuntimeSettingsError: When settings are invalid.
    """
    from plural.common import ExecutionTarget
    from plural.environments.definition import EnvironmentRuntime

    spec = require_provider(provider)
    values = resolved_settings(provider, settings)
    resources = ResourceRequirements.model_validate(
        {
            target: values[source]
            for source, target in (
                ("cpus", "cpu"),
                ("memory_mb", "memory_mb"),
                ("storage_mb", "storage_mb"),
                ("pids", "pids"),
            )
            if source in values
        }
    )
    targets = {
        "local": frozenset({ExecutionTarget.LOCAL}),
        "docker": frozenset({ExecutionTarget.DOCKER, ExecutionTarget.REMOTE}),
        "remote": frozenset({ExecutionTarget.REMOTE}),
    }[spec.target]
    network = NetworkMode(values.get("network", "public"))
    return EnvironmentRuntime(
        provider=provider,
        ref=ref,
        variables=variables,
        image=values.get("image"),
        snapshot=values.get("snapshot"),
        network=network,
        network_allowlist=tuple(values.get("allowed_hosts") or ()),
        resources=resources,
        read_only_root=bool(values.get("read_only_root", False)),
        timeout_seconds=values.get("timeout_seconds", 300),
        placement={
            key: str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in values.items()
            if key not in RUNTIME_KEYS
        },
        targets=targets,
        allow_unsafe_local=spec.target == "local",
    )


def settings_from_runtime(runtime: EnvironmentRuntime) -> dict[str, Any]:
    """The catalog settings an Environment Runtime holds, the inverse of
    :func:`runtime_from_settings` for the fields the provider declares.

    Returns:
        Settings keyed by field ``key``; empty for a provider outside the catalog.
    """
    spec = runtime_provider(runtime.provider)
    if spec is None:
        return {}
    values: dict[str, Any] = {
        "image": runtime.image,
        "snapshot": runtime.snapshot,
        "cpus": runtime.resources.cpu,
        "memory_mb": runtime.resources.memory_mb,
        "storage_mb": runtime.resources.storage_mb,
        "pids": runtime.resources.pids,
        "timeout_seconds": runtime.timeout_seconds,
        "network": runtime.network.value,
        "allowed_hosts": list(runtime.network_allowlist),
        "read_only_root": runtime.read_only_root,
        **runtime.placement,
    }
    return {
        field.key: values[field.key]
        for field in spec.fields
        if field.key in values and not _empty(values[field.key])
    }


__all__ = [
    "RUNTIME_KEYS",
    "RUNTIME_PROVIDERS",
    "RuntimeCredential",
    "RuntimeField",
    "RuntimeFieldOption",
    "RuntimeProviderSpec",
    "RuntimeSettingsError",
    "clean_credentials",
    "clean_settings",
    "require_provider",
    "resolved_settings",
    "runtime_environ",
    "runtime_from_settings",
    "runtime_provider",
    "settings_from_runtime",
]
