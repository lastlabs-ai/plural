from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from plural.common import HarnessProtocol
from plural.harness.protocol import HarnessRunRequest
from plural.harness.runner import HarnessRunner
from plural.sandbox import (
    CapabilityError,
    DaytonaProvider,
    ExecRequest,
    FileUpload,
    LocalProvider,
    NetworkMode,
    SandboxRequirements,
)
from plural.sandbox.daytona import DaytonaSandboxAdapter


async def test_local_provider_exec_timeout_transfer_and_cleanup(tmp_path: Path) -> None:
    provider = LocalProvider(base_dir=tmp_path)
    requirements = SandboxRequirements(network=NetworkMode.FULL)
    handle = await provider.create(requirements)
    await provider.upload_files(handle, (FileUpload(path="input.txt", data=b"hello"),))
    files = await provider.download_files(handle, ("input.txt",))
    assert files[0].data == b"hello"

    result = await provider.exec(
        handle,
        ExecRequest(
            command=("python", "-c", "import time; time.sleep(5)"),
            timeout_seconds=0.01,
        ),
    )
    assert result.timed_out is True
    await provider.destroy(handle)
    assert not any(tmp_path.iterdir())


async def test_local_preflight_rejects_unenforceable_network() -> None:
    provider = LocalProvider()
    try:
        await provider.preflight(SandboxRequirements(network=NetworkMode.NONE))
    except CapabilityError as exc:
        assert "network_none" in str(exc)
    else:
        raise AssertionError("local provider claimed network isolation")


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
async def test_local_cancel_terminates_descendant_processes(tmp_path: Path) -> None:
    provider = LocalProvider(base_dir=tmp_path)
    handle = await provider.create(SandboxRequirements(network=NetworkMode.FULL))
    execution = asyncio.create_task(
        provider.exec(
            handle,
            ExecRequest(
                command=(
                    "python",
                    "-c",
                    "import pathlib,subprocess,sys,time;"
                    "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                    "pathlib.Path('child.pid').write_text(str(p.pid));time.sleep(60)",
                )
            ),
        )
    )
    child_pid: int | None = None
    for _ in range(100):
        try:
            files = await provider.download_files(handle, ("child.pid",))
            child_pid = int(files[0].data)
            break
        except FileNotFoundError:
            await asyncio.sleep(0.01)
    assert child_pid is not None

    await provider.cancel(handle)
    await execution
    for _ in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("descendant process survived local cancellation")
    await provider.destroy(handle)


class FakeDaytonaSandbox:
    sandbox_id = "remote-1"
    image_identity = "snapshot-1"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.commands: list[
            tuple[tuple[str, ...], str, Mapping[str, str], float | None, str | None]
        ] = []
        self.stdout = "ok"

    async def upload_file(self, data: bytes, path: str) -> None:
        self.files[path] = data

    async def download_file(self, path: str) -> bytes:
        return self.files[path]

    async def exec(
        self,
        command: tuple[str, ...],
        *,
        cwd: str,
        env: Mapping[str, str],
        timeout: float | None,
        user: str | None = None,
    ) -> tuple[int, str, str]:
        self.commands.append((command, cwd, env, timeout, user))
        return 0, self.stdout, ""


class FakeDaytonaClient:
    def __init__(self) -> None:
        self.sandbox = FakeDaytonaSandbox()
        self.requirements: SandboxRequirements | None = None
        self.deleted: list[DaytonaSandboxAdapter] = []

    async def create(self, requirements: SandboxRequirements) -> DaytonaSandboxAdapter:
        self.requirements = requirements
        return self.sandbox

    async def delete(self, sandbox: DaytonaSandboxAdapter) -> None:
        self.deleted.append(sandbox)


async def test_daytona_provider_uses_adapter_without_importing_sdk() -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(adapter=client, environ={})
    requirements = SandboxRequirements(
        image="python:3.12",
        network=NetworkMode.RESTRICTED,
        network_allowlist=("api.example.com",),
    )
    handle = await provider.create(requirements)
    await provider.upload_files(handle, (FileUpload(path="a.txt", data=b"a"),))
    result = await provider.exec(
        handle,
        ExecRequest(
            command=("python", "agent.py"),
            env={"TOKEN": "secret"},
            timeout_seconds=3,
        ),
    )
    files = await provider.download_files(handle, ("a.txt",))
    await provider.destroy(handle)

    assert result.stdout == b"ok"
    assert files[0].data == b"a"
    assert client.requirements == requirements
    assert client.sandbox.commands[0][0] == ("python", "agent.py")
    assert len(client.deleted) == 1


async def test_daytona_rejects_unsupported_resource_controls() -> None:
    from plural.sandbox import ResourceRequirements

    provider = DaytonaProvider(adapter=FakeDaytonaClient(), environ={})
    try:
        await provider.preflight(
            SandboxRequirements(
                network=NetworkMode.NONE,
                resources=ResourceRequirements(pids=10),
            )
        )
    except CapabilityError as exc:
        assert "pids" in str(exc)
    else:
        raise AssertionError("unsupported Daytona limit was accepted")


async def test_daytona_harness_request_redirect_matches_custom_workspace() -> None:
    client = FakeDaytonaClient()
    client.sandbox.stdout = (
        '{"protocol":"plural-harness-v1","type":"result","status":"succeeded",'
        '"outputs":[],"artifacts":[]}\n'
    )
    provider = DaytonaProvider(adapter=client, environ={})
    handle = await provider.create(SandboxRequirements())
    request = HarnessRunRequest(
        request_id="custom-workspace",
        task={"task_id": "one", "input": "x"},
        agent={"name": "test", "model": "test/model"},
        environment={},
        workspace="/workspace/custom",
    )

    await HarnessRunner(provider).run(
        handle,
        HarnessProtocol(name="test", command=("python", "harness.py")),
        request,
    )

    assert "/workspace/custom/.plural/request.jsonl" in client.sandbox.files
    command = client.sandbox.commands[-1][0]
    assert command[4] == "/workspace/custom/.plural/request.jsonl"
    assert "/workspace/.plural/request.jsonl" not in command
