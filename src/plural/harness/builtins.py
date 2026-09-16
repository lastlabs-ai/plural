"""Built-in vendor Harness registry: names, option schemas, and package factories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from plural.common import (
    FileDeclaration,
    FrozenModel,
    HarnessCapability,
    HarnessDefinition,
    HarnessPackage,
    PackageSource,
)
from plural.harness.retrieval import tree_digest

BUILTIN_HARNESS_NAMES = ("hermes", "claude-code", "codex")
LEGACY_DECLARED_HARNESS_NAMES = frozenset({*BUILTIN_HARNESS_NAMES, "cursor"})

_CODE_CAPABILITIES = frozenset(
    {
        HarnessCapability.SHELL,
        HarnessCapability.FILE_READ,
        HarnessCapability.FILE_EDIT,
        HarnessCapability.CODE_EXECUTION,
        HarnessCapability.WEB_SEARCH,
        HarnessCapability.BROWSER,
        HarnessCapability.NETWORK_FETCH,
        HarnessCapability.MCP,
        HarnessCapability.SUBAGENTS,
        HarnessCapability.PERSISTENCE,
    }
)
_ORCHESTRATED_SECRETS = ("PLURAL_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
_ORCHESTRATED_ENVIRONMENT = (
    "PLURAL_GATEWAY_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "PLURAL_ALLOW_NO_AUTH",
    "PLURAL_RUNTIME_PROVIDER",
    "PLURAL_HARNESS_NAME",
    "PLURAL_HARNESS_VERSION",
)


class BuiltinHarnessOptions(FrozenModel):
    """Shared options accepted by every built-in Harness."""

    version: str | None = Field(
        default=None,
        description="Override the release-pinned CLI version.",
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="Native CLI config as an inline mapping. File paths are loaded first.",
    )


class ClaudeCodeOptions(BuiltinHarnessOptions):
    """Options for the Claude Code built-in."""

    reasoning_effort: Literal["low", "medium", "high"] | None = Field(
        default=None,
        description="Claude Code reasoning effort. Omitted values use the CLI default.",
    )
    permission_mode: Literal["acceptEdits", "bypassPermissions", "default", "plan"] | None = Field(
        default=None,
        description="Claude Code permission mode.",
    )
    max_turns: int | None = Field(
        default=None,
        gt=0,
        description="Maximum Claude Code turns for one Trial.",
    )


class CodexOptions(BuiltinHarnessOptions):
    """Options for the Codex built-in."""

    reasoning_effort: Literal["low", "medium", "high"] | None = Field(
        default=None,
        description="Codex reasoning effort. Omitted values use the CLI default.",
    )
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] | None = Field(
        default=None,
        description="Codex sandbox mode inside the Runtime.",
    )


class HermesOptions(BuiltinHarnessOptions):
    """Options for the Hermes built-in."""


@dataclass(frozen=True)
class BuiltinHarnessSpec:
    """One built-in vendor Harness."""

    name: str
    description: str
    options_model: type[BuiltinHarnessOptions]
    pinned_version: str
    supported_models: tuple[str, ...]
    capabilities: frozenset[HarnessCapability]
    npm_package: str | None = None
    pip_package: str | None = None
    secret_names: tuple[str, ...] = _ORCHESTRATED_SECRETS
    environment_names: tuple[str, ...] = _ORCHESTRATED_ENVIRONMENT
    requirements: tuple[str, ...] = (
        "Network access so the Runtime can install the pinned CLI",
        "Job(client=...) or Job(api_key=...) for model authentication",
    )


BUILTIN_HARNESSES: dict[str, BuiltinHarnessSpec] = {
    "hermes": BuiltinHarnessSpec(
        name="hermes",
        description="Nous Hermes CLI. Plural installs the pinned package in the Runtime.",
        options_model=HermesOptions,
        pinned_version="0.19.0",
        supported_models=("*",),
        capabilities=_CODE_CAPABILITIES,
        pip_package="hermes-agent",
    ),
    "claude-code": BuiltinHarnessSpec(
        name="claude-code",
        description="Anthropic Claude Code CLI. Plural installs the pinned CLI in the Runtime.",
        options_model=ClaudeCodeOptions,
        pinned_version="2.1.236",
        supported_models=("anthropic/*",),
        capabilities=_CODE_CAPABILITIES,
        npm_package="@anthropic-ai/claude-code",
    ),
    "codex": BuiltinHarnessSpec(
        name="codex",
        description="OpenAI Codex CLI. Plural installs the pinned CLI in the Runtime.",
        options_model=CodexOptions,
        pinned_version="0.153.2",
        supported_models=("openai/*",),
        capabilities=_CODE_CAPABILITIES,
        npm_package="@openai/codex",
    ),
}
_BUILTIN_CLASSES = {
    "hermes": "HermesHarness",
    "claude-code": "ClaudeCodeHarness",
    "codex": "CodexHarness",
}


def list_builtin_harnesses() -> tuple[BuiltinHarnessSpec, ...]:
    """Return built-in Harnesses in stable name order."""
    return tuple(BUILTIN_HARNESSES[name] for name in BUILTIN_HARNESS_NAMES)


def get_builtin(name: str) -> BuiltinHarnessSpec:
    """Return one built-in spec.

    Raises:
        ValueError: If the name is not a built-in Harness.
    """
    spec = BUILTIN_HARNESSES.get(name)
    if spec is None:
        available = ", ".join(BUILTIN_HARNESS_NAMES)
        raise ValueError(
            f"Unknown built-in Harness {name!r}.\n"
            f"Available names: {available}.\n"
            "Omit harness to use Plural's native loop, or pass a custom Harness(...)."
        )
    return spec


def builtin_schema(name: str) -> dict[str, Any]:
    """Return the JSON Schema for one built-in's accepted kwargs."""
    spec = get_builtin(name)
    schema = spec.options_model.model_json_schema()
    schema["title"] = spec.name
    schema["description"] = spec.description
    schema["x-pinned-version"] = spec.pinned_version
    schema["x-supported-models"] = list(spec.supported_models)
    return schema


