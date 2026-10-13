"""Lifecycle contract for agent and verifier sandboxes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from plural.sandbox.models import (
    AppIsolation,
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

KILL_USER_PROCESSES = """uids=""
for name in "$@"; do
    case "$name" in
        *[!0-9]*) uid=$(id -u "$name" 2>/dev/null) || continue ;;
        *) uid=$name ;;
    esac
    uids="$uids $uid"
done
[ -n "$uids" ] || exit 0
for entry in /proc/[0-9]*; do
    pid=${entry#/proc/}
    case "$pid" in 1|"$$") continue ;; esac
    owner=""
    while read -r key real _rest; do
        if [ "$key" = "Uid:" ]; then owner=$real; break; fi
    done 2>/dev/null < "$entry/status"
    for uid in $uids; do
        if [ "$owner" = "$uid" ]; then kill -9 "$pid" 2>/dev/null; fi
    done
done
exit 0
"""
"""Kill every process of the named users, or numeric ids, other than PID 1 and itself.

It reads ``/proc`` rather than relying on ``pkill``, which slim images lack.
"""


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
        self,
        handle: SandboxHandle,
        paths: Sequence[str],
        *,
        root: str = "/workspace",
        user: str | None = None,
    ) -> tuple[DownloadedFile, ...]:
        """Download files a Harness declared, which ``user`` wrote, as regular files only."""
        return await self.download_files(handle, paths, root=root)

    async def stop_user_processes(self, handle: SandboxHandle, users: Sequence[str | None]) -> None:
        """Kill every process the Harnesses' users still run, once their run has ended.

        ``None`` names the sandbox's default user. A provider that cannot do
        this safely does nothing; the App host refuses actions after the Job's
        ``finish`` either way.
        """
        return None

    async def isolate_apps(self, handle: SandboxHandle) -> AppIsolation:
        """Prepare a separate OS user for the App host, when this sandbox can.

        Returns:
            The users to run the App host and the Harness as; no ``app_user``
            when the sandbox cannot separate them.
        """
        return AppIsolation()

    async def open_workspace(
        self, handle: SandboxHandle, isolation: AppIsolation, paths: Sequence[str]
    ) -> None:
        """Let ``isolation.agent_user`` write the Harness's folders, once staging is done."""
        return None

    async def isolate_seats(self, handle: SandboxHandle, seats: Sequence[str]) -> dict[str, str]:
        """Prepare one OS user for each seat's Harness, when this sandbox can.

        Each must differ from the App host's user and from every other seat's,
        and must not be able to become another user, so one seat's Harness
        cannot read another's files or process.

        Returns:
            Seat to user, or empty when the sandbox cannot separate them.
        """
        return {}

    @abstractmethod
    async def cancel(self, handle: SandboxHandle) -> None:
        """Force cancellation of active work."""

    @abstractmethod
    async def destroy(self, handle: SandboxHandle) -> None:
        """Idempotently delete the sandbox and scoped data."""


__all__ = ["SandboxProvider"]
