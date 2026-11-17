from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plural.harness import mcp_bridge, messages_bridge, responses_bridge, vendor_adapter


def _request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "task": {"task_id": "one", "instructions": "Solve it."},
        "agent": {
            "name": "agent",
            "model": "openai/gpt-5.6-luna",
            "harness": "codex",
            "harness_config": {"version": "0.153.2"},
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
    # Set, so the test restores them; the adapter replaces both.
    monkeypatch.setenv("CODEX_HOME", "/home/user/.codex")
    monkeypatch.setenv("PLURAL_CODEX_BASE_URL", "unset")
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
    # Codex has its own home, never the machine's login, and calls models only via the bridge.
    assert environ["CODEX_HOME"] == str((tmp_path / ".plural" / "codex").resolve())
    bridge = environ["PLURAL_CODEX_BASE_URL"]
    assert bridge.startswith("http://127.0.0.1:")
    assert "model_provider=plural" in command
    assert f"model_providers.plural.base_url={json.dumps(bridge)}" in command
    assert "--skip-git-repo-check" in command
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
        captured["timeout"] = timeout
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
        },
        900.0,
    )
    assert captured["timeout"] == 900.0
    assert captured["url"] == "https://gateway.example/v1/chat/completions"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert translated["content"][0]["text"] == "hello from gateway"
    assert translated["usage"]["output_tokens"] == 3


def test_messages_bridge_carries_tools_both_ways() -> None:
    request = messages_bridge._to_openai(
        {
            "model": "anthropic/claude-haiku-4-5",
            "tools": [
                {"name": "Write", "description": "Write a file", "input_schema": {"type": "object"}}
            ],
            "tool_choice": {"type": "any"},
            "messages": [
                {"role": "user", "content": "Write it."},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Writing."},
                        {"type": "tool_use", "id": "t1", "name": "Write", "input": {"path": "a"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": "denied",
                            "is_error": True,
                        },
                        {"type": "text", "text": "Try again."},
                    ],
                },
            ],
        }
    )
    assert request["tools"][0]["function"]["name"] == "Write"
    assert request["tool_choice"] == "required"
    assistant, result, follow_up = request["messages"][1:]
    assert assistant["tool_calls"][0]["function"] == {"name": "Write", "arguments": '{"path": "a"}'}
    assert result == {"role": "tool", "tool_call_id": "t1", "content": "Error: denied"}
    assert follow_up == {"role": "user", "content": "Try again."}

    response = messages_bridge._from_openai(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {"name": "Write", "arguments": '{"path": "b"}'},
                            }
                        ],
                    },
                }
            ]
        },
        model="anthropic/claude-haiku-4-5",
    )
    assert response["stop_reason"] == "tool_use"
    assert response["content"] == [
        {"type": "tool_use", "id": "c1", "name": "Write", "input": {"path": "b"}}
    ]


def test_responses_bridge_reads_codex_tools_and_answers_in_kind() -> None:
    request, tools = responses_bridge.to_chat(
        {
            "model": "openai/gpt-5.6-luna",
            "instructions": "Be careful.",
            "input": [
                {
                    "type": "additional_tools",
                    "tools": [
                        {
                            "type": "namespace",
                            "name": "functions",
                            "tools": [
                                {"type": "custom", "name": "exec", "format": {"type": "grammar"}},
                                {"type": "function", "name": "wait", "parameters": {}},
                            ],
                        },
                        {
                            "type": "namespace",
                            "name": "mcp__files",
                            "tools": [{"type": "function", "name": "read", "parameters": {}}],
                        },
                    ],
                },
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "Rules."}],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Go."}],
                },
                {"type": "custom_tool_call", "name": "exec", "call_id": "c1", "input": "text(1)"},
                {"type": "custom_tool_call_output", "call_id": "c1", "output": "1"},
            ],
        }
    )
    names = [tool["function"]["name"] for tool in request["tools"]]
    assert names == ["exec", "wait", "mcp__files__read"]
    assert tools.custom == {"exec"} and tools.namespaces == {"mcp__files"}
    assert [message["role"] for message in request["messages"]] == [
        "system",
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert (
        request["messages"][3]["tool_calls"][0]["function"]["arguments"] == '{"input": "text(1)"}'
    )

    response = responses_bridge.from_chat(
        {
            "choices": [
                {
                    "message": {
                        "content": "Working.",
                        "tool_calls": [
                            {
                                "id": "a",
                                "function": {"name": "exec", "arguments": '{"input": "x()"}'},
                            },
                            {
                                "id": "b",
                                "function": {"name": "mcp__files__read", "arguments": "{}"},
                            },
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
        tools,
    )
    message, freeform, function = response["output"]
    assert message["content"][0]["text"] == "Working."
    assert (freeform["type"], freeform["name"], freeform["input"]) == (
        "custom_tool_call",
        "exec",
        "x()",
    )
    assert (function["type"], function["namespace"], function["name"]) == (
        "function_call",
        "mcp__files",
        "read",
    )
    assert response["usage"]["total_tokens"] == 7
    events = responses_bridge.stream_events(response)
    assert events[0]["type"] == "response.created"
    assert events[-1] == {**events[-1], "type": "response.completed", "response": response}
    done = [event["item"] for event in events if event["type"] == "response.output_item.done"]
    assert done == response["output"]


def test_claude_code_never_reads_this_machines_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = {"name": "agent", "model": "anthropic/claude-haiku-4-5", "harness": "claude-code"}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLURAL_API_KEY", "job-key")
    monkeypatch.setenv("PLURAL_GATEWAY_URL", "https://gateway.example/v1")
    for name in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(name, "from-this-machine")
    monkeypatch.setattr(vendor_adapter.sys, "argv", ["vendor_adapter.py", "claude-code"])
    monkeypatch.setattr(
        vendor_adapter.sys, "stdin", io.StringIO(json.dumps(_request(agent=agent)) + "\n")
    )
    monkeypatch.setattr(vendor_adapter.shutil, "which", lambda _name: "/usr/bin/claude")
    seen: list[dict[str, str]] = []

    def _run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        del command, kwargs
        seen.append(dict(vendor_adapter.os.environ))
        return SimpleNamespace(returncode=0, stdout='{"result": "done"}', stderr="")

    monkeypatch.setattr(vendor_adapter.subprocess, "run", _run)
    vendor_adapter.main()
    assert seen[0]["CLAUDE_CONFIG_DIR"] == str((tmp_path / ".plural" / "claude").resolve())
    assert seen[0]["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:")
    assert seen[0]["ANTHROPIC_API_KEY"] == "job-key"
