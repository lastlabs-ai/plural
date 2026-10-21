"""Sandbox lifecycle providers."""

from typing import Any

from plural._deprecation import module_getattr
from plural.sandbox.base import SandboxProvider
from plural.sandbox.daytona import (
    DaytonaClientAdapter,
    DaytonaProvider,
    DaytonaSandboxAdapter,
    OfficialDaytonaAdapter,
)
from plural.sandbox.docker import DockerProvider
from plural.sandbox.local import LocalProvider
from plural.sandbox.models import (
    AppIsolation,
    CapabilityError,
    DeclarativeImage,
    DownloadedFile,
    EffectiveSandboxPolicy,
    ExecRequest,
    ExecResult,
    FileUpload,
    NetworkMode,
    ProviderCapabilities,
    ProviderDoctor,
    ProviderUnavailableError,
    ResourceRequirements,
    SandboxCapability,
    SandboxError,
    SandboxHandle,
    SandboxRequirements,
    SandboxTimeoutError,
    environment_required_capabilities,
    safe_relative_path,
)
from plural.sandbox.registry import ProviderRegistry, default_registry

_renamed = module_getattr(
    "plural.sandbox", {"Capability": ("SandboxCapability", lambda: SandboxCapability)}
)


def __getattr__(name: str) -> Any:
    return _renamed(name)


__all__ = [
    "AppIsolation",
    "SandboxCapability",
    "CapabilityError",
    "DeclarativeImage",
    "DaytonaClientAdapter",
    "DaytonaProvider",
    "DaytonaSandboxAdapter",
    "DockerProvider",
    "DownloadedFile",
    "EffectiveSandboxPolicy",
    "environment_required_capabilities",
    "ExecRequest",
    "ExecResult",
    "FileUpload",
    "LocalProvider",
    "NetworkMode",
    "OfficialDaytonaAdapter",
    "ProviderCapabilities",
    "ProviderDoctor",
    "ProviderRegistry",
    "ProviderUnavailableError",
    "ResourceRequirements",
    "SandboxError",
    "SandboxHandle",
    "SandboxProvider",
    "SandboxRequirements",
    "SandboxTimeoutError",
    "default_registry",
    "safe_relative_path",
]