def model_supported(model: str, patterns: tuple[str, ...]) -> bool:
    """Return whether a catalog model ID matches a built-in's supported patterns."""
    for pattern in patterns:
        if pattern == "*":
            return True
        if pattern.endswith("/*") and model.startswith(pattern[:-1]):
            return True
        if model == pattern:
            return True
    return False


def normalize_config(value: Any, *, root: Path | None = None) -> dict[str, Any] | None:
    """Load a native config from a mapping, JSON text, or file path."""
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise ValueError("harness_kwargs.config must be a mapping, JSON object, or file path")
    text = value.strip()
    if not text:
        return None
    if text[0] in "{[":
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError("harness_kwargs.config JSON must be an object")
        return loaded
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (root or Path.cwd()) / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"harness_kwargs.config file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".json"} or raw.lstrip().startswith("{"):
        loaded = json.loads(raw)
    else:
        import yaml

        loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise ValueError(f"harness_kwargs.config file must contain a mapping: {path}")
    return loaded


def normalize_kwargs(
    name: str,
    kwargs: dict[str, Any] | None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate and normalize kwargs for a built-in Harness.

    Returns:
        A JSON-ready mapping that always includes the resolved CLI version.
    """
    spec = get_builtin(name)
    payload = dict(kwargs or {})
    if "config" in payload:
        payload["config"] = normalize_config(payload["config"], root=root)
    try:
        options = spec.options_model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid harness_kwargs for {name!r}: {exc}") from exc
    normalized = options.model_dump(mode="json", exclude_none=True)
    normalized["version"] = options.version or spec.pinned_version
    return normalized


def resolve_builtin_package(name: str, kwargs: dict[str, Any] | None = None) -> HarnessPackage:
    """Build the runnable package for a validated built-in Harness."""
    spec = get_builtin(name)
    options = normalize_kwargs(name, kwargs)
    version = str(options["version"])
    source = Path(__file__).parent
    definition = HarnessDefinition(
        name=spec.name,
        revision=version,
        description=spec.description,
        implementation="runnable",
        command=(
            "python",
            "-m",
            "plural.harness.class_runner",
            f"vendor_harnesses.py:{_BUILTIN_CLASSES[name]}",
        ),
        setup=(("python", "install.py", spec.name, version),),
        requirements=spec.requirements,
        capabilities=spec.capabilities,
        supported_models=spec.supported_models,
        auth_modes=("environment", "none"),
        secret_names=spec.secret_names,
        environment_names=spec.environment_names,
        outputs=(FileDeclaration(path="result.json"),),
        artifacts=(
            FileDeclaration(path="trajectory.jsonl"),
            FileDeclaration(path="logs.txt", required=False),
        ),
        trajectory_path="trajectory.jsonl",
    )
    return HarnessPackage(
        definition=definition,
        source=PackageSource(
            kind="local",
            uri=str(source),
            digest=tree_digest(source),
            trusted=True,
        ),
    )


def legacy_declared_harness_error(name: str) -> ValueError:
    """Return the migration error for an old declared-only vendor Harness."""
    if name in BUILTIN_HARNESSES:
        return ValueError(
            f"Harness {name!r} is a built-in now.\n"
            f"Attach it with Agent(harness={name!r}) or YAML harness: {name}.\n"
            "Use Harness(...) only for a custom executable loop."
        )
    return ValueError(
        f"Harness {name!r} is no longer a declared-only vendor recipe and is not a built-in.\n"
        f"Available built-ins: {', '.join(BUILTIN_HARNESS_NAMES)}.\n"
        "Use Harness(...) for a custom executable loop."
    )


def summarize_builtin(spec: BuiltinHarnessSpec) -> dict[str, Any]:
    """Return a CLI-safe summary of one built-in."""
    return {
        "name": spec.name,
        "description": spec.description,
        "version": spec.pinned_version,
        "supported_models": list(spec.supported_models),
        "capabilities": sorted(item.value for item in spec.capabilities),
    }


__all__ = [
    "BUILTIN_HARNESSES",
    "BUILTIN_HARNESS_NAMES",
    "BuiltinHarnessOptions",
    "BuiltinHarnessSpec",
    "ClaudeCodeOptions",
    "CodexOptions",
    "HermesOptions",
    "LEGACY_DECLARED_HARNESS_NAMES",
    "builtin_schema",
    "get_builtin",
    "legacy_declared_harness_error",
    "list_builtin_harnesses",
    "model_supported",
    "normalize_config",
    "normalize_kwargs",
    "resolve_builtin_package",
    "summarize_builtin",
]
