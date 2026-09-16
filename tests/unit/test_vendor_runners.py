from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plural.harness import mcp_bridge, messages_bridge, vendor_adapter


def _request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "task": {"task_id": "one", "instructions": "Solve it."},
        "agent": {
            "name": "agent",
            "model": "openai/gpt-5.6-luna",
            "harness": "codex",
            "harness_kwargs": {"version": "0.153.2"},
        },
        "environment": {
            "name": "world",
            "observation": {"ticket": "open"},
            "actions": [
                {
                    "name": "lookup",
                    "description": "Look up a ticket.",
                    "command": ["python", "-c", "print('{\"ok\": true}')"],
                    "parameters": {"type": "object"},
                }
            ],
            "limits": {"max_seconds": 10},
            "workspace": "/workspace/environment",
        },
    }
    payload.update(overrides)
    return payload


def test_vendor_adapter_maps_job_credentials_and_normalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = json.dumps(_request()) + "\n"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLURAL_API_KEY", "job-key")
    monkeypatch.setenv("PLURAL_GATEWAY_URL", "https://gateway.example/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(vendor_adapter.sys, "argv", ["vendor_adapter.py", "codex"])
    monkeypatch.setattr(vendor_adapter.sys, "stdin", io.StringIO(request))
    monkeypatch.setattr(vendor_adapter.shutil, "which", lambda _name: "/usr/bin/codex")
    seen: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def _run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        del kwargs
        seen.append((tuple(command), dict(vendor_adapter.os.environ)))
        return SimpleNamespace(
            returncode=0,
            stdout='{"item":{"text":"done"}}\n',
            stderr="log-line",
        )

    monkeypatch.setattr(vendor_adapter.subprocess, "run", _run)
    vendor_adapter.main()
    command, environ = seen[0]
    assert command[0] == "codex"
    assert environ["OPENAI_API_KEY"] == "job-key"
    assert environ["OPENAI_BASE_URL"] == "https://gateway.example/v1"
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["response"] == "done"
    assert (tmp_path / "trajectory.jsonl").is_file()
    assert "log-line" in (tmp_path / "logs.txt").read_text(encoding="utf-8")
    event = json.loads(capsys.readouterr().out)
    assert event["outputs"] == ["result.json"]
    assert "trajectory.jsonl" in event["artifacts"]
    assert (tmp_path / ".plural" / "mcp.json").is_file()


def test_vendor_adapter_fails_without_job_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PLURAL_ALLOW_NO_AUTH", raising=False)
    monkeypatch.setattr(vendor_adapter.sys, "argv", ["vendor_adapter.py", "hermes"])
    monkeypatch.setattr(vendor_adapter.sys, "stdin", io.StringIO(json.dumps(_request()) + "\n"))
    monkeypatch.setattr(vendor_adapter.shutil, "which", lambda _name: "/usr/bin/hermes")
    with pytest.raises(SystemExit, match="Job\\(client="):
        vendor_adapter.main()


def test_mcp_bridge_dispatches_environment_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment = tmp_path / "environment.json"
    environment.write_text(
        json.dumps(
            {
                "workspace": str(tmp_path),
                "actions": [
                    {
                        "name": "lookup",
                        "command": [
                            "python",
                            "-c",
                            "import json,sys; print(json.dumps(sys.stdin.read()))",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLURAL_ENVIRONMENT_FILE", str(environment))
    monkeypatch.setattr(
        mcp_bridge.sys,
        "stdin",
        io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            + "\n"
            + json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "lookup", "arguments": {"q": "ticket"}},
                }
            )
            + "\n"
        ),
    )
    mcp_bridge.main()
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0]["result"]["tools"][0]["name"] == "lookup"
    assert "ticket" in lines[1]["result"]["content"][0]["text"]


def test_messages_bridge_translates_to_openai_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "id": "chatcmpl-1",
                    "choices": [{"message": {"content": "hello from gateway"}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                }
            ).encode()

    def _urlopen(request: object, timeout: float = 0) -> _Response:
        del timeout
        captured["url"] = request.full_url  # type: ignore[attr-defined]
        captured["body"] = json.loads(request.data.decode())  # type: ignore[attr-defined]
        captured["auth"] = request.headers.get("Authorization")  # type: ignore[attr-defined]
        return _Response()

    monkeypatch.setenv("PLURAL_GATEWAY_URL", "https://gateway.example/v1")
    monkeypatch.setenv("PLURAL_API_KEY", "job-key")
    monkeypatch.setattr(messages_bridge.urllib.request, "urlopen", _urlopen)
    translated = messages_bridge._forward_messages(
        {
            "model": "anthropic/claude-sonnet-5",
            "system": "Be brief.",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
        }
    )
    assert captured["url"] == "https://gateway.example/v1/chat/completions"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert translated["content"][0]["text"] == "hello from gateway"
    assert translated["usage"]["output_tokens"] == 3
