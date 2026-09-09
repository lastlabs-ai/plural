"""First-party harness profiles and vendor adapter installation recipes."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from plural.domain import FileDeclaration, HarnessManifest, HarnessPackage, PackageSource
from plural.harness.retrieval import tree_digest


class HarnessRecipe(BaseModel):
    """Metadata-only recipe; vendor code is never bundled by Plural."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    manifest: HarnessManifest
    install: tuple[tuple[str, ...], ...]
    adapter_source: str
    notes: str


def _builtin(profile: str, capabilities: tuple[str, ...]) -> HarnessPackage:
    manifest = HarnessManifest(
        name=profile,
        version="1.0.0",
        description=f"Plural first-party {profile} harness profile.",
        command=("python", "builtin_runner.py", profile),
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
        manifest=manifest,
        source=PackageSource(
            kind="local",
            uri=str(source),
            digest=digest,
        ),
    )


def chat_v1() -> HarnessPackage:
    """Return the basic chat request/response profile."""
    return _builtin("chat.v1", ("chat",))


def tool_loop_v1() -> HarnessPackage:
    """Return the iterative tool-use profile."""
    return _builtin("tool-loop.v1", ("chat", "tools", "trajectory"))


def code_task_v1() -> HarnessPackage:
    """Return the code-editing profile."""
    return _builtin("code-task.v1", ("chat", "tools", "filesystem", "trajectory"))


BUILTIN_PROFILES = {
    "chat.v1": chat_v1,
    "tool-loop.v1": tool_loop_v1,
    "code-task.v1": code_task_v1,
}


ADAPTER_RECIPES = {
    "claude-code": HarnessRecipe(
        name="claude-code",
        manifest=HarnessManifest(
            name="claude-code",
            command=("python", "vendor_adapter.py", "claude-code"),
            requirements=("Installed `claude` executable on PATH",),
            capabilities=("chat", "tools", "filesystem", "trajectory"),
            supported_models=("anthropic/*",),
            auth_modes=("environment", "oauth"),
            secret_names=("ANTHROPIC_API_KEY",),
            outputs=(FileDeclaration(path="result.json"),),
            artifacts=(FileDeclaration(path="trajectory.jsonl"),),
            trajectory_path="trajectory.jsonl",
        ),
        install=(("npm", "install", "--global", "@anthropic-ai/claude-code"),),
        adapter_source=str(Path(__file__).with_name("vendor_adapter.py")),
        notes="Vendor CLI is separate; Plural ships only the protocol adapter source.",
    ),
    "codex": HarnessRecipe(
        name="codex",
        manifest=HarnessManifest(
            name="codex",
            command=("python", "vendor_adapter.py", "codex"),
            requirements=("Installed `codex` executable on PATH",),
            capabilities=("chat", "tools", "filesystem", "trajectory"),
            supported_models=("openai/*",),
            auth_modes=("environment", "oauth"),
            secret_names=("OPENAI_API_KEY",),
            outputs=(FileDeclaration(path="result.json"),),
            artifacts=(FileDeclaration(path="trajectory.jsonl"),),
            trajectory_path="trajectory.jsonl",
        ),
        install=(("npm", "install", "--global", "@openai/codex"),),
        adapter_source=str(Path(__file__).with_name("vendor_adapter.py")),
        notes="Vendor CLI is separate; Plural ships only the protocol adapter source.",
    ),
    "hermes-agent": HarnessRecipe(
        name="hermes-agent",
        manifest=HarnessManifest(
            name="hermes-agent",
            command=("python", "vendor_adapter.py", "hermes-agent"),
            requirements=("Installed `hermes` executable on PATH",),
            capabilities=("chat", "tools", "filesystem", "trajectory"),
            supported_models=("*",),
            auth_modes=("environment",),
            secret_names=("OPENROUTER_API_KEY",),
            outputs=(FileDeclaration(path="result.json"),),
            artifacts=(FileDeclaration(path="trajectory.jsonl"),),
            trajectory_path="trajectory.jsonl",
        ),
        install=(("pip", "install", "hermes-agent"),),
        adapter_source=str(Path(__file__).with_name("vendor_adapter.py")),
        notes="Vendor agent is separate; Plural ships only the protocol adapter source.",
    ),
}


__all__ = [
    "ADAPTER_RECIPES",
    "BUILTIN_PROFILES",
    "HarnessRecipe",
    "chat_v1",
    "code_task_v1",
    "tool_loop_v1",
]
