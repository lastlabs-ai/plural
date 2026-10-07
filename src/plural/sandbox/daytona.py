"""Optional Daytona SDK sandbox provider."""

from __future__ import annotations

import importlib.util
import math
import os
import shlex
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast
from uuid import uuid4

from plural.sandbox.base import SandboxProvider
from plural.sandbox.models import (
    Capability,
    CapabilityError,
    DownloadedFile,
    EffectiveSandboxPolicy,
    ExecRequest,
    ExecResult,
    FileUpload,
    NetworkMode,
    ProviderCapabilities,
    ProviderDoctor,
    ProviderUnavailableError,
    SandboxHandle,
    SandboxRequirements,
    safe_relative_path,
)


class DaytonaSandboxAdapter(Protocol):
    """Small async surface used by the provider and fake tests."""

    @property
    def sandbox_id(self) -> str:
        """Return the remote sandbox id."""
        ...

    @property
    def image_identity(self) -> str | None:
        """Return snapshot or image identity when exposed."""
        ...

    async def upload_file(self, data: bytes, path: str) -> None:
        """Upload one file."""
        ...

    async def download_file(self, path: str) -> bytes:
        """Download one file."""
        ...

    async def exec(
        self,
        command: tuple[str, ...],
        *,
        cwd: str,
        env: Mapping[str, str],
        timeout: float | None,
        user: str | None = None,
    ) -> tuple[int, str, str]:
        """Execute one safely quoted argv command."""
        ...


class DaytonaClientAdapter(Protocol):
    """Injectable Daytona client boundary."""

    async def create(self, requirements: SandboxRequirements) -> DaytonaSandboxAdapter:
        """Create one sandbox."""
        ...

    async def delete(self, sandbox: DaytonaSandboxAdapter) -> None:
        """Delete one sandbox."""
        ...


class _OfficialSandbox:
    def __init__(self, value: Any) -> None:
        self.value = value

    @property
    def resources(self) -> tuple[float, float, float]:
        """vCPUs, memory GiB, and disk GiB Daytona allotted."""
        return (
            float(getattr(self.value, "cpu", 0) or 0),
            float(getattr(self.value, "memory", 0) or 0),
            float(getattr(self.value, "disk", 0) or 0),
        )

    @property
    def sandbox_id(self) -> str:
        return str(getattr(self.value, "id", None) or getattr(self.value, "sandbox_id", None))

    @property
    def image_identity(self) -> str | None:
        value = getattr(self.value, "snapshot", None) or getattr(self.value, "snapshot_id", None)
        return str(value) if value else None

    async def upload_file(self, data: bytes, path: str) -> None:
        await self.value.fs.upload_file(data, path)

    async def download_file(self, path: str) -> bytes:
        result = await self.value.fs.download_file(path)
        return bytes(result)

    async def exec(
        self,
        command: tuple[str, ...],
        *,
        cwd: str,
        env: Mapping[str, str],
        timeout: float | None,
        user: str | None = None,
    ) -> tuple[int, str, str]:
        kwargs: dict[str, Any] = {
            "cwd": cwd,
            "env": dict(env),
            # Daytona's API rejects fractional seconds.
            "timeout": math.ceil(timeout) if timeout is not None else None,
        }
        if user:
            kwargs["user"] = user
        try:
            try:
                result = await self.value.process.exec(shlex.join(command), **kwargs)
            except TypeError:
                kwargs.pop("user", None)
                result = await self.value.process.exec(shlex.join(command), **kwargs)
        except Exception as exc:
            if any(kind.__name__ == "DaytonaTimeoutError" for kind in type(exc).__mro__):
                raise TimeoutError(str(exc)) from exc
            raise
        exit_code = int(getattr(result, "exit_code", getattr(result, "code", 0)))
        stdout = str(getattr(result, "result", getattr(result, "stdout", "")) or "")
        stderr = str(getattr(result, "stderr", "") or "")
        return exit_code, stdout, stderr


