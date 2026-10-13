"""Shared sandbox fakes for execution tests."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Sequence
from typing import Any

from plural.apps import daemon
from plural.sandbox import (
    Capability,
    DownloadedFile,
    ExecRequest,
    ExecResult,
    FileUpload,
    ProviderCapabilities,
    ProviderDoctor,
    SandboxHandle,
    SandboxProvider,
    SandboxRequirements,
)

_EPISODE = "".join(
    json.dumps(record) + "\n"
    for record in (
        {
            "schema": "plural.episode/v1",
            "sequence": 1,
            "kind": "model.call",
            "turn": 1,
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": "2026-01-01T00:00:01+00:00",
            "duration_ms": 1000,
            "model": "model",
            "messages_offset": 0,
            "messages": [{"role": "user", "content": "answer"}],
            "message_count": 1,
            "text": "42",
            "tool_calls": [],
            "usage": {"input_tokens": 10, "output_tokens": 2, "cost_usd": 0.01},
            "via_gateway": False,
            "error": None,
        },
    )
).encode()


class FakeProvider(SandboxProvider):
    def __init__(self, name: str, *, delay: float = 0, fail_first: bool = False) -> None:
        self.name = name
        self.delay = delay
        self.fail_first = fail_first
        self.created: list[SandboxRequirements] = []
        self.files: dict[str, dict[str, bytes]] = {}
        self.active = 0
        self.max_active = 0
        self.harness_runs = 0
        self.host_calls: list[ExecRequest] = []
        self.harness_requests: list[ExecRequest] = []
        self.bootstraps: dict[str, dict[str, Any]] = {}
        self.environments: dict[str, dict[str, Any]] = {}
        self.control_requests: list[dict[str, Any]] = []
        self.host_steps: list[dict[str, Any]] = []
        self.uploads: dict[str, bytes] = {}
        self.sealed: list[tuple[str, ...]] = []
        self.episode = _EPISODE
        self.result = b'{"answer": 42}'
        self.forge_host = False

    async def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.name,
            available=True,
            capabilities=frozenset(Capability),
        )

    async def doctor(self) -> ProviderDoctor:
        return ProviderDoctor(
            name=self.name,
            available=True,
            healthy=True,
            capabilities=tuple(item.value for item in Capability),
        )

    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        identifier = f"{self.name}-{len(self.created)}"
        self.created.append(requirements)
        self.files[identifier] = {}
        return SandboxHandle(sandbox_id=identifier, provider=self.name, image_identity="fake")

    async def upload_files(
        self,
        handle: SandboxHandle,
        files: Sequence[FileUpload],
        *,
        root: str = "/workspace",
    ) -> None:
        for item in files:
            self.files[handle.sandbox_id][item.path] = item.data
            self.uploads[item.path] = item.data

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        if request.command[:3] == ("python", "-m", "plural.apps.daemon"):
            return self._app_host(handle, request)
        if request.command[:2] == ("python", "-c"):
            return self._python(handle, request)
        if request.stdin is None:
            self.files[handle.sandbox_id]["verifier-result.json"] = json.dumps(
                {
                    "score": 1,
                    "scores": {"correct": 1},
                    "evidence": ["result.json"],
                }
            ).encode()
            return ExecResult(exit_code=0, duration_seconds=0.001)
        self.harness_runs += 1
        self.harness_requests.append(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_first and self.harness_runs == 1:
                return ExecResult(exit_code=2, stderr=b"temporary secret", duration_seconds=0.001)
            payload = json.loads(request.stdin)
            assert payload["model_resolution"]["catalog_model_id"] == "test/model"
            assert payload["model_resolution"]["upstream_id"] == "model"
            self.files[handle.sandbox_id]["result.json"] = self.result
            self.files[handle.sandbox_id]["episode.jsonl"] = self.episode
            self.files[handle.sandbox_id]["state.json"] = b'{"step": 1}'
            self.files[handle.sandbox_id]["observation.json"] = b'{"text": "done"}'
            self.files[handle.sandbox_id]["view.json"] = b'{"kind": "text", "text": "done"}'
            if "mode" in payload["environment"]:
                raise AssertionError("mode must not be injected into Environment payload")
            artifact_paths = ["episode.jsonl"]
            if payload["capture_tito"]:
                self.files[handle.sandbox_id]["tito.jsonl"] = (
                    json.dumps(
                        {
                            "schema_version": "1",
                            "step": 0,
                            "tokenizer": "test",
                            "model": "test/model",
                            "input_token_ids": [1],
                            "output_token_ids": [2],
                            "observation_token_ids": [3],
                            "output_logprobs": [-0.1],
                            "output_top_logprobs": [{"ok": -0.1}],
                            "output_text": "ok",
                            "assistant_message": {
                                "role": "assistant",
                                "content": "ok",
                            },
                            "input_len": 1,
                            "output_len": 1,
                            "observation_len": 1,
                        }
                    )
                    + "\n"
                ).encode()
                artifact_paths = ["tito.jsonl"]
            event = {
                "protocol": "plural-harness-v1",
                "type": "result",
                "status": "succeeded",
                "outputs": ["result.json"],
                "artifacts": artifact_paths,
                "trace_id": "trace-1",
            }
            return ExecResult(
                exit_code=0,
                stdout=(json.dumps(event) + "\n").encode(),
                duration_seconds=0.001,
            )
        finally:
            self.active -= 1

    def _app_host(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        """Answer App host commands as one App named ``game`` would, signing like the host."""
        self.host_calls.append(request)
        files = self.files[handle.sandbox_id]
        operation = request.command[3]
        if operation == "start":
            boot = json.loads(request.stdin or files.get(daemon.BOOTSTRAP_FILE) or b"{}")
            self.bootstraps[handle.sandbox_id] = boot
            self.environments[handle.sandbox_id] = json.loads(
                files.get(daemon.ENVIRONMENT_FILE) or b"{}"
            )
            return ExecResult(exit_code=0, stdout=b'{"ok": true}\n', duration_seconds=0.001)
        raw = request.stdin or base64.b64decode(request.command[5])
        sent = json.loads(raw)
        self.control_requests.append(sent)
        op = sent["op"]
        result: object = None
        if op == "hello":
            result = {"pid": 7, "uid": 65533, "private": "/workspace/.plural-apps-x"}
        elif op == "finish":
            declared = self.environments.get(handle.sandbox_id) or {}
            apps = {
                app["name"]: {"control": app.get("control", "owned"), "initial": {}, "final": {}}
                for app in declared.get("apps") or []
            }
            apps["game"] = {"control": "owned", "initial": {"step": 0}, "final": {"step": 1}}
            result = {
                "apps": apps,
                "steps": list(self.host_steps),
                "states": [{"step": 0, "state": {"game": {"step": 0}}}],
                "observation": {"text": "board"},
                "view": {},
            }
        elif op == "query":
            result = {"app": sent["app"], "action": sent["action"], **sent["arguments"]}
        elif op == "stop":
            result = "stopped"
        # A forged host signs without the Trial's token, which it never saw.
        token = "forged" if self.forge_host else str(self.bootstraps[handle.sandbox_id]["token"])
        payload = json.loads(daemon.canonical({"ok": True, "result": result}))
        signed = {**payload, "mac": daemon._mac(token, sent["nonce"], payload)}
        return ExecResult(
            exit_code=0, stdout=(json.dumps(signed) + "\n").encode(), duration_seconds=0.001
        )

    def _python(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        script = request.command[2]
        if "shutil.rmtree" in script:
            # The Job removing what it staged for the App host.
            files = self.files[handle.sandbox_id]
            self.sealed.append(request.command[4:])
            for name in request.command[4:]:
                for path in [item for item in files if item == name or item.startswith(name + "/")]:
                    del files[path]
            return ExecResult(exit_code=0, duration_seconds=0.001)
        if "os.access" in script:
            # The isolation probe: the Harness's user cannot read the host's folder.
            return ExecResult(exit_code=1, duration_seconds=0.001)
        # Plural's install probe: report this machine's version as installed.
        import plural

        version = json.dumps({"version": plural.__version__}).encode()
        return ExecResult(exit_code=0, stdout=version + b"\n", duration_seconds=0.001)

    async def download_files(
        self,
        handle: SandboxHandle,
        paths: Sequence[str],
        *,
        root: str = "/workspace",
    ) -> tuple[DownloadedFile, ...]:
        files = self.files[handle.sandbox_id]
        missing = [path for path in paths if path not in files]
        if missing:
            raise FileNotFoundError(missing[0])
        return tuple(DownloadedFile(path=path, data=files[path]) for path in paths)

    async def cancel(self, handle: SandboxHandle) -> None:
        return

    async def destroy(self, handle: SandboxHandle) -> None:
        return
