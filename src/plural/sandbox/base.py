"""Lifecycle contract for agent and verifier sandboxes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from plural.sandbox.models import (
    CapabilityError,
    DownloadedFile,
    EffectiveSandboxPolicy,
    ExecRequest,
    ExecResult,
    FileUpload,
    ProviderCapabilities,
    ProviderDoctor,
    SandboxHandle,
    SandboxRequirements,
)


class SandboxProvider(ABC):
    """Async lifecycle provider, separate from environment tool runtimes."""

    name: str

    @abstractmethod
    async def capabilities(self) -> ProviderCapabilities:
        """Declare controls available in the current installation."""

    async def preflight(self, requirements: SandboxRequirements) -> EffectiveSandboxPolicy:
        """Fail before launch if any requested control is unavailable."""
        declared = await self.capabilities()
        if not declared.available:
            raise CapabilityError(declared.reason or f"{self.name} is unavailable")
        missing = requirements.required_capabilities() - declared.capabilities
        if missing:
            values = ", ".join(sorted(item.value for item in missing))
            raise CapabilityError(f"{self.name} cannot enforce required capabilities: {values}")
        return EffectiveSandboxPolicy(
            provider=self.name,
            requirements=requirements,
            enforced=requirements.required_capabilities(),
        )

    @abstractmethod
    async def doctor(self) -> ProviderDoctor:
        """Return dependency, daemon, or credential health."""

    @abstractmethod
    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        """Create a fresh sandbox after successful preflight."""

    @abstractmethod
    async def upload_files(
        self, handle: SandboxHandle, files: Sequence[FileUpload], *, root: str = "/workspace"
    ) -> None:
        """Upload validated files beneath a scoped workspace."""

    async def upload_bundle(
        self, handle: SandboxHandle, bundle: Path, *, root: str = "/workspace"
    ) -> None:
        """Upload a local directory without following symlinks."""
        resolved = bundle.resolve()
        uploads: list[FileUpload] = []
        for path in sorted(resolved.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"bundle contains a symlink: {path.relative_to(resolved)}")
            if path.is_file():
                uploads.append(
                    FileUpload(
                        path=path.relative_to(resolved).as_posix(),
                        data=path.read_bytes(),
                        mode=path.stat().st_mode & 0o777,
                    )
                )
        await self.upload_files(handle, uploads, root=root)

    @abstractmethod
    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        """Execute argv with cwd, env, timeout, stdin, and captured logs."""

    @abstractmethod
    async def download_files(
        self, handle: SandboxHandle, paths: Sequence[str], *, root: str = "/workspace"
    ) -> tuple[DownloadedFile, ...]:
        """Download exact declared files."""

    async def download_artifacts(
        self, handle: SandboxHandle, paths: Sequence[str], *, root: str = "/workspace"
    ) -> tuple[DownloadedFile, ...]:
        """Download declared artifact files."""
        return await self.download_files(handle, paths, root=root)

    @abstractmethod
    async def cancel(self, handle: SandboxHandle) -> None:
        """Force cancellation of active work."""

    @abstractmethod
    async def destroy(self, handle: SandboxHandle) -> None:
        """Idempotently delete the sandbox and scoped data."""


__all__ = ["SandboxProvider"]
