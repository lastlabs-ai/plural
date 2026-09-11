from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from plural.domain import FileDeclaration, HarnessDefinition
from plural.harness import HarnessRunner, HarnessRunRequest, native_runner, vendor_adapter
from plural.harness.retrieval import build_archive, package_from_archive, retrieve_archive
from plural.sandbox import LocalProvider, NetworkMode, SandboxRequirements


def _request() -> HarnessRunRequest:
    return HarnessRunRequest(
        request_id="test",
        task={"task_id": "one", "input": "hello", "metadata": {}},
        agent={"name": "agent", "model": "test/model", "routing": {}},
        environment={
            "name": "test",
            "instructions": "Solve the task.",
            "context": {"public": True},
            "actions": [],
            "limits": {"max_turns": 2, "max_seconds": 10},
            "guardrails": [],
            "workspace": "/workspace",
        },
    )


def test_raw_acp_manifest_is_rejected() -> None:
    try:
        HarnessDefinition(name="acp", protocol="acp", command=("agent",))
    except ValidationError as exc:
        assert "protocol_adapter='acp-client-v1'" in str(exc)
    else:
        raise AssertionError("raw ACP support was advertised")


async def test_acp_adapter_runs_json_rpc_lifecycle(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    agent = source / "agent.py"
    agent.write_text(
        """
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": 1}
    elif method == "session/new":
        result = {"sessionId": "session-1"}
    elif method == "session/prompt":
        update = {"jsonrpc":"2.0","method":"session/update",
                  "params":{"update":{"type":"text","text":"finished"}}}
        print(json.dumps(update), flush=True)
        result = {"stopReason": "end_turn"}
    else:
        continue
    print(json.dumps({"jsonrpc":"2.0","id":message["id"],"result":result}), flush=True)
""".lstrip(),
        encoding="utf-8",
    )
    manifest = HarnessDefinition(
        name="acp",
        protocol="acp",
        protocol_adapter="acp-client-v1",
        command=("python", "agent.py"),
        outputs=(FileDeclaration(path="result.json"),),
        artifacts=(FileDeclaration(path="trajectory.jsonl"),),
    )
    provider = LocalProvider(base_dir=tmp_path / "sandboxes")
    (tmp_path / "sandboxes").mkdir()
    handle = await provider.create(SandboxRequirements(network=NetworkMode.FULL))
    try:
        await provider.upload_bundle(handle, source, root="/workspace")
        execution = await HarnessRunner(provider).run(handle, manifest, _request())
        files = await provider.download_files(handle, ("result.json",))
        result = json.loads(files[0].data)
        assert execution.status == "succeeded"
        assert result["response"] == "finished"
        assert result["session_id"] == "session-1"
    finally:
        await provider.destroy(handle)


def test_archive_is_deterministic_verified_and_cached(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "harness.yaml").write_text(
        """
manifest:
  schema_version: "2"
  name: archived
  revision: "0.1.0"
  implementation: runnable
  command: [python, harness.py]
source:
  kind: local
  uri: .
  trusted: true
""".lstrip(),
        encoding="utf-8",
    )
    (package / "harness.py").write_text("print('ok')\n", encoding="utf-8")
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    digest = build_archive(package, first)
    assert build_archive(package, second) == digest
    assert first.read_bytes() == second.read_bytes()

    cache = tmp_path / "cache"
    loaded = package_from_archive(str(first), digest, cache_root=cache)
    assert loaded.definition.name == "archived"
    assert loaded.source.kind == "archive"
    cached = cache / digest[7:] / "package"
    assert retrieve_archive(str(first), digest, cache_root=cache) == cached

    (cached / "harness.py").write_text("tampered\n", encoding="utf-8")
    assert retrieve_archive(str(first), digest, cache_root=cache) == cached
    assert (cached / "harness.py").read_text(encoding="utf-8") == "print('ok')\n"

    (cache / digest[7:] / "archive.tar.gz").write_bytes(b"corrupt")
    assert retrieve_archive(str(first), digest, cache_root=cache) == cached
    assert (cached / "harness.py").read_text(encoding="utf-8") == "print('ok')\n"


def test_archive_rejects_traversal(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    archive_path = tmp_path / "bad.tar.gz"
    archive_path.write_bytes(payload.getvalue())
    import hashlib

    digest = f"sha256:{hashlib.sha256(payload.getvalue()).hexdigest()}"
    try:
        retrieve_archive(str(archive_path), digest, cache_root=tmp_path / "cache")
    except ValueError as exc:
        assert "unsafe archive path" in str(exc)
    else:
        raise AssertionError("archive traversal was extracted")


def test_trajectory_path_must_be_declared_as_artifact() -> None:
    with pytest.raises(ValidationError, match="trajectory_path must be declared"):
        HarnessDefinition(
            name="bad-trajectory",
            command=("python", "harness.py"),
            trajectory_path="trajectory.jsonl",
        )


def test_native_actions_executes_only_declared_actions(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    tool = tmp_path / "tool.py"
    tool.write_text(
        "import json,sys; print(json.dumps({'seen': json.load(sys.stdin)['value']}))\n",
        encoding="utf-8",
    )
    responses = iter(
        (
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "inspect",
                                        "arguments": '{"value": 7}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"cost_usd": 0.01},
            },
            {
                "choices": [{"message": {"role": "assistant", "content": "complete"}}],
                "usage": {"cost_usd": 0.01},
            },
        )
    )
    monkeypatch.setattr(native_runner, "_model_call", lambda **_kwargs: next(responses))
    request = _request().model_dump(mode="json")
    request["environment"]["actions"] = [
        {
            "name": "inspect",
            "description": "Inspect a value",
            "command": ["python", "tool.py"],
            "parameters": {"type": "object"},
            "timeout_seconds": 2,
        }
    ]
    request["environment"]["workspace"] = str(tmp_path)
    request["environment"]["limits"]["max_cost_usd"] = 1

    result, trajectory, _trace_id = native_runner._run("native.actions.v1", request)

    assert result["response"] == "complete"
    assert result["turns"] == 2
    assert result["cost_usd"] == 0.02
    assert '"seen": 7' in trajectory[1]["observation"]["content"]


def test_vendor_adapter_invokes_installed_cli_and_translates(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    request = _request().model_dump_json() + "\n"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vendor_adapter.sys, "argv", ["vendor_adapter.py", "claude-code"])
    monkeypatch.setattr(vendor_adapter.sys, "stdin", io.StringIO(request))
    monkeypatch.setattr(vendor_adapter.shutil, "which", lambda _name: "/usr/bin/claude")
    monkeypatch.setattr(
        vendor_adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout='{"result":"vendor answer"}',
            stderr="",
        ),
    )

    vendor_adapter.main()

    assert json.loads((tmp_path / "result.json").read_text())["response"] == "vendor answer"
    event = json.loads(capsys.readouterr().out)
    assert event["status"] == "succeeded"