class OfficialDaytonaAdapter:
    """Lazy adapter for the official ``daytona`` async SDK.

    Args:
        api_key: Use this key instead of ``DAYTONA_API_KEY``.
        api_url: Use this API instead of ``DAYTONA_API_URL`` or Daytona Cloud.
        target: Use this region instead of ``DAYTONA_TARGET``.
        create_options: Extra sandbox parameters for every create, such as
            ``labels``, ``auto_stop_interval``, ``ttl_minutes``, or ``ephemeral``.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        target: str | None = None,
        create_options: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            from daytona import AsyncDaytona, DaytonaConfig
        except ImportError as exc:  # pragma: no cover - dependency-gated
            raise ProviderUnavailableError("install plural[daytona]") from exc
        if api_key or api_url or target:
            self._client = AsyncDaytona(
                DaytonaConfig(api_key=api_key, api_url=api_url, target=target)
            )
        else:
            self._client = AsyncDaytona()
        self._create_options = dict(create_options or {})

    async def create(
        self,
        requirements: SandboxRequirements,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> DaytonaSandboxAdapter:
        """Create one sandbox; ``options`` add to the adapter's create options."""
        from daytona import (
            CreateSandboxFromImageParams,
            CreateSandboxFromSnapshotParams,
            Image,
            Resources,
        )

        network: dict[str, Any] = {}
        if requirements.network is NetworkMode.NONE:
            network["network_block_all"] = True
        elif requirements.network is NetworkMode.RESTRICTED:
            values = ",".join(requirements.network_allowlist)
            if all("/" in item for item in requirements.network_allowlist):
                network["network_allow_list"] = values
            else:
                network["domain_allow_list"] = values
        resources = None
        if requirements.resources.configured:
            cpu = requirements.resources.cpu
            memory_mb = requirements.resources.memory_mb
            # Daytona sizes sandboxes in whole vCPUs and whole GiB.
            resources = Resources(
                cpu=max(1, round(cpu)) if cpu is not None else None,
                memory=max(1, round(memory_mb / 1024)) if memory_mb is not None else None,
            )
        common = {
            **self._create_options,
            **dict(options or {}),
            **network,
            "resources": resources,
        }
        image: Any = requirements.image
        if requirements.declarative_image is not None:
            specification = requirements.declarative_image
            image = Image.base(specification.base)
            if specification.pip_packages:
                image = image.pip_install(*specification.pip_packages)
            if specification.environment:
                image = image.env(specification.environment)
            if specification.workdir:
                image = image.workdir(specification.workdir)
        if image:
            params = CreateSandboxFromImageParams(image=image, **common)
        else:
            params = CreateSandboxFromSnapshotParams(snapshot=requirements.snapshot, **common)
        timeout = requirements.timeout_seconds or 60
        value = await self._client.create(params, timeout=timeout)
        return _OfficialSandbox(value)

    async def get(self, sandbox_id: str) -> DaytonaSandboxAdapter:
        """Reattach to a sandbox this client's account owns."""
        return _OfficialSandbox(await self._client.get(sandbox_id))

    async def delete(self, sandbox: DaytonaSandboxAdapter) -> None:
        official = cast(_OfficialSandbox, sandbox)
        await self._client.delete(official.value)

    async def close(self) -> None:
        """Close the client's HTTP connections."""
        await self._client.close()


