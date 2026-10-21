"""Typed sandbox capabilities, requirements, handles, and results."""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from plural._deprecation import module_getattr


class SandboxModel(BaseModel):
    """Strict immutable base for sandbox values."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NetworkMode(str, Enum):
    """Requested sandbox network policy.

    Use public, no-network, or allowlist to configure outbound access.
    """

    PUBLIC = "public"
    NO_NETWORK = "no-network"
    ALLOWLIST = "allowlist"
    FULL = "public"
    NONE = "no-network"
    RESTRICTED = "allowlist"

    @classmethod
    def _missing_(cls, value: object) -> NetworkMode | None:
        if not isinstance(value, str):
            return None
        aliases = {
            "public": cls.PUBLIC,
            "full": cls.PUBLIC,
            "no-network": cls.NO_NETWORK,
            "none": cls.NO_NETWORK,
            "allowlist": cls.ALLOWLIST,
            "restricted": cls.ALLOWLIST,
        }
        return aliases.get(value.strip().lower())


class SandboxCapability(str, Enum):
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
    capabilities: frozenset[SandboxCapability]
    reason: str | None = None

    def supports(self, capability: SandboxCapability) -> bool:
        """Return whether a control is available."""
        return capability in self.capabilities


class ResourceRequirements(SandboxModel):
    """Optional compute limits."""

    cpu: float | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, gt=0)
    pids: int | None = Field(default=None, gt=0)
    disk_mb: int | None = Field(default=None, gt=0)
    storage_mb: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _storage_alias(self) -> ResourceRequirements:
        if self.storage_mb is not None and self.disk_mb is None:
            object.__setattr__(self, "disk_mb", self.storage_mb)
        elif self.disk_mb is not None and self.storage_mb is None:
            object.__setattr__(self, "storage_mb", self.disk_mb)
        return self

    @property
    def configured(self) -> bool:
        """Return whether any resource limit was requested."""
        return any(
            value is not None
            for value in (self.cpu, self.memory_mb, self.pids, self.disk_mb, self.storage_mb)
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
    network: NetworkMode = NetworkMode.PUBLIC
    network_allowlist: tuple[str, ...] = ()
    timeout_seconds: float | None = Field(default=None, gt=0)
    persistent: bool = False
    compose: bool = False
    read_only_root: bool = False

    @model_validator(mode="after")
    def _network_shape(self) -> SandboxRequirements:
        if self.network_allowlist and self.network is not NetworkMode.ALLOWLIST:
            raise ValueError("network_allowlist requires network='allowlist'")
        sources = (
            self.image is not None,
            self.snapshot is not None,
            self.declarative_image is not None,
        )
        if sum(sources) > 1:
            raise ValueError("image, snapshot, and declarative_image are mutually exclusive")
        return self

    def required_capabilities(self) -> frozenset[SandboxCapability]:
        """Return the controls that must be enforceable."""
        required = {
            SandboxCapability.UPLOAD,
            SandboxCapability.DOWNLOAD,
            SandboxCapability.TIMEOUT,
            SandboxCapability.CANCEL,
            SandboxCapability.WORKING_DIRECTORY,
            SandboxCapability.ENVIRONMENT,
            SandboxCapability.LOG_CAPTURE,
        }
        if self.image or self.snapshot or self.declarative_image:
            required.add(SandboxCapability.IMAGE)
        if self.build_context:
            required.add(SandboxCapability.BUILD)
        if self.resources.configured:
            required.add(SandboxCapability.RESOURCES)
        if self.network is NetworkMode.NONE:
            required.add(SandboxCapability.NETWORK_NONE)
        elif self.network is NetworkMode.RESTRICTED:
            required.add(SandboxCapability.NETWORK_ALLOWLIST)
        if self.persistent:
            required.add(SandboxCapability.PERSISTENCE)
        if self.compose:
            required.add(SandboxCapability.COMPOSE)
        if self.read_only_root:
            required.add(SandboxCapability.READ_ONLY_ROOT)
        return frozenset(required)


RUNTIME_RENAMES = {
    "network_allowlist": "allowed_hosts",
    "build_timeout_sec": "build_timeout_seconds",
    "resources": "compute",
}
"""Old Runtime field names, accepted on input for one release, and their new names."""


def runtime_hash_payload(runtime: dict[str, Any]) -> dict[str, Any]:
    """A dumped Runtime keyed by its original field names, for content hashing.

    Renaming a field must not change the identity of every Environment and
    Verifier that declares a Runtime.

    Returns:
        A copy with each renamed field under its old name.
    """
    payload = dict(runtime)
    for old, new in RUNTIME_RENAMES.items():
        if new in payload:
            payload[old] = payload.pop(new)
    return payload


def environment_required_capabilities(runtime: Any) -> frozenset[SandboxCapability]:
    """Derive sandbox controls required by an environment runtime declaration."""
    required = {
        SandboxCapability.UPLOAD,
        SandboxCapability.DOWNLOAD,
        SandboxCapability.TIMEOUT,
        SandboxCapability.CANCEL,
        SandboxCapability.WORKING_DIRECTORY,
        SandboxCapability.ENVIRONMENT,
        SandboxCapability.LOG_CAPTURE,
    }
    if (
        getattr(runtime, "image", None)
        or getattr(runtime, "snapshot", None)
        or getattr(runtime, "declarative_image", None)
    ):
        required.add(SandboxCapability.IMAGE)
    if getattr(runtime, "build_context", None):
        required.add(SandboxCapability.BUILD)
    compute = getattr(runtime, "compute", None)
    if compute is not None and getattr(compute, "configured", False):
        required.add(SandboxCapability.RESOURCES)
    network = getattr(runtime, "network", NetworkMode.NONE)
    if network is NetworkMode.NONE:
        required.add(SandboxCapability.NETWORK_NONE)
    elif network is NetworkMode.RESTRICTED:
        required.add(SandboxCapability.NETWORK_ALLOWLIST)
    if getattr(runtime, "persistent", False):
        required.add(SandboxCapability.PERSISTENCE)
    if getattr(runtime, "compose", False):
        required.add(SandboxCapability.COMPOSE)
    if getattr(runtime, "read_only_root", False):
        required.add(SandboxCapability.READ_ONLY_ROOT)
    extra: frozenset[SandboxCapability] = (
        getattr(runtime, "extra_capabilities", frozenset()) or frozenset()
    )
    return frozenset(required) | frozenset(extra)


class EffectiveSandboxPolicy(SandboxModel):
    """Provider-confirmed requirements captured in receipts."""

    provider: str
    requirements: SandboxRequirements
    enforced: frozenset[SandboxCapability]


class SandboxHandle(SandboxModel):
    """Opaque provider sandbox identity."""

    sandbox_id: str
    provider: str
    image_identity: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class AppIsolation(SandboxModel):
    """The OS users that keep an Environment's App host apart from the Harness.

    ``app_user`` runs the App host, its App servers, and the Job's control
    requests. ``agent_user`` runs the Harness, or ``None`` for the sandbox's
    default user. With no ``app_user`` both share one user, so a Harness could
    read the host's private folder: the Trial records that as ``none``.
    """

    app_user: str | None = None
    agent_user: str | None = None

    @property
    def level(self) -> str:
        """``os_user`` when the App host has a user of its own, else ``none``."""
        return "os_user" if self.app_user else "none"


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
    user: str | None = None
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


_renamed = module_getattr(
    "plural.sandbox.models", {"Capability": ("SandboxCapability", lambda: SandboxCapability)}
)


def __getattr__(name: str) -> Any:
    return _renamed(name)


__all__ = [
    "AppIsolation",
    "CapabilityError",
    "DeclarativeImage",
    "DownloadedFile",
    "EffectiveSandboxPolicy",
    "environment_required_capabilities",
    "ExecRequest",
    "ExecResult",
    "FileUpload",
    "NetworkMode",
    "ProviderCapabilities",
    "ProviderDoctor",
    "ProviderUnavailableError",
    "ResourceRequirements",
    "RUNTIME_RENAMES",
    "SandboxCapability",
    "SandboxError",
    "SandboxHandle",
    "SandboxRequirements",
    "SandboxTimeoutError",
    "safe_relative_path",
]
