"""Shared sandbox fakes for execution tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

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

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        if request.stdin is None:
            self.files[handle.sandbox_id]["verifier-result.json"] = json.dumps(
                {
                    "reward": 1,
                    "scores": {"correct": 1},
                    "evidence": ["result.json"],
                }
            ).encode()
            return ExecResult(exit_code=0, duration_seconds=0.001)
        self.harness_runs += 1
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
            self.files[handle.sandbox_id]["result.json"] = b'{"answer": 42}'
            self.files[handle.sandbox_id]["trajectory.jsonl"] = (
                b'{"turn": 1}\n{"type": "cost", "cost_usd": 0.01}\n'
            )
            self.files[handle.sandbox_id]["state.json"] = b'{"step": 1}'
            self.files[handle.sandbox_id]["observation.json"] = b'{"text": "done"}'
            self.files[handle.sandbox_id]["view.json"] = b'{"kind": "text", "text": "done"}'
            if "mode" in payload["environment"]:
                raise AssertionError("mode must not be injected into Environment payload")
            artifact_paths = ["trajectory.jsonl"]
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

    async def download_files(
        self,
        handle: SandboxHandle,
        paths: Sequence[str],
        *,
        root: str = "/workspace",
    ) -> tuple[DownloadedFile, ...]:
        return tuple(
            DownloadedFile(path=path, data=self.files[handle.sandbox_id][path]) for path in paths
        )

    async def cancel(self, handle: SandboxHandle) -> None:
        return

    async def destroy(self, handle: SandboxHandle) -> None:
        return
