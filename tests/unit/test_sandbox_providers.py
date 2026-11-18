from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

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
from plural.sandbox.daytona import DaytonaSandboxAdapter, _OfficialSandbox
from plural.sandbox.hosted_daytona import _HostedSandbox


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
        except (FileNotFoundError, ValueError):
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
    assert client.sandbox.commands[-1][0] == ("python", "agent.py")
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


async def test_daytona_sends_whole_seconds_and_reports_timeouts() -> None:
    sent: list[dict[str, object]] = []

    class DaytonaTimeoutError(Exception):
        pass

    class Process:
        async def exec(self, command: str, **kwargs: object) -> object:
            sent.append(kwargs)
            if command == "sleep 5":
                raise DaytonaTimeoutError("command execution timeout")
            return type("Result", (), {"exit_code": 0, "result": "ok"})()

    official = _OfficialSandbox(type("Value", (), {"process": Process()})())
    await official.exec(("true",), cwd="/workspace", env={}, timeout=120.5)
    await official.exec(("true",), cwd="/workspace", env={}, timeout=None)
    assert [item["timeout"] for item in sent] == [121, None]

    class Studio:
        def request(self, method: str, path: str, **kwargs: object) -> object:
            return {"exit_code": -1, "stdout": "", "stderr": "", "timed_out": True}

    hosted = _HostedSandbox(cast(Any, Studio()), {"id": "sb-1"})
    for sandbox in (official, hosted):
        client = FakeDaytonaClient()
        client.sandbox = cast(Any, sandbox)
        provider = DaytonaProvider(adapter=client)
        handle = await provider.create(SandboxRequirements(image="python:3.12-slim"))
        result = await provider.exec(handle, ExecRequest(command=("sleep", "5"), timeout_seconds=2))
        assert result.timed_out
        assert result.exit_code == -1


def test_a_daytona_provider_makes_a_client_for_each_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plural.sandbox.daytona as daytona

    made: list[asyncio.AbstractEventLoop] = []

    class Client:
        def __init__(self) -> None:
            made.append(asyncio.get_running_loop())

        async def list(self, labels: Mapping[str, str]) -> tuple[()]:
            return ()

    monkeypatch.setattr(daytona, "OfficialDaytonaAdapter", Client)
    provider = DaytonaProvider(environ={})

    async def twice() -> None:
        await provider.list_sandboxes({})
        await provider.list_sandboxes({})

    asyncio.run(twice())
    asyncio.run(provider.list_sandboxes({}))
    assert len(made) == 2 and made[0] is not made[1]


class _LeavesFailedBuilds(FakeDaytonaClient):
    """A client whose create fails after Daytona made the sandbox, as a failed build does."""

    def __init__(self) -> None:
        super().__init__()
        self.left: dict[str, dict[str, str]] = {"other": {"plural.owner": "someone-else"}}
        self.deleted_ids: list[str] = []

    async def create(self, requirements: SandboxRequirements) -> DaytonaSandboxAdapter:
        self.left["failed-1"] = dict(requirements.labels)
        raise RuntimeError("Failed to create sandbox: build failed")

    async def list(self, labels: Mapping[str, str]) -> tuple[Any, ...]:
        from plural.sandbox.models import SandboxSummary

        return tuple(
            SandboxSummary(sandbox_id=key, provider="daytona", labels=value, state="build_failed")
            for key, value in self.left.items()
            if labels.items() <= value.items()
        )

    async def delete_by_id(self, sandbox_id: str) -> None:
        self.deleted_ids.append(sandbox_id)
        self.left.pop(sandbox_id, None)


async def test_a_failed_daytona_create_deletes_the_sandbox_it_left_behind() -> None:
    from plural.sandbox.sweep import trial_labels

    client = _LeavesFailedBuilds()
    provider = DaytonaProvider(adapter=client, environ={})
    labels = trial_labels(
        job="job-1", trial="trl-1", execution="0", environ={"PLURAL_SANDBOX_OWNER": "me"}
    )
    with pytest.raises(RuntimeError, match="build failed"):
        await provider.create(SandboxRequirements(image="python:3.12", labels=labels))
    assert client.deleted_ids == ["failed-1"]
    assert list(client.left) == ["other"]

    # Without an execution's own labels nothing is deleted: they could be anyone's.
    with pytest.raises(RuntimeError):
        await provider.create(SandboxRequirements(image="python:3.12"))
    assert client.deleted_ids == ["failed-1"]


async def test_a_daytona_sandbox_whose_workspace_setup_fails_is_deleted() -> None:
    client = FakeDaytonaClient()

    async def refuse(*args: Any, **kwargs: Any) -> tuple[int, str, str]:
        raise ConnectionError("toolbox unreachable")

    client.sandbox.exec = refuse  # type: ignore[method-assign]
    provider = DaytonaProvider(adapter=client, environ={})
    with pytest.raises(ConnectionError):
        await provider.create(SandboxRequirements(image="python:3.12"))
    assert client.deleted == [client.sandbox]


async def test_the_daytona_listing_asks_for_failed_builds_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataclasses
    import enum
    import sys
    import types

    from plural.sandbox.daytona import FAILED_STATES, OfficialDaytonaAdapter

    class SandboxState(enum.Enum):
        STARTED = "started"
        BUILD_FAILED = "build_failed"
        ERROR = "error"

    @dataclasses.dataclass
    class ListSandboxesQuery:
        labels: dict[str, str]
        states: list[Any] | None = None

    sandboxes = [
        types.SimpleNamespace(id="ok-1", state=SandboxState.STARTED, labels={"plural.owner": "me"}),
        types.SimpleNamespace(
            id="failed-1", state=SandboxState.BUILD_FAILED, labels={"plural.owner": "me"}
        ),
    ]
    queries: list[ListSandboxesQuery] = []

    class Client:
        async def list(self, query: ListSandboxesQuery) -> Any:
            queries.append(query)
            for item in sandboxes:
                # Like an API whose default listing leaves failed builds out.
                failed = item.state is not SandboxState.STARTED
                if failed == bool(query.states) and (
                    not query.states or item.state in query.states
                ):
                    yield item

    monkeypatch.setitem(
        sys.modules,
        "daytona",
        types.SimpleNamespace(ListSandboxesQuery=ListSandboxesQuery, SandboxState=SandboxState),
    )
    adapter = object.__new__(OfficialDaytonaAdapter)
    adapter._client = Client()  # type: ignore[attr-defined]
    found = await adapter.list({"plural.owner": "me"})
    assert {(item.sandbox_id, item.state) for item in found} == {
        ("ok-1", "started"),
        ("failed-1", "build_failed"),
    }
    assert [state.value for state in queries[1].states or ()] == list(FAILED_STATES)
