"""Docker CLI sandbox provider with argv-only command construction."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from plural.sandbox.base import KILL_USER_PROCESSES, SandboxProvider
from plural.sandbox.models import (
    AppIsolation,
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
    SandboxCapability,
    SandboxHandle,
    SandboxRequirements,
    safe_relative_path,
)

HOST_ALIAS = "host.docker.internal"
DEFAULT_USER = "65532:65532"
"""The container's default user, which runs the Harness."""
APP_USER = "65533:65533"
"""The App host's user: not the container's default ``65532``, which runs the Harness."""
SEAT_UID = 65400
"""The first seat's user; each later seat takes the next number."""
MAX_SEATS = 100
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _host_url(value: str) -> str:
    """Point a loopback URL, such as a local model gateway, at the Docker host.

    Inside a container ``localhost`` is the container itself.
    """
    if not value.startswith(("http://", "https://")):
        return value
    parsed = urlsplit(value)
    if parsed.hostname not in _LOOPBACK:
        return value
    netloc = HOST_ALIAS if parsed.port is None else f"{HOST_ALIAS}:{parsed.port}"
    if parsed.username or parsed.password:
        return value
    return urlunsplit(parsed._replace(netloc=netloc))


class DockerProvider(SandboxProvider):
    """Create one locked-down Docker container per execution phase."""

    name = "docker"

    def __init__(
        self, *, executable: str = "docker", default_image: str = "python:3.12-slim"
    ) -> None:
        self.executable = executable
        self.default_image = default_image
        self._containers: set[str] = set()
        self._active_exec: dict[str, asyncio.subprocess.Process] = {}
        self._layer_locks: dict[str, asyncio.Lock] = {}

    async def _run(
        self,
        *args: str,
        stdin: bytes | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> tuple[int, bytes, bytes]:
        if shutil.which(self.executable) is None:
            raise ProviderUnavailableError(f"{self.executable!r} was not found")
        process = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            communication = process.communicate(stdin)
            stdout, stderr = (
                await asyncio.wait_for(communication, timeout)
                if timeout is not None
                else await communication
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        if check and process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"docker {' '.join(args[:2])} failed: {message}")
        return process.returncode or 0, stdout, stderr

    async def capabilities(self) -> ProviderCapabilities:
        """Declare Docker controls only when the daemon is reachable."""
        doctor = await self.doctor()
        supported = frozenset(
            {
                SandboxCapability.IMAGE,
                SandboxCapability.BUILD,
                SandboxCapability.RESOURCES,
                SandboxCapability.NETWORK_NONE,
                SandboxCapability.UPLOAD,
                SandboxCapability.DOWNLOAD,
                SandboxCapability.TIMEOUT,
                SandboxCapability.CANCEL,
                SandboxCapability.READ_ONLY_ROOT,
                SandboxCapability.WORKING_DIRECTORY,
                SandboxCapability.ENVIRONMENT,
                SandboxCapability.LOG_CAPTURE,
            }
        )
        return ProviderCapabilities(
            provider=self.name,
            available=doctor.available and doctor.healthy,
            capabilities=supported,
            reason=doctor.reason,
        )

    async def preflight(self, requirements: SandboxRequirements) -> EffectiveSandboxPolicy:
        """Reject provider-specific image forms before launch."""
        if requirements.declarative_image is not None:
            raise CapabilityError(
                "DockerProvider does not translate Daytona declarative images; "
                "use image or build_context"
            )
        if requirements.snapshot is not None:
            raise CapabilityError("DockerProvider does not resolve Daytona snapshot identities")
        if requirements.resources.disk_mb is not None:
            raise CapabilityError("DockerProvider does not enforce per-container disk limits")
        return await super().preflight(requirements)

    async def doctor(self) -> ProviderDoctor:
        """Detect the Docker CLI and daemon."""
        capabilities = (
            SandboxCapability.IMAGE,
            SandboxCapability.BUILD,
            SandboxCapability.RESOURCES,
            SandboxCapability.NETWORK_NONE,
            SandboxCapability.UPLOAD,
            SandboxCapability.DOWNLOAD,
            SandboxCapability.TIMEOUT,
            SandboxCapability.CANCEL,
            SandboxCapability.READ_ONLY_ROOT,
            SandboxCapability.WORKING_DIRECTORY,
            SandboxCapability.ENVIRONMENT,
            SandboxCapability.LOG_CAPTURE,
        )
        if shutil.which(self.executable) is None:
            return ProviderDoctor(
                name=self.name,
                available=False,
                healthy=False,
                capabilities=tuple(item.value for item in capabilities),
                reason="Docker CLI not found",
            )
        try:
            _code, stdout, _stderr = await self._run(
                "version", "--format", "{{json .Server}}", timeout=5
            )
            details = json.loads(stdout or b"{}")
        except (OSError, RuntimeError, TimeoutError, json.JSONDecodeError) as exc:
            return ProviderDoctor(
                name=self.name,
                available=True,
                healthy=False,
                capabilities=tuple(item.value for item in capabilities),
                reason=f"Docker daemon unavailable: {exc}",
            )
        return ProviderDoctor(
            name=self.name,
            available=True,
            healthy=True,
            capabilities=tuple(item.value for item in capabilities),
            details={"version": str(details.get("Version", "unknown"))},
        )

    async def _image(self, requirements: SandboxRequirements) -> tuple[str, str | None]:
        image = requirements.image or self.default_image
        if requirements.build_context:
            identity = (requirements.execution_identity or uuid4().hex).removeprefix("sha256:")
            tag = f"plural-execution:{identity[:32]}"
            args = ["build", "--pull=false", "--tag", tag]
            if requirements.dockerfile:
                args.extend(["--file", requirements.dockerfile])
            args.append(requirements.build_context)
            await self._run(*args)
            image = tag
        try:
            _code, stdout, _stderr = await self._run(
                "image", "inspect", image, "--format", "{{.Id}}"
            )
        except RuntimeError:
            await self._run("pull", image)
            _code, stdout, _stderr = await self._run(
                "image", "inspect", image, "--format", "{{.Id}}"
            )
        return image, stdout.decode().strip() or None

    async def extend_image(
        self, requirements: SandboxRequirements, context: Path, key: str
    ) -> SandboxRequirements:
        """Layer a build context onto the requirements' image, once per base and key.

        The context's Dockerfile receives the base image as the ``BASE`` build
        argument. The result is tagged by base identity and ``key``, so later
        Trials and Jobs reuse it instead of building again.

        Returns:
            The requirements, pointing at the extended image.
        """
        await self.preflight(requirements)
        base, identity = await self._image(requirements)
        digest = hashlib.sha256(f"{identity or base}\n{key}".encode()).hexdigest()
        tag = f"plural-runtime:{digest[:32]}"
        async with self._layer_locks.setdefault(tag, asyncio.Lock()):
            code, _stdout, _stderr = await self._run(
                "image", "inspect", tag, "--format", "{{.Id}}", check=False
            )
            if code != 0:
                await self._run(
                    "build",
                    "--pull=false",
                    "--build-arg",
                    f"BASE={base}",
                    "--tag",
                    tag,
                    str(context),
                )
        return requirements.model_copy(
            update={"image": tag, "build_context": None, "dockerfile": None}
        )

    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        """Create and start a hardened, scoped container."""
        await self.preflight(requirements)
        image, identity = await self._image(requirements)
        name = f"plural-{uuid4().hex}"
        args = [
            "create",
            "--name",
            name,
            "--label",
            "dev.plural.execution=true",
            "--security-opt",
            "no-new-privileges=true",
            "--cap-drop",
            "ALL",
            "--user",
            DEFAULT_USER,
            "--pids-limit",
            str(requirements.resources.pids or 256),
            "--tmpfs",
            "/workspace:rw,nosuid,nodev,noexec,mode=1777",
        ]
        if requirements.network is NetworkMode.NONE:
            args.extend(["--network", "none"])
        else:
            args.extend(["--add-host", f"{HOST_ALIAS}:host-gateway"])
            if requirements.network is NetworkMode.FULL:
                args.extend(["--network", "bridge"])
        if requirements.resources.cpu is not None:
            args.extend(["--cpus", str(requirements.resources.cpu)])
        if requirements.resources.memory_mb is not None:
            args.extend(["--memory", f"{requirements.resources.memory_mb}m"])
        if requirements.read_only_root:
            args.append("--read-only")
        args.extend([image, "sleep", "infinity"])
        _code, stdout, _stderr = await self._run(*args)
        container_id = stdout.decode().strip()
        self._containers.add(container_id)
        try:
            await self._run("start", container_id)
        except BaseException:
            await self.destroy(
                SandboxHandle(
                    sandbox_id=container_id,
                    provider=self.name,
                    image_identity=identity,
                )
            )
            raise
        return SandboxHandle(
            sandbox_id=container_id,
            provider=self.name,
            image_identity=identity,
        )

    def _validate(self, handle: SandboxHandle) -> str:
        if handle.provider != self.name or handle.sandbox_id not in self._containers:
            raise ValueError("unknown Docker sandbox")
        return handle.sandbox_id

    async def upload_files(
        self, handle: SandboxHandle, files: Sequence[FileUpload], *, root: str = "/workspace"
    ) -> None:
        """Stream exact files into the writable workspace mount."""
        container = self._validate(handle)
        for upload in files:
            safe = safe_relative_path(upload.path)
            remote_path = f"{root.rstrip('/')}/{safe}"
            remote_parent = str(Path(remote_path).parent)
            await self._run("exec", container, "mkdir", "-p", remote_parent)
            await self._run(
                "exec",
                "--interactive",
                container,
                "sh",
                "-c",
                'cat > "$1"',
                "plural-upload",
                remote_path,
                stdin=upload.data,
            )
            await self._run(
                "exec",
                container,
                "chmod",
                f"{upload.mode:o}",
                remote_path,
            )

    async def isolate_apps(self, handle: SandboxHandle) -> AppIsolation:
        """Run the App host as its own unprivileged user.

        The container runs everything else as ``65532``, with every capability
        dropped, so the Harness cannot read the App host's ``0700`` folder or
        its process.

        Returns:
            The App host's user, and the default user for the Harness.
        """
        self._validate(handle)
        return AppIsolation(app_user=APP_USER)

    async def isolate_seats(self, handle: SandboxHandle, seats: Sequence[str]) -> dict[str, str]:
        """Run each seat's Harness as its own unprivileged user.

        Every capability is dropped, so no seat's user can read another's
        ``0700`` folder or process, or the App host's.

        Returns:
            Seat to a numeric user, ``65400`` for the first.
        """
        self._validate(handle)
        if len(seats) > MAX_SEATS:
            return {}
        return {seat: f"{SEAT_UID + index}:{SEAT_UID + index}" for index, seat in enumerate(seats)}

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        """Execute argv and capture logs, enforcing a host-side timeout."""
        container = self._validate(handle)
        args = ["exec", "--workdir", request.cwd]
        if request.user:
            args.extend(["--user", request.user])
        if request.stdin is not None:
            args.append("--interactive")
        for name, value in sorted(request.env.items()):
            args.extend(["--env", f"{name}={_host_url(value)}"])
        args.extend([container, *request.command])
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdin=asyncio.subprocess.PIPE
            if request.stdin is not None
            else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._active_exec[container] = process
        timed_out = False
        try:
            communication = process.communicate(request.stdin)
            stdout, stderr = (
                await asyncio.wait_for(communication, request.timeout_seconds)
                if request.timeout_seconds is not None
                else await communication
            )
        except asyncio.TimeoutError:
            timed_out = True
            await self.cancel(handle)
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            await self.cancel(handle)
            raise
        finally:
            self._active_exec.pop(container, None)
        return ExecResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
        )

    async def download_files(
        self, handle: SandboxHandle, paths: Sequence[str], *, root: str = "/workspace"
    ) -> tuple[DownloadedFile, ...]:
        """Stream exact declared paths out and reject non-regular files."""
        return await self._download(handle, paths, root=root, user=None)

    async def download_artifacts(
        self,
        handle: SandboxHandle,
        paths: Sequence[str],
        *,
        root: str = "/workspace",
        user: str | None = None,
    ) -> tuple[DownloadedFile, ...]:
        """Read a Harness's files as the user that wrote them, which owns its folder.

        No capability is kept, so only a seat's own user can enter its ``0700`` folder.
        """
        return await self._download(handle, paths, root=root, user=user)

    async def _download(
        self,
        handle: SandboxHandle,
        paths: Sequence[str],
        *,
        root: str,
        user: str | None,
    ) -> tuple[DownloadedFile, ...]:
        container = self._validate(handle)
        as_user = ("--user", user) if user else ()
        output: list[DownloadedFile] = []
        for path in paths:
            safe = safe_relative_path(path)
            remote_path = f"{root.rstrip('/')}/{safe}"
            regular, _stdout, _stderr = await self._run(
                "exec", *as_user, container, "test", "-f", remote_path, check=False
            )
            symlink, _stdout, _stderr = await self._run(
                "exec", *as_user, container, "test", "-L", remote_path, check=False
            )
            if regular != 0 or symlink == 0:
                raise FileNotFoundError(f"declared output is not a regular file: {safe}")
            _code, data, _stderr = await self._run("exec", *as_user, container, "cat", remote_path)
            output.append(DownloadedFile(path=safe, data=data))
        return tuple(output)

    async def stop_user_processes(self, handle: SandboxHandle, users: Sequence[str | None]) -> None:
        """Kill what each Harness user left running, as that user, since no capability is kept.

        ``None`` is the container's default user, whose ``sleep`` keeps it alive
        as PID 1 and is spared.
        """
        container = self._validate(handle)
        for user in dict.fromkeys(item or DEFAULT_USER for item in users):
            uid = user.split(":", 1)[0]
            await self._run(
                "exec",
                "--user",
                user,
                container,
                "sh",
                "-c",
                KILL_USER_PROCESSES,
                "plural",
                uid,
                timeout=30,
                check=False,
            )

    async def cancel(self, handle: SandboxHandle) -> None:
        """Kill the container to force all active processes to stop."""
        container = self._validate(handle)
        process = self._active_exec.get(container)
        await self._run("kill", container, check=False)
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()

    async def destroy(self, handle: SandboxHandle) -> None:
        """Force-remove the container idempotently."""
        container = handle.sandbox_id
        if container in self._containers:
            await self._run("rm", "--force", container, check=False)
            self._containers.discard(container)
            self._active_exec.pop(container, None)


__all__ = ["DockerProvider"]
