"""Unsafe local subprocess provider for development and conformance tests."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from plural.sandbox.base import SandboxProvider
from plural.sandbox.models import (
    Capability,
    DownloadedFile,
    ExecRequest,
    ExecResult,
    FileUpload,
    ProviderCapabilities,
    ProviderDoctor,
    SandboxHandle,
    SandboxRequirements,
    safe_relative_path,
)


class LocalProvider(SandboxProvider):
    """Run commands in temporary directories without isolation.

    This provider intentionally does not advertise network, resource, image, or
    read-only-root enforcement. It is suitable only for explicitly trusted local
    development workloads.
    """

    name = "local"

    def __init__(self, *, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir
        self._roots: dict[str, Path] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def capabilities(self) -> ProviderCapabilities:
        """Declare local subprocess controls."""
        return ProviderCapabilities(
            provider=self.name,
            available=True,
            capabilities=frozenset(
                {
                    Capability.UPLOAD,
                    Capability.DOWNLOAD,
                    Capability.TIMEOUT,
                    Capability.CANCEL,
                    Capability.WORKING_DIRECTORY,
                    Capability.ENVIRONMENT,
                    Capability.LOG_CAPTURE,
                }
            ),
            reason="development mode; no process, network, or filesystem isolation",
        )

    async def doctor(self) -> ProviderDoctor:
        """Report local execution availability without implying isolation."""
        capabilities = await self.capabilities()
        return ProviderDoctor(
            name=self.name,
            available=True,
            healthy=True,
            capabilities=tuple(sorted(item.value for item in capabilities.capabilities)),
            reason=capabilities.reason,
            details={"mode": "unsafe-development-subprocess"},
        )

    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        """Create a scoped temporary workspace."""
        await self.preflight(requirements)
        sandbox_id = f"local-{uuid4().hex}"
        root = Path(tempfile.mkdtemp(prefix=f"plural-{sandbox_id}-", dir=self._base_dir)).resolve()
        (root / "workspace").mkdir(mode=0o700)
        self._roots[sandbox_id] = root
        return SandboxHandle(sandbox_id=sandbox_id, provider=self.name)

    def _root(self, handle: SandboxHandle) -> Path:
        if handle.provider != self.name or handle.sandbox_id not in self._roots:
            raise ValueError("unknown local sandbox")
        return self._roots[handle.sandbox_id]

    def _path(self, handle: SandboxHandle, root: str, relative: str = ".") -> Path:
        base = self._root(handle)
        root_relative = root.removeprefix("/")
        candidate = (base / root_relative / safe_relative_path(relative)).resolve()
        if not candidate.is_relative_to(base):
            raise ValueError("path escapes local sandbox")
        return candidate

    async def upload_files(
        self, handle: SandboxHandle, files: Sequence[FileUpload], *, root: str = "/workspace"
    ) -> None:
        """Copy files into the temporary workspace."""
        for upload in files:
            destination = self._path(handle, root, upload.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(upload.data)
            destination.chmod(upload.mode)

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        """Run an argv-only subprocess and kill it at timeout."""
        root = self._root(handle)
        cwd = (root / request.cwd.removeprefix("/")).resolve()
        if not cwd.is_relative_to(root):
            raise ValueError("cwd escapes local sandbox")
        cwd.mkdir(parents=True, exist_ok=True)
        inherited = {
            name: value
            for name in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
            if (value := os.environ.get(name)) is not None
        }
        env = {
            **inherited,
            "PLURAL_SANDBOX_ROOT": str(root),
            **request.env,
        }
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *request.command,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE
            if request.stdin is not None
            else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self._processes[handle.sandbox_id] = process
        timed_out = False
        try:
            communicate = process.communicate(request.stdin)
            stdout, stderr = (
                await asyncio.wait_for(communicate, timeout=request.timeout_seconds)
                if request.timeout_seconds is not None
                else await communicate
            )
        except TimeoutError:
            timed_out = True
            await _terminate_process_tree(process)
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            await _terminate_process_tree(process)
            raise
        finally:
            self._processes.pop(handle.sandbox_id, None)
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
        """Read exact declared regular files."""
        output: list[DownloadedFile] = []
        for path in paths:
            safe = safe_relative_path(path)
            source = self._path(handle, root, safe)
            if source.is_symlink() or not source.is_file():
                raise FileNotFoundError(f"declared output is not a regular file: {safe}")
            output.append(DownloadedFile(path=safe, data=source.read_bytes()))
        return tuple(output)

    async def cancel(self, handle: SandboxHandle) -> None:
        """Kill the active subprocess, if any."""
        process = self._processes.get(handle.sandbox_id)
        if process is not None and process.returncode is None:
            await _terminate_process_tree(process)

    async def destroy(self, handle: SandboxHandle) -> None:
        """Kill active work and remove all scoped files."""
        await self.cancel(handle)
        root = self._roots.pop(handle.sandbox_id, None)
        if root is not None:
            await asyncio.to_thread(shutil.rmtree, root, True)


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            process.kill()
    else:
        process.kill()
    await process.wait()


__all__ = ["LocalProvider"]
