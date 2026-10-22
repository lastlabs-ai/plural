"""``plural-agent.yaml``: how an agent service registers with Plural and traces its runs.

The file lives next to the agent's code. ``plural external init`` writes one with
every field explained; edit it, then ``plural external register``. Each run can
override the tracing section in code (:meth:`plural.external.Tracer.run`) or
with ``PLURAL_TRACE_*`` environment variables.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from plural.errors import ConfigurationError

if TYPE_CHECKING:
    from plural.studio import Studio

CONFIG_FILE = "plural-agent.yaml"
CONFIG_VARIABLE = "PLURAL_AGENT_CONFIG"

REQUIRED_FIELDS = (
    "trace_id",
    "agent.name",
    "agent.version",
    "started_at",
    "ended_at",
    "status",
    "steps[].source",
    "steps[].timestamp",
    "steps[].model_name",
)
"""What every trace holds, whatever ``capture`` says."""


def signing_key_secret(name: str) -> str:
    """The secret a project keeps an Agent's signing key in, such as ``SUPPORT_BOT_SIGNING_KEY``.

    Returns:
        The secret's name.
    """
    return f"{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_').upper()}_SIGNING_KEY"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentSection(_Section):
    """Who the agent is. ``name`` and ``version`` label every trace."""

    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    model: str = Field(default="", max_length=200)
    """The label runs report as their model, such as ``acme/takeoff-v3``."""
    url: str | None = None
    """Where Plural Jobs send each signed episode, over https. Needed only to be
    evaluated in Jobs; tracing alone works without it."""
    signing_key: str = ""
    """The secret the project that runs Jobs keeps the signing key in, never the key.
    Defaults to the Agent's name, as ``SUPPORT_BOT_SIGNING_KEY``. The service reads
    the same key from ``PLURAL_SIGNING_KEY``."""
    ca_bundle: str | None = None
    """A PEM CA file that Jobs trust for this service's certificate, when it is private."""

    @model_validator(mode="before")
    @classmethod
    def _default_secret(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value.get("signing_key") and value.get("name"):
            return {**value, "signing_key": signing_key_secret(str(value["name"]))}
        return value

    @field_validator("signing_key")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value.upper().startswith("PLURAL_"):
            raise ValueError(
                "signing_key names the secret the project that runs Jobs keeps the key in, "
                "and names starting with PLURAL_ are reserved. Use one such as "
                "SUPPORT_BOT_SIGNING_KEY; this service still reads the key from "
                "PLURAL_SIGNING_KEY."
            )
        return value


class PluralSection(_Section):
    """Where traces go."""

    api_key: str = "PLURAL_API_KEY"
    """The environment variable holding a Plural API key. Never the key."""
    project: str | None = None
    """The project id or slug, when the key is not scoped to one."""
    api_url: str | None = None
    """The Plural API, for a self-hosted install. Defaults to ``PLURAL_API_URL``."""


class FlushPolicy(_Section):
    """When a run's trace is written.

    ``end`` writes it once, when the run finishes. ``interval`` also writes it
    every ``interval_seconds`` while the run is going, and ``steps`` every
    ``every_steps`` steps, so a long run can be watched live. Each write
    replaces the last until the run finishes.
    """

    mode: Literal["end", "interval", "steps"] = "end"
    interval_seconds: float = Field(default=10.0, ge=1.0, le=3600.0)
    every_steps: int = Field(default=20, ge=1, le=10_000)

    @classmethod
    def parse(cls, value: FlushPolicy | str | Mapping[str, Any]) -> FlushPolicy:
        """Read a policy from ``end``, ``interval:5``, ``steps:10``, or a mapping.

        Returns:
            The policy.

        Raises:
            ConfigurationError: When the value names no policy.
        """
        if isinstance(value, FlushPolicy):
            return value
        if isinstance(value, Mapping):
            return cls.model_validate(dict(value))
        mode, _, amount = value.strip().partition(":")
        try:
            if mode == "end" and not amount:
                return cls(mode="end")
            if mode == "interval":
                return cls(mode="interval", interval_seconds=float(amount or 10))
            if mode == "steps":
                return cls(mode="steps", every_steps=int(amount or 20))
        except (ValueError, ValidationError) as exc:
            raise ConfigurationError(f"Flush policy {value!r} is out of range: {exc}") from None
        raise ConfigurationError(
            f"Flush policy {value!r} is not one of end, interval:SECONDS, or steps:COUNT."
        )


class Capture(_Section):
    """Which optional fields a trace holds. Turn off what must never leave the service."""

    messages: bool = True
    """The text of user and agent messages."""
    system_prompt: bool = True
    reasoning: bool = True
    """A model's reasoning, when it reports any."""
    tool_arguments: bool = True
    tool_results: bool = True
    usage: bool = True
    """Tokens, cost, and latency of each model call."""
    metadata: bool = True
    """Values the agent attaches with ``run.metadata``."""


class TracingSection(_Section):
    """How runs are traced."""

    enabled: bool = True
    production: bool = True
    """Trace runs outside Plural Jobs too, as production traces of this agent.
    Runs inside a Job are always traced to that Job."""
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    """The share of production runs kept. Job runs are always kept."""
    flush: FlushPolicy = Field(default_factory=FlushPolicy)
    capture: Capture = Field(default_factory=Capture)
    redact: tuple[str, ...] = ()
    """Regular expressions replaced with ``[REDACTED]`` in every string written."""
    max_trace_bytes: int = Field(default=4_000_000, ge=10_000, le=16_000_000)
    """Steps past this size are dropped, and the trace says how many."""
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("flush", mode="before")
    @classmethod
    def _flush(cls, value: Any) -> Any:
        return FlushPolicy.parse(value) if isinstance(value, str) else value


class AgentConfig(_Section):
    """The whole of ``plural-agent.yaml``."""

    agent: AgentSection
    plural: PluralSection = Field(default_factory=PluralSection)
    tracing: TracingSection = Field(default_factory=TracingSection)

    @classmethod
    def load(
        cls, path: str | Path | None = None, *, environ: Mapping[str, str] | None = None
    ) -> AgentConfig:
        """Read the config, then apply ``PLURAL_TRACE_*`` overrides.

        Args:
            path: The file. Defaults to ``PLURAL_AGENT_CONFIG``, then
                ``plural-agent.yaml`` in the working directory.
            environ: Environment to read; defaults to ``os.environ``.

        Returns:
            The config.

        Raises:
            ConfigurationError: When the file is missing or invalid.
        """
        env = os.environ if environ is None else environ
        source = Path(path or env.get(CONFIG_VARIABLE) or CONFIG_FILE)
        try:
            data = yaml.safe_load(source.read_text("utf-8")) or {}
        except FileNotFoundError:
            raise ConfigurationError(
                f"{source} does not exist. Run `plural external init` to write one."
            ) from None
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"{source} is not valid YAML: {exc}") from None
        try:
            config = cls.model_validate(data)
        except ValidationError as exc:
            raise ConfigurationError(f"{source} is invalid:\n{exc}") from None
        return config.with_environment(env)

    def with_environment(self, environ: Mapping[str, str]) -> AgentConfig:
        """Apply ``PLURAL_TRACE_*`` and ``PLURAL_AGENT_VERSION`` overrides.

        Returns:
            A copy with the overrides applied.

        Raises:
            ConfigurationError: When an override has the wrong form.
        """
        tracing: dict[str, Any] = {}
        for variable, field in (
            ("PLURAL_TRACE_ENABLED", "enabled"),
            ("PLURAL_TRACE_PRODUCTION", "production"),
        ):
            if variable in environ:
                tracing[field] = _flag(variable, environ[variable])
        if "PLURAL_TRACE_SAMPLE_RATE" in environ:
            tracing["sample_rate"] = environ["PLURAL_TRACE_SAMPLE_RATE"]
        if "PLURAL_TRACE_FLUSH" in environ:
            tracing["flush"] = FlushPolicy.parse(environ["PLURAL_TRACE_FLUSH"])
        agent: dict[str, Any] = {}
        if environ.get("PLURAL_AGENT_VERSION"):
            agent["version"] = environ["PLURAL_AGENT_VERSION"]
        if not tracing and not agent:
            return self
        try:
            return AgentConfig.model_validate(
                {
                    **self.model_dump(),
                    "agent": {**self.agent.model_dump(), **agent},
                    "tracing": {**self.tracing.model_dump(), **tracing},
                }
            )
        except ValidationError as exc:
            raise ConfigurationError(f"A PLURAL_TRACE_* override is invalid:\n{exc}") from None

    def studio(self, environ: Mapping[str, str] | None = None) -> Studio:
        """The Plural API, with the key in ``plural.api_key``.

        Returns:
            The client.

        Raises:
            ConfigurationError: When that environment variable is not set.
        """
        from plural.config import resolve_gateway_url
        from plural.studio import Studio, studio_base_url

        env = os.environ if environ is None else environ
        variable = self.plural.api_key
        key = env.get(variable, "")
        if not key:
            raise ConfigurationError(
                f"Tracing to Plural needs a Plural API key in {variable}. Set it where the agent "
                "runs, or set tracing.production to false to trace only Plural Jobs."
            )
        api = self.plural.api_url or env.get("PLURAL_API_URL")
        root = studio_base_url(api) if api else studio_base_url(resolve_gateway_url(None, env))
        return Studio(api_root=root, token=key, project=self.plural.project)


