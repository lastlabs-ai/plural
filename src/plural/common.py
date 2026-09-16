"""Dependency-safe primitives shared by schema-v2 domain contracts."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMANTIC_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_UNORDERED_KEYS = frozenset(
    {
        "allowed_capabilities",
        "allowed_harness_capabilities",
        "allowed_targets",
        "capabilities",
        "declared",
        "denied",
        "denied_capabilities",
        "enforced",
        "extra_capabilities",
        "granted",
        "granted_harness_capabilities",
        "targets",
    }
)


def _sort_unordered(value: Any) -> Any:
    if isinstance(value, dict):
        payload = {key: _sort_unordered(item) for key, item in value.items()}
        for key in _UNORDERED_KEYS:
            item = payload.get(key)
            if isinstance(item, list):
                payload[key] = sorted(
                    item,
                    key=lambda entry: json.dumps(
                        entry, sort_keys=True, default=str, allow_nan=False
                    ),
                )
        return payload
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_sort_unordered(item) for item in value),
            key=lambda entry: json.dumps(entry, sort_keys=True, default=str, allow_nan=False),
        )
    if isinstance(value, (list, tuple)):
        return [_sort_unordered(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for content identity and studio transport."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    else:
        value = to_jsonable_python(value, exclude_none=False)
    return json.dumps(
        _sort_unordered(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    """Return a SHA-256 content digest."""
    return f"sha256:{hashlib.sha256(canonical_json(value).encode()).hexdigest()}"


def stable_id(prefix: str, value: Any) -> str:
    """Return a compact deterministic identifier."""
    return f"{prefix}_{content_hash(value).removeprefix('sha256:')[:24]}"


def semantic_version(value: str) -> str:
    """Validate an ordinary semantic version.

    Returns:
        The unchanged semantic version.
    """
    if SEMANTIC_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("version must be a semantic version such as '1.0.0'")
    return value


class FrozenModel(BaseModel):
    """Strict immutable base for public domain objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ErrorCode(str, Enum):
    """Stable execution failure categories."""

    AUTHENTICATION = "authentication"
    CONFIGURATION = "configuration"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    HARNESS_FAILED = "harness_failed"
    PROTOCOL_FAILED = "protocol_failed"
    ENVIRONMENT_FAILED = "environment_failed"
    VERIFIER_FAILED = "verifier_failed"
    EVIDENCE_MISSING = "evidence_missing"
    ARTIFACT_FAILED = "artifact_failed"
    LOCK_INCOMPATIBLE = "lock_incompatible"
    TITO_UNSUPPORTED = "tito_unsupported"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class ExecutionTarget(str, Enum):
    """Execution isolation class."""

    LOCAL = "local"
    DOCKER = "docker"
    REMOTE = "remote"


class HarnessCapability(str, Enum):
    """A capability requested by an agent harness."""

    SHELL = "shell"
    FILE_READ = "file_read"
    FILE_EDIT = "file_edit"
    CODE_EXECUTION = "code_execution"
    WEB_SEARCH = "web_search"
    BROWSER = "browser"
    NETWORK_FETCH = "network_fetch"
    MCP = "mcp"
    SUBAGENTS = "subagents"
    PERSISTENCE = "persistence"


class PackageSource(FrozenModel):
    """Immutable package source."""

    kind: Literal["local", "oci", "archive"]
    uri: str = Field(min_length=1)
    digest: str | None = None
    trusted: bool = False
    unsafe_local: bool = False

    @field_validator("digest")
    @classmethod
    def _valid_digest(cls, value: str | None) -> str | None:
        if value is not None and SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must be sha256:<64 lowercase hex characters>")
        return value

    @model_validator(mode="after")
    def _locked(self) -> PackageSource:
        if self.kind != "local" and self.digest is None:
            raise ValueError("nonlocal package sources require an immutable digest")
        if self.kind == "local" and self.digest is None and not self.unsafe_local:
            raise ValueError("unsigned local package source requires unsafe_local=true")
        if self.kind != "local" and self.unsafe_local:
            raise ValueError("unsafe_local is valid only for local sources")
        return self


class FileDeclaration(FrozenModel):
    """A file emitted or consumed by a package."""

    path: str = Field(min_length=1)
    required: bool = True
    media_type: str = "application/octet-stream"

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        from plural.sandbox.models import safe_relative_path

        return safe_relative_path(value)


