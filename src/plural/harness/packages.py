"""First-party harness profiles and vendor adapter installation recipes."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from plural.domain import (
    FileDeclaration,
    HarnessCapability,
    HarnessDefinition,
    HarnessPackage,
    PackageSource,
)
from plural.harness.retrieval import tree_digest

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


class HarnessRecipe(BaseModel):
    """Metadata-only recipe; vendor code is never bundled by Plural."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    definition: HarnessDefinition
    install: tuple[tuple[str, ...], ...]
    adapter_source: str
    notes: str


def _builtin(profile: str, capabilities: frozenset[HarnessCapability]) -> HarnessPackage:
    definition = HarnessDefinition(
        name=profile,
        revision="1.0.0",
        description=f"Plural first-party {profile} harness profile.",
        implementation="runnable",
        command=("python", "native_runner.py", profile),
        requirements=(
            "OpenAI-compatible POST /chat/completions endpoint",
            "PLURAL_API_KEY or OPENAI_API_KEY unless explicitly unauthenticated",
        ),
        capabilities=capabilities,
        secret_names=("PLURAL_API_KEY", "OPENAI_API_KEY"),
        environment_names=(
            "PLURAL_GATEWAY_URL",
            "OPENAI_BASE_URL",
            "PLURAL_ALLOW_NO_AUTH",
        ),
        auth_modes=("environment", "none"),
        outputs=(FileDeclaration(path="result.json"),),
        artifacts=(FileDeclaration(path="trajectory.jsonl"),),
        trajectory_path="trajectory.jsonl",
    )
    source = Path(__file__).parent
    digest = tree_digest(source)
    return HarnessPackage(
        definition=definition,
        source=PackageSource(
            kind="local",
            uri=str(source),
            digest=digest,
        ),
    )


def native_chat_v1() -> HarnessPackage:
    """Return the native chat request/response profile."""
    return _builtin("native.chat.v1", frozenset())


def native_actions_v1() -> HarnessPackage:
    """Return the native environment-action profile."""
    return _builtin(
        "native.actions.v1",
        frozenset({HarnessCapability.SHELL, HarnessCapability.FILE_READ}),
    )


BUILTIN_PROFILES = {
    "native.chat.v1": native_chat_v1,
    "native.actions.v1": native_actions_v1,
}


def _declared(
    name: str,
    *,
    capabilities: frozenset[HarnessCapability],
    supported_models: tuple[str, ...] = ("*",),
    auth_modes: tuple[str, ...] = ("environment",),
    secret_names: tuple[str, ...] = (),
    requirements: tuple[str, ...] = (),
) -> HarnessDefinition:
    return HarnessDefinition(
        name=name,
        implementation="declared",
        capabilities=capabilities,
        supported_models=supported_models,
        auth_modes=auth_modes,  # type: ignore[arg-type]
        secret_names=secret_names,
        requirements=requirements,
    )


DECLARED_HARNESSES = {
    "hermes": _declared(
        "hermes",
        capabilities=_CODE_CAPABILITIES,
        secret_names=("OPENROUTER_API_KEY",),
        requirements=("Installed `hermes` executable on PATH",),
    ),
    "claude-code": _declared(
        "claude-code",
        capabilities=_CODE_CAPABILITIES,
        supported_models=("anthropic/*",),
        auth_modes=("environment", "oauth"),
        secret_names=("ANTHROPIC_API_KEY",),
        requirements=("Installed `claude` executable on PATH",),
    ),
    "codex": _declared(
        "codex",
        capabilities=_CODE_CAPABILITIES,
        supported_models=("openai/*",),
        auth_modes=("environment", "oauth"),
        secret_names=("OPENAI_API_KEY",),
        requirements=("Installed `codex` executable on PATH",),
    ),
    "cursor": _declared(
        "cursor",
        capabilities=_CODE_CAPABILITIES,
        requirements=("Installed Cursor agent CLI on PATH",),
    ),
}


ADAPTER_RECIPES = {
    "claude-code": HarnessRecipe(
        name="claude-code",
        definition=DECLARED_HARNESSES["claude-code"],
        install=(("npm", "install", "--global", "@anthropic-ai/claude-code"),),
        adapter_source=str(Path(__file__).with_name("vendor_adapter.py")),
        notes="Declared-only in this release; Plural ships only the protocol adapter source.",
    ),
    "codex": HarnessRecipe(
        name="codex",
        definition=DECLARED_HARNESSES["codex"],
        install=(("npm", "install", "--global", "@openai/codex"),),
        adapter_source=str(Path(__file__).with_name("vendor_adapter.py")),
        notes="Declared-only in this release; Plural ships only the protocol adapter source.",
    ),
    "hermes-agent": HarnessRecipe(
        name="hermes-agent",
        definition=DECLARED_HARNESSES["hermes"],
        install=(("pip", "install", "hermes-agent"),),
        adapter_source=str(Path(__file__).with_name("vendor_adapter.py")),
        notes="Declared-only in this release; Plural ships only the protocol adapter source.",
    ),
}


__all__ = [
    "ADAPTER_RECIPES",
    "BUILTIN_PROFILES",
    "DECLARED_HARNESSES",
    "HarnessRecipe",
    "native_actions_v1",
    "native_chat_v1",
]