class DaytonaProvider(SandboxProvider):
    """Execute in Daytona while keeping its SDK an optional import."""

    name = "daytona"

    def __init__(
        self,
        *,
        adapter: DaytonaClientAdapter | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._adapter = adapter
        self._environ = os.environ if environ is None else environ
        self._sandboxes: dict[str, DaytonaSandboxAdapter] = {}

    def _sdk_available(self) -> bool:
        return self._adapter is not None or importlib.util.find_spec("daytona") is not None

    def _credentials_available(self) -> bool:
        return self._adapter is not None or bool(self._environ.get("DAYTONA_API_KEY"))

    async def capabilities(self) -> ProviderCapabilities:
        """Declare controls implemented by the current Daytona SDK."""
        available = self._sdk_available() and self._credentials_available()
        return ProviderCapabilities(
            provider=self.name,
            available=available,
            capabilities=frozenset(
                {
                    Capability.IMAGE,
                    Capability.RESOURCES,
                    Capability.NETWORK_NONE,
                    Capability.NETWORK_ALLOWLIST,
                    Capability.UPLOAD,
                    Capability.DOWNLOAD,
                    Capability.TIMEOUT,
                    Capability.CANCEL,
                    Capability.WORKING_DIRECTORY,
                    Capability.ENVIRONMENT,
                    Capability.LOG_CAPTURE,
                }
            ),
            reason=None if available else "Daytona SDK or DAYTONA_API_KEY is unavailable",
        )

    async def preflight(self, requirements: SandboxRequirements) -> EffectiveSandboxPolicy:
        """Reject Daytona controls whose SDK mapping is not enforceable."""
        if requirements.build_context:
            raise CapabilityError(
                "Daytona local build_context is unsupported; use an image or snapshot"
            )
        if requirements.resources.pids is not None or requirements.resources.disk_mb is not None:
            raise CapabilityError("Daytona does not expose pids or disk limits in this adapter")
        if requirements.network is NetworkMode.RESTRICTED and not requirements.network_allowlist:
            raise CapabilityError("restricted Daytona networking requires an allowlist")
        return await super().preflight(requirements)

    async def doctor(self) -> ProviderDoctor:
        """Detect SDK and credential presence without exposing values."""
        capabilities = await self.capabilities()
        sdk = self._sdk_available()
        credentials = self._credentials_available()
        return ProviderDoctor(
            name=self.name,
            available=sdk,
            healthy=sdk and credentials,
            capabilities=tuple(sorted(item.value for item in capabilities.capabilities)),
            reason=capabilities.reason,
            details={
                "sdk_installed": sdk,
                "credentials_configured": credentials,
                "api_url_configured": bool(self._environ.get("DAYTONA_API_URL")),
                "target_configured": bool(self._environ.get("DAYTONA_TARGET")),
            },
        )

    def _client(self) -> DaytonaClientAdapter:
        if self._adapter is None:
            self._adapter = OfficialDaytonaAdapter()
        return self._adapter

    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        """Create a Daytona sandbox from image, snapshot, or defaults."""
        await self.preflight(requirements)
        remote = await self._client().create(requirements)
        sandbox_id = remote.sandbox_id
        if not sandbox_id or sandbox_id == "None":
            sandbox_id = f"daytona-{uuid4().hex}"
        self._sandboxes[sandbox_id] = remote
        return SandboxHandle(
            sandbox_id=sandbox_id,
            provider=self.name,
            image_identity=(
                remote.image_identity
                or requirements.snapshot
                or requirements.image
                or (
                    requirements.declarative_image.base
                    if requirements.declarative_image is not None
                    else None
                )
            ),
        )

    def _remote(self, handle: SandboxHandle) -> DaytonaSandboxAdapter:
        if handle.provider != self.name or handle.sandbox_id not in self._sandboxes:
            raise ValueError("unknown Daytona sandbox")
        return self._sandboxes[handle.sandbox_id]

    async def upload_files(
        self, handle: SandboxHandle, files: Sequence[FileUpload], *, root: str = "/workspace"
    ) -> None:
        """Upload exact in-memory files."""
        remote = self._remote(handle)
        for upload in files:
            await remote.upload_file(upload.data, f"{root.rstrip('/')}/{upload.path}")

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        """Execute through ``sandbox.process.exec``."""
        if request.stdin is not None:
            raise CapabilityError("Daytona process.exec does not support stdin in this adapter")
        started = time.monotonic()
        try:
            code, stdout, stderr = await self._remote(handle).exec(
                request.command,
                cwd=request.cwd,
                env=request.env,
                timeout=request.timeout_seconds,
                user=request.user,
            )
        except TimeoutError:
            return ExecResult(
                exit_code=-1,
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )
        return ExecResult(
            exit_code=code,
            stdout=stdout.encode(),
            stderr=stderr.encode(),
            duration_seconds=time.monotonic() - started,
        )

    async def download_files(
        self, handle: SandboxHandle, paths: Sequence[str], *, root: str = "/workspace"
    ) -> tuple[DownloadedFile, ...]:
        """Download exact declared files."""
        remote = self._remote(handle)
        output = []
        for path in paths:
            safe = safe_relative_path(path)
            output.append(
                DownloadedFile(
                    path=safe,
                    data=await remote.download_file(f"{root.rstrip('/')}/{safe}"),
                )
            )
        return tuple(output)

    async def cancel(self, handle: SandboxHandle) -> None:
        """Delete the sandbox to force cancellation."""
        remote = self._sandboxes.get(handle.sandbox_id)
        if remote is not None:
            await self._client().delete(remote)
            self._sandboxes.pop(handle.sandbox_id, None)

    async def destroy(self, handle: SandboxHandle) -> None:
        """Idempotently delete the remote sandbox."""
        await self.cancel(handle)


__all__ = [
    "DaytonaClientAdapter",
    "DaytonaProvider",
    "DaytonaSandboxAdapter",
    "OfficialDaytonaAdapter",
]
