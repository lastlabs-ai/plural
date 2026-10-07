"""Daytona sandboxes on Plural's own Daytona account.

A project Runtime set to use Plural's credentials never hands its key to the
client. Plural starts each sandbox and relays every command and file through
the hosted API, then bills the sandbox's lifetime to the account's credits as
compute usage. :class:`HostedDaytonaAdapter` is the client side of that relay
and slots into :class:`~plural.sandbox.daytona.DaytonaProvider` unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from plural.sandbox.models import SandboxRequirements

if TYPE_CHECKING:
    from plural.sandbox.daytona import DaytonaSandboxAdapter
    from plural.studio import Studio

CREATE_TIMEOUT_SECONDS = 600.0
EXEC_GRACE_SECONDS = 60.0
DEFAULT_EXEC_TIMEOUT_SECONDS = 3600.0


class _HostedSandbox:
    def __init__(self, studio: Studio, record: Mapping[str, Any]) -> None:
        self._studio = studio
        self._id = str(record["id"])
        self._image = record.get("image_identity")

    @property
    def sandbox_id(self) -> str:
        return self._id

    @property
    def image_identity(self) -> str | None:
        return str(self._image) if self._image else None

    @property
    def path(self) -> str:
        return f"/compute/sandboxes/{quote(self._id)}"

    async def upload_file(self, data: bytes, path: str) -> None:
        await asyncio.to_thread(
            self._studio.request,
            "PUT",
            f"{self.path}/files",
            params={"path": path},
            content=data,
            content_type="application/octet-stream",
        )

    async def download_file(self, path: str) -> bytes:
        return await asyncio.to_thread(
            self._studio.request_bytes, "GET", f"{self.path}/files", params={"path": path}
        )

    async def exec(
        self,
        command: tuple[str, ...],
        *,
        cwd: str,
        env: Mapping[str, str],
        timeout: float | None,
        user: str | None = None,
    ) -> tuple[int, str, str]:
        result = await asyncio.to_thread(
            self._studio.request,
            "POST",
            f"{self.path}/exec",
            json={
                "command": list(command),
                "cwd": cwd,
                "env": dict(env),
                "timeout_seconds": timeout,
                "user": user,
            },
            timeout=(timeout or DEFAULT_EXEC_TIMEOUT_SECONDS) + EXEC_GRACE_SECONDS,
        )
        if result.get("timed_out"):
            raise TimeoutError(f"command timed out after {timeout} seconds")
        return (
            int(result.get("exit_code", 0)),
            str(result.get("stdout") or ""),
            str(result.get("stderr") or ""),
        )


class HostedDaytonaAdapter:
    """Start Daytona sandboxes through Plural for one project Runtime.

    Args:
        studio: Hosted API client for the Runtime's project.
        runtime: The project Runtime's slug or id. Its settings, not the
            client's, decide the region, and its account pays.
    """

    def __init__(self, studio: Studio, *, runtime: str) -> None:
        self._studio = studio
        self._runtime = runtime

    async def create(self, requirements: SandboxRequirements) -> DaytonaSandboxAdapter:
        record = await asyncio.to_thread(
            self._studio.request,
            "POST",
            "/compute/sandboxes",
            json={
                "runtime": self._runtime,
                "requirements": requirements.model_dump(mode="json"),
            },
            timeout=CREATE_TIMEOUT_SECONDS,
        )
        return cast("DaytonaSandboxAdapter", _HostedSandbox(self._studio, record))

    async def delete(self, sandbox: DaytonaSandboxAdapter) -> None:
        hosted = cast(_HostedSandbox, sandbox)
        await asyncio.to_thread(self._studio.request, "DELETE", hosted.path)


__all__ = ["HostedDaytonaAdapter"]