class HarnessDefinition(FrozenModel):
    """Versioned executable harness contract."""

    schema_version: Literal["2"] = "2"
    name: str = Field(min_length=1)
    revision: str = Field(
        default="0.1.0",
        min_length=1,
        validation_alias=AliasChoices("revision", "version"),
    )
    description: str = ""
    protocol: Literal["plural-harness-v1", "acp"] = "plural-harness-v1"
    protocol_adapter: Literal["acp-client-v1"] | None = None
    implementation: Literal["declared", "runnable"] = "declared"
    command: tuple[str, ...] = ()
    setup: tuple[tuple[str, ...], ...] = ()
    requirements: tuple[str, ...] = ()
    capabilities: frozenset[HarnessCapability] = frozenset()
    supported_models: tuple[str, ...] = ("*",)
    auth_modes: tuple[Literal["environment", "api_key", "oauth", "none"], ...] = ("environment",)
    secret_names: tuple[str, ...] = ()
    environment_names: tuple[str, ...] = ()
    healthcheck: tuple[str, ...] | None = None
    trajectory_path: str | None = None
    outputs: tuple[FileDeclaration, ...] = ()
    artifacts: tuple[FileDeclaration, ...] = ()
    supports_tito: bool = False
    tito_path: str | None = None

    @field_validator(
        "command",
        "requirements",
        "supported_models",
        "secret_names",
        "environment_names",
        "healthcheck",
    )
    @classmethod
    def _nonempty_items(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("items must be non-empty strings")
        return value

    @model_validator(mode="after")
    def _valid_definition(self) -> HarnessDefinition:
        if self.protocol == "acp" and self.protocol_adapter != "acp-client-v1":
            raise ValueError("protocol='acp' requires protocol_adapter='acp-client-v1'")
        if self.protocol != "acp" and self.protocol_adapter is not None:
            raise ValueError("protocol_adapter is valid only for protocol='acp'")
        declared = {item.path for item in self.artifacts}
        if self.trajectory_path is not None and self.trajectory_path not in declared:
            raise ValueError("trajectory_path must be declared in artifacts")
        if self.supports_tito and not self.tito_path:
            raise ValueError("supports_tito=true requires tito_path")
        if self.tito_path is not None and self.tito_path not in declared:
            raise ValueError("tito_path must be declared in artifacts")
        if self.implementation == "runnable" and not self.command:
            raise ValueError("runnable harnesses require a command")
        for command in self.setup:
            if not command or any(not item.strip() for item in command):
                raise ValueError("setup commands must be non-empty argv tuples")
        return self


class HarnessPackage(FrozenModel):
    """Content-addressed harness definition and source."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    definition: HarnessDefinition = Field(validation_alias=AliasChoices("definition", "manifest"))
    source: PackageSource

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_manifest_key(cls, value: Any) -> Any:
        if isinstance(value, dict) and "definition" not in value and "manifest" in value:
            payload = dict(value)
            payload["definition"] = payload.pop("manifest")
            return payload
        return value

    @property
    def content_hash(self) -> str:
        """Stable package hash."""
        return content_hash(self)

    @property
    def package_id(self) -> str:
        """Stable package identifier."""
        return stable_id("hrn", self)


class HarnessBinding(FrozenModel):
    """Exact harness revision."""

    name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    digest: str

    @field_validator("digest")
    @classmethod
    def _valid_digest(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must be sha256:<64 lowercase hex characters>")
        return value

    @classmethod
    def from_package(cls, package: HarnessPackage) -> HarnessBinding:
        """Create an exact binding.

        Returns:
            The pinned Harness binding.
        """
        return cls(
            name=package.definition.name,
            revision=package.definition.revision,
            digest=package.source.digest or package.content_hash,
        )


class RoutingSpec(FrozenModel):
    """Portable model routing configuration."""

    provider: str | None = None
    fallback_models: tuple[str, ...] = ()
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, gt=0)


__all__ = [
    "ErrorCode",
    "ExecutionTarget",
    "FileDeclaration",
    "FrozenModel",
    "HarnessBinding",
    "HarnessCapability",
    "HarnessDefinition",
    "HarnessPackage",
    "PackageSource",
    "RoutingSpec",
    "SHA256_PATTERN",
    "SEMANTIC_VERSION_PATTERN",
    "canonical_json",
    "content_hash",
    "semantic_version",
    "stable_id",
]
