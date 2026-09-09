"""Typed sandbox capabilities, requirements, handles, and results."""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SandboxModel(BaseModel):
    """Strict immutable base for sandbox values."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NetworkMode(str, Enum):
    """Requested sandbox network policy."""

    NONE = "none"
    RESTRICTED = "restricted"
    FULL = "full"


class Capability(str, Enum):
    """Individual controls a provider can enforce."""

    IMAGE = "image"
    BUILD = "build"
    RESOURCES = "resources"
    NETWORK_NONE = "network_none"
    NETWORK_ALLOWLIST = "network_allowlist"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    TIMEOUT = "timeout"
    CANCEL = "cancel"
    PERSISTENCE = "persistence"
    COMPOSE = "compose"
    READ_ONLY_ROOT = "read_only_root"
    WORKING_DIRECTORY = "working_directory"
    ENVIRONMENT = "environment"
    LOG_CAPTURE = "log_capture"


class ProviderCapabilities(SandboxModel):
    """Provider capability declaration used by preflight and runtime doctor."""

    provider: str
    available: bool
    capabilities: frozenset[Capability]
    reason: str | None = None

    def supports(self, capability: Capability) -> bool:
        """Return whether a control is available."""
        return capability in self.capabilities


class ResourceRequirements(SandboxModel):
    """Optional compute limits."""

    cpu: float | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, gt=0)
    pids: int | None = Field(default=None, gt=0)
    disk_mb: int | None = Field(default=None, gt=0)

    @property
    def configured(self) -> bool:
        """Return whether any resource limit was requested."""
        return any(
            value is not None for value in (self.cpu, self.memory_mb, self.pids, self.disk_mb)
        )


class DeclarativeImage(SandboxModel):
    """Portable subset of Daytona's declarative image builder."""

    base: str = Field(min_length=1)
    pip_packages: tuple[str, ...] = ()
    environment: dict[str, str] = Field(default_factory=dict)
    workdir: str | None = None


class SandboxRequirements(SandboxModel):
    """Controls required for one sandbox before it may launch."""

    image: str | None = None
    snapshot: str | None = None
    declarative_image: DeclarativeImage | None = None
    execution_identity: str | None = None
    build_context: str | None = None
    dockerfile: str | None = None
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    network: NetworkMode = NetworkMode.NONE
    network_allowlist: tuple[str, ...] = ()
    timeout_seconds: float | None = Field(default=None, gt=0)
    persistent: bool = False
    compose: bool = False
    read_only_root: bool = False

    @model_validator(mode="after")
    def _network_shape(self) -> SandboxRequirements:
        if self.network_allowlist and self.network is not NetworkMode.RESTRICTED:
            raise ValueError("network_allowlist requires network='restricted'")
        sources = (
            self.image is not None,
            self.snapshot is not None,
            self.declarative_image is not None,
        )
        if sum(sources) > 1:
            raise ValueError("image, snapshot, and declarative_image are mutually exclusive")
        return self

    def required_capabilities(self) -> frozenset[Capability]:
        """Return the controls that must be enforceable."""
        required = {
            Capability.UPLOAD,
            Capability.DOWNLOAD,
            Capability.TIMEOUT,
            Capability.CANCEL,
            Capability.WORKING_DIRECTORY,
            Capability.ENVIRONMENT,
            Capability.LOG_CAPTURE,
        }
        if self.image or self.snapshot or self.declarative_image:
            required.add(Capability.IMAGE)
        if self.build_context:
            required.add(Capability.BUILD)
        if self.resources.configured:
            required.add(Capability.RESOURCES)
        if self.network is NetworkMode.NONE:
            required.add(Capability.NETWORK_NONE)
        elif self.network is NetworkMode.RESTRICTED:
            required.add(Capability.NETWORK_ALLOWLIST)
        if self.persistent:
            required.add(Capability.PERSISTENCE)
        if self.compose:
            required.add(Capability.COMPOSE)
        if self.read_only_root:
            required.add(Capability.READ_ONLY_ROOT)
        return frozenset(required)


class EffectiveSandboxPolicy(SandboxModel):
    """Provider-confirmed requirements captured in receipts."""

    provider: str
    requirements: SandboxRequirements
    enforced: frozenset[Capability]


class SandboxHandle(SandboxModel):
    """Opaque provider sandbox identity."""

    sandbox_id: str
    provider: str
    image_identity: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class FileUpload(SandboxModel):
    """One in-memory file copied into a sandbox."""

    path: str
    data: bytes
    mode: int = Field(default=0o600, ge=0, le=0o777)

    @field_validator("path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        return safe_relative_path(value)


class DownloadedFile(SandboxModel):
    """One file retrieved from a sandbox."""

    path: str
    data: bytes

    @property
    def digest(self) -> str:
        """Return the content digest."""
        return f"sha256:{hashlib.sha256(self.data).hexdigest()}"


class ExecRequest(SandboxModel):
    """One argv-based process invocation."""

    command: tuple[str, ...] = Field(min_length=1)
    cwd: str = "/workspace"
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0)
    stdin: bytes | None = None
    capture_logs: bool = True

    @field_validator("command")
    @classmethod
    def _command_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("command items must be non-empty and contain no NUL")
        return value


class ExecResult(SandboxModel):
    """Captured process completion."""

    exit_code: int
    stdout: bytes = b""
    stderr: bytes = b""
    duration_seconds: float = Field(ge=0)
    timed_out: bool = False


class ProviderDoctor(SandboxModel):
    """Availability report safe for CLI output."""

    name: str
    available: bool
    healthy: bool
    capabilities: tuple[str, ...]
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SandboxError(RuntimeError):
    """Base sandbox lifecycle error."""


class ProviderUnavailableError(SandboxError):
    """Provider dependency, daemon, or credentials are unavailable."""


class CapabilityError(SandboxError):
    """A requested control cannot be enforced."""


class SandboxTimeoutError(SandboxError):
    """A sandbox process exceeded its deadline."""


def safe_relative_path(value: str) -> str:
    """Validate and normalize a sandbox-relative path."""
    if not value or "\x00" in value:
        raise ValueError("path must be non-empty and contain no NUL")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.parts in {(), (".",)}:
        raise ValueError(f"unsafe relative path: {value!r}")
    return str(path)


__all__ = [
    "Capability",
    "CapabilityError",
    "DeclarativeImage",
    "DownloadedFile",
    "EffectiveSandboxPolicy",
    "ExecRequest",
    "ExecResult",
    "FileUpload",
    "NetworkMode",
    "ProviderCapabilities",
    "ProviderDoctor",
    "ProviderUnavailableError",
    "ResourceRequirements",
    "SandboxError",
    "SandboxHandle",
    "SandboxRequirements",
    "SandboxTimeoutError",
    "safe_relative_path",
]
