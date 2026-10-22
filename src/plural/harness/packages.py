"""First-party native profiles and built-in vendor Harness packages."""

from __future__ import annotations

import hashlib
from pathlib import Path

from plural.common import (
    FileDeclaration,
    HarnessCapability,
    HarnessPackage,
    HarnessProtocol,
    PackageSource,
)
from plural.harness.builtins import (
    BUILTIN_HARNESS_NAMES,
    BUILTIN_HARNESSES,
    builtin_schema,
    get_builtin,
    list_builtin_harnesses,
    resolve_builtin_package,
)
from plural.harness.retrieval import source_digest


def _builtin(profile: str, capabilities: frozenset[HarnessCapability]) -> HarnessPackage:
    definition = HarnessProtocol(
        name=profile,
        revision="1.0.0",
        description=f"Plural first-party {profile} harness profile.",
        implementation="runnable",
        command=("python", "native_runner.py", profile),
        requirements=(
            "OpenAI-compatible POST /chat/completions endpoint",
            "PLURAL_API_KEY unless explicitly unauthenticated",
        ),
        capabilities=capabilities,
        secret_names=("PLURAL_API_KEY",),
        environment_names=(
            "PLURAL_GATEWAY_URL",
            "PLURAL_PROJECT_ID",
            "PLURAL_ALLOW_NO_AUTH",
        ),
        auth_modes=("environment", "none"),
        outputs=(FileDeclaration(path="result.json"),),
        artifacts=(
            FileDeclaration(
                path="episode.jsonl",
                media_type="application/jsonl; profile=plural.episode/v1",
            ),
        ),
    )
    source = Path(__file__).parent
    digest = source_digest(source)
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


EXTERNAL_PROFILE = "external.v1"


def external_v1() -> HarnessPackage:
    """Return the profile of an External Agent, which runs nothing in the Runtime."""
    definition = HarnessProtocol(
        name=EXTERNAL_PROFILE,
        revision="1.0.0",
        description="An agent that runs as its own service and acts over HTTPS.",
        implementation="runnable",
        command=("external",),
        auth_modes=("environment", "none"),
        outputs=(FileDeclaration(path="result.json"),),
        artifacts=(FileDeclaration(path="agent-trace.json", media_type="application/json"),),
    )
    return HarnessPackage(
        definition=definition,
        source=PackageSource(
            kind="local",
            uri=EXTERNAL_PROFILE,
            digest="sha256:" + hashlib.sha256(EXTERNAL_PROFILE.encode()).hexdigest(),
        ),
    )


BUILTIN_PROFILES = {
    "native.chat.v1": native_chat_v1,
    "native.actions.v1": native_actions_v1,
}


__all__ = [
    "BUILTIN_HARNESSES",
    "BUILTIN_HARNESS_NAMES",
    "BUILTIN_PROFILES",
    "EXTERNAL_PROFILE",
    "builtin_schema",
    "external_v1",
    "get_builtin",
    "list_builtin_harnesses",
    "native_actions_v1",
    "native_chat_v1",
    "resolve_builtin_package",
]
