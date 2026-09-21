from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from plural.common import FileDeclaration, HarnessProtocol
from plural.harness.builtins import resolve_builtin_package
from plural.harness.install import main as install_main
from plural.harness.protocol import HarnessRunRequest
from plural.harness.runner import HarnessExecutionError, HarnessRunner
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
)


class RecordingProvider(SandboxProvider):
    name = "docker"

    def __init__(self) -> None:
        self.requests: list[ExecRequest] = []
        self.fail_setup = False

    async def capabilities(self) -> ProviderCapabilities:
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
        )

    async def doctor(self) -> ProviderDoctor:
        return ProviderDoctor(
            name=self.name,
            available=True,
            healthy=True,
            capabilities=("timeout",),
        )

    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        del requirements
        return SandboxHandle(sandbox_id="box", provider=self.name)

    async def upload_files(
        self,
        handle: SandboxHandle,
        files: Sequence[FileUpload],
        *,
        root: str = "/workspace",
    ) -> None:
        del handle, files, root

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        del handle
        self.requests.append(request)
        if self.fail_setup and request.user == "root":
            return ExecResult(
                exit_code=1,
                stdout=b"",
                stderr=b"network is blocked",
                duration_seconds=0.01,
            )
        event = (
            b'{"protocol":"plural-harness-v1","type":"result","status":"succeeded",'
            b'"outputs":["result.json"],"artifacts":["trajectory.jsonl"]}\n'
        )
        return ExecResult(exit_code=0, stdout=event, stderr=b"", duration_seconds=0.01)

    async def download_files(
        self, handle: SandboxHandle, paths: Sequence[str], *, root: str = "/workspace"
    ) -> tuple[DownloadedFile, ...]:
        del handle, root
        return tuple(DownloadedFile(path=path, data=b"{}") for path in paths)

    async def cancel(self, handle: SandboxHandle) -> None:
        del handle

    async def destroy(self, handle: SandboxHandle) -> None:
        del handle


def _request() -> HarnessRunRequest:
    return HarnessRunRequest(
        request_id="trial",
        task={"task_id": "one"},
        agent={"name": "agent", "model": "openai/gpt-5.6-luna"},
        environment={"name": "world", "actions": [], "workspace": "/workspace/environment"},
        workspace="/workspace/harness",
    )


async def test_setup_runs_as_root_then_harness_as_default_user() -> None:
    provider = RecordingProvider()
    package = resolve_builtin_package("hermes", {"version": "0.19.0"})
    await HarnessRunner(provider).run(
        SandboxHandle(sandbox_id="box", provider="docker"),
        package.definition,
        _request(),
    )
    assert provider.requests[0].user == "root"
    assert provider.requests[0].command[1] == "install.py"
    assert provider.requests[0].env["PLURAL_RUNTIME_PROVIDER"] == "docker"
    assert provider.requests[-1].user is None
    assert provider.requests[-1].command[2] == "plural.harness.class_runner"
    assert provider.requests[-1].command[-1].endswith(":HermesHarness")
    assert "/workspace/harness/.plural/tools/bin" in provider.requests[-1].env["PATH"]


async def test_setup_failure_is_clear() -> None:
    provider = RecordingProvider()
    provider.fail_setup = True
    definition = HarnessProtocol(
        name="codex",
        implementation="runnable",
        command=("python", "vendor_adapter.py", "codex"),
        setup=(("python", "install.py", "codex", "0.153.2"),),
        outputs=(FileDeclaration(path="result.json"),),
        artifacts=(FileDeclaration(path="trajectory.jsonl"),),
        trajectory_path="trajectory.jsonl",
    )
    with pytest.raises(HarnessExecutionError, match="setup failed"):
        await HarnessRunner(provider).run(
            SandboxHandle(sandbox_id="box", provider="docker"),
            definition,
            _request(),
        )


def test_local_installer_skips_when_binary_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLURAL_RUNTIME_PROVIDER", "local")
    monkeypatch.setattr("plural.harness.install.shutil.which", lambda _name: "/usr/bin/hermes")
    install_main(["hermes", "0.19.0"])


async def test_builtin_setup_contract_for_each_vendor_and_provider() -> None:
    request = _request()
    for provider_name in ("local", "docker"):
        for name in ("hermes", "claude-code", "codex"):
            provider = RecordingProvider()
            provider.name = provider_name
            package = resolve_builtin_package(name, {})
            await HarnessRunner(provider).run(
                SandboxHandle(sandbox_id="box", provider=provider_name),
                package.definition,
                request,
            )
            assert provider.requests[0].user == "root"
            assert provider.requests[0].env["PLURAL_RUNTIME_PROVIDER"] == provider_name
            assert provider.requests[0].command[-2] == name
            assert provider.requests[-1].command[2] == "plural.harness.class_runner"
            assert provider.requests[-1].user is None


def test_local_installer_fails_clearly_without_node(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLURAL_RUNTIME_PROVIDER", "local")
    monkeypatch.setenv("PLURAL_TOOLS_PREFIX", str(tmp_path / "tools"))
    monkeypatch.setattr("plural.harness.install.shutil.which", lambda _name: None)
    with pytest.raises(SystemExit, match="Node.js"):
        install_main(["claude-code", "2.1.236"])