def _flag(variable: str, value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{variable} must be true or false, not {value!r}.")


def render_template(
    *, name: str, version: str = "0.1.0", model: str = "", url: str | None = None
) -> str:
    """The commented ``plural-agent.yaml`` that ``plural external init`` writes.

    Returns:
        The YAML text.
    """
    return f"""\
# How this agent registers with Plural and traces its runs.
# Docs: https://pluralintel.com/docs/project/external-tracing

agent:
  # Required: the Agent's name in Plural, and your release label. Set
  # PLURAL_AGENT_VERSION on each deploy to override the version.
  name: {_scalar(name)}
  version: {_scalar(version)}
  # The label runs report as their model, such as acme/takeoff-v3.
  model: {_scalar(model)}
  # Where Plural Jobs send each signed episode, over https. Needed only to be
  # evaluated in Jobs; tracing alone works without it.
  url: {_scalar(url) if url else "null"}
  # The secret the project that runs Jobs keeps the signing key in, never the key.
  # This service reads the same key from PLURAL_SIGNING_KEY.
  signing_key: {signing_key_secret(name)}
  ca_bundle: null   # a PEM CA file Jobs trust, for a service with a private certificate

plural:
  api_key: PLURAL_API_KEY   # the env var holding your Plural API key, never the key
  project: null             # project id or slug, when the key is not scoped to one
  api_url: null             # for a self-hosted Plural; defaults to PLURAL_API_URL

tracing:
  enabled: true             # PLURAL_TRACE_ENABLED overrides it
  production: true          # trace runs outside Plural Jobs too (PLURAL_TRACE_PRODUCTION)
  sample_rate: 1.0          # share of production runs kept; Job runs are always kept
  # When a trace is written: end (once, when the run finishes), interval:SECONDS,
  # or steps:COUNT, which also write it while the run is going. PLURAL_TRACE_FLUSH
  # overrides it, and so does Tracer.run(flush=...).
  flush: end
  # Always written: {", ".join(REQUIRED_FIELDS)}.
  # Turn off what must never leave this service:
  capture:
    messages: true          # user and agent message text
    system_prompt: true
    reasoning: true         # a model's reasoning, when it reports any
    tool_arguments: true
    tool_results: true
    usage: true             # tokens, cost, and latency of each model call
    metadata: true          # values attached with run.metadata(...)
  redact: []                # regular expressions replaced with [REDACTED] everywhere
  max_trace_bytes: 4000000  # steps past this are dropped, and the trace says how many
  tags: {{}}
"""


def _scalar(value: str) -> str:
    return yaml.safe_dump(value, width=1000).strip().removesuffix("...").strip()


__all__ = [
    "CONFIG_FILE",
    "CONFIG_VARIABLE",
    "REQUIRED_FIELDS",
    "AgentConfig",
    "AgentSection",
    "Capture",
    "FlushPolicy",
    "PluralSection",
    "TracingSection",
    "render_template",
    "signing_key_secret",
]
