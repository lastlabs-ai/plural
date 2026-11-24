"""Daytona sandboxes Plural starts for a project Runtime.

A project Runtime set to use Plural's credentials never hands its key to the
client, and neither does one with its own stored credentials when a run goes
through the relay, as a detached run does. Plural starts each sandbox and
relays every command and file through the hosted API. On Plural's account the
sandbox's lifetime is billed to the account's credits as compute usage; on the
Runtime's own credentials it never draws on credits.
:class:`HostedDaytonaAdapter` is the client side of that relay and slots into
:class:`~plural.sandbox.daytona.DaytonaProvider` unchanged.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from plural.errors import PluralError
from plural.harness.native_runner import CREDIT_PAUSE_VARIABLE, DEFAULT_CREDIT_PAUSE_SECONDS
from plural.sandbox.models import SandboxRequirements

if TYPE_CHECKING:
    from plural.sandbox.daytona import DaytonaSandboxAdapter
    from plural.studio import Studio

CREATE_TIMEOUT_SECONDS = 600.0
EXEC_GRACE_SECONDS = 60.0
DEFAULT_EXEC_TIMEOUT_SECONDS = 3600.0
CREDIT_POLL_SECONDS = 30.0


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
        detached_job_id: The recorded Job a detached run's sandbox runs. The
            sandbox lives as long as the run asks, and isn't ended for being
            idle while that Job runs.
    """

    def __init__(self, studio: Studio, *, runtime: str, detached_job_id: str | None = None) -> None:
        self._studio = studio
        self._runtime = runtime
        self._detached_job_id = detached_job_id

    async def create(self, requirements: SandboxRequirements) -> DaytonaSandboxAdapter:
        """Start a sandbox, waiting while the account has no credits for one."""
        budget = float(os.environ.get(CREDIT_PAUSE_VARIABLE) or DEFAULT_CREDIT_PAUSE_SECONDS)
        waited = 0.0
        while True:
            try:
                record = await asyncio.to_thread(
                    self._studio.request,
                    "POST",
                    "/compute/sandboxes",
                    json={
                        "runtime": self._runtime,
                        "requirements": requirements.model_dump(mode="json"),
                        **(
                            {"detached_job_id": self._detached_job_id}
                            if self._detached_job_id
                            else {}
                        ),
                    },
                    timeout=CREATE_TIMEOUT_SECONDS,
                )
                break
            except PluralError as exc:
                if exc.status_code != 402 or waited >= budget:
                    raise
                if not waited:
                    print(f"{exc} Waiting for credits to start it.", file=sys.stderr)
                wait = min(CREDIT_POLL_SECONDS, budget - waited)
                await asyncio.sleep(wait)
                waited += wait
        return cast("DaytonaSandboxAdapter", _HostedSandbox(self._studio, record))

    async def get(self, sandbox_id: str) -> DaytonaSandboxAdapter:
        """Reach a sandbox this project started, such as a detached run's.

        Raises:
            PluralError: When it has ended.
        """
        record = await asyncio.to_thread(
            self._studio.request, "GET", f"/compute/sandboxes/{quote(sandbox_id)}"
        )
        if record.get("status") != "running":
            reason = record.get("end_reason") or record.get("status")
            raise PluralError(f"Sandbox {sandbox_id} has ended ({reason}).")
        return cast("DaytonaSandboxAdapter", _HostedSandbox(self._studio, record))

    async def delete(self, sandbox: DaytonaSandboxAdapter) -> None:
        hosted = cast(_HostedSandbox, sandbox)
        await asyncio.to_thread(self._studio.request, "DELETE", hosted.path)

    async def delete_by_id(self, sandbox_id: str) -> None:
        """End a sandbox this project started, by id."""
        await asyncio.to_thread(
            self._studio.request, "DELETE", f"/compute/sandboxes/{quote(sandbox_id)}"
        )

    async def close(self) -> None:
        """Nothing to close: every call is a request to the hosted API."""


__all__ = ["HostedDaytonaAdapter"]
