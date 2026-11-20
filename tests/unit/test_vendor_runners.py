from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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


def test_messages_bridge_keeps_cache_breakpoints_and_reports_cache_use() -> None:
    mark = {"type": "ephemeral"}
    request = messages_bridge._to_openai(
        {
            "model": "anthropic/claude-haiku-4-5",
            "system": [
                {"type": "text", "text": "You are Claude Code."},
                {"type": "text", "text": "Long instructions.", "cache_control": mark},
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hi", "cache_control": mark}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": [{"type": "text", "text": "file", "cache_control": mark}],
                        }
                    ],
                },
            ],
        }
    )
    system, user, _assistant, result = request["messages"]
    assert system["content"] == [
        {"type": "text", "text": "You are Claude Code."},
        {"type": "text", "text": "Long instructions.", "cache_control": mark},
    ]
    assert user["content"] == [{"type": "text", "text": "Hi", "cache_control": mark}]
    assert result["content"] == [{"type": "text", "text": "file", "cache_control": mark}]
    plain = messages_bridge._to_openai(
        {"system": [{"type": "text", "text": "Be brief."}], "messages": []}
    )
    assert plain["messages"] == [{"role": "system", "content": "Be brief."}]
    response = messages_bridge._from_openai(
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 60},
            },
        },
        model="anthropic/claude-haiku-4-5",
    )
    assert response["usage"] == {
        "input_tokens": 40,
        "output_tokens": 5,
        "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 60,
    }


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


def test_hermes_calls_only_the_bridge_and_never_holds_a_provider_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = json.dumps(_request()) + "\n"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLURAL_API_KEY", "job-key")
    monkeypatch.setenv("PLURAL_GATEWAY_URL", "https://gateway.example/v1")
    # Set, so the test restores them; the adapter removes or replaces each.
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY", "HERMES_HOME"):
        monkeypatch.setenv(name, "this-machine")
    monkeypatch.setenv("CUSTOM_BASE_URL", "unset")
    monkeypatch.setattr(vendor_adapter.sys, "argv", ["vendor_adapter.py", "hermes"])
    monkeypatch.setattr(vendor_adapter.sys, "stdin", io.StringIO(request))
    monkeypatch.setattr(vendor_adapter.shutil, "which", lambda _name: "/usr/bin/hermes")
    seen: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def _run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        del kwargs
        seen.append((tuple(command), dict(vendor_adapter.os.environ)))
        return SimpleNamespace(returncode=0, stdout="done\n", stderr="")

    monkeypatch.setattr(vendor_adapter.subprocess, "run", _run)
    vendor_adapter.main()
    command, environ = seen[0]
    assert command[:2] == ("hermes", "-z")
    assert command[command.index("--provider") + 1] == "custom"
    assert "--ignore-user-config" in command and "--ignore-rules" in command
    assert environ["CUSTOM_BASE_URL"].startswith("http://127.0.0.1:")
    assert environ["HERMES_HOME"] == str((tmp_path / ".plural" / "hermes").resolve())
    assert not {"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY"} & set(environ)
    assert "job-key" not in json.dumps(command)


def test_the_bridge_passes_chat_completions_through_and_streams_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    sent: list[dict[str, object]] = []
    answer = {
        "id": "chatcmpl-1",
        "model": "openai/gpt-5.6-luna",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "write_file", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 3},
    }

    def gateway(payload: dict[str, object], timeout: float) -> dict[str, object]:
        del timeout
        sent.append(payload)
        return answer

    monkeypatch.setattr(responses_bridge, "_gateway_request", gateway)
    server, url = responses_bridge.start(deadline=10**12)
    try:
        messages = [{"role": "developer", "content": "Be brief."}]
        body = {"model": "openai/gpt-5.6-luna", "messages": messages, "stream": True}
        request = urllib.request.Request(
            f"{url}/chat/completions",
            data=json.dumps({**body, "stream_options": {"include_usage": True}}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer ignored"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            lines = response.read().decode().split("\n\n")
    finally:
        server.shutdown()
    assert sent == [
        {"model": "openai/gpt-5.6-luna", "messages": [{"role": "system", "content": "Be brief."}]}
    ]
    chunks = [
        json.loads(line.removeprefix("data: ")) for line in lines if line.startswith("data: {")
    ]
    assert chunks[0]["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert chunks[1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"] == answer["usage"]
    assert "data: [DONE]" in lines


def test_claude_code_reports_a_call_to_a_missing_tool_as_unknown_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plural.apps import daemon

    monkeypatch.chdir(tmp_path)
    from plural.harness.interface import HarnessEnvironment

    environment = HarnessEnvironment({"tool_command": ["tool"], "workspace": str(tmp_path)})
    vendor_adapter._write_claude_settings(environment)
    settings = json.loads((tmp_path / ".plural/claude-settings.json").read_text())
    hooks = settings["hooks"]
    assert hooks["PostToolUse"] == hooks["PostToolUseFailure"]
    assert settings["permissions"]["allow"] == ["mcp__plural-environment"]

    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(daemon, "call", lambda op, **fields: calls.append((op, fields)) or {})
    missing = {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "lookup_prices",
        "tool_input": {"grade": "A36"},
        "error": "<tool_use_error>Error: No such tool available: lookup_prices</tool_use_error>",
    }
    environment_call = {
        "hook_event_name": "PostToolUse",
        "tool_name": "mcp__plural-environment__quote",
        "tool_input": {},
        "tool_response": {"content": "ok"},
    }
    own = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    for payload in (missing, environment_call, own):
        monkeypatch.setattr(daemon.sys, "stdin", io.StringIO(json.dumps(payload)))
        daemon._report_tool(tmp_path, ["--claude-hook"], None)
    assert [(op, fields["name"]) for op, fields in calls] == [("tool", "Bash")]

    read = vendor_adapter.ClaudeUnknownTools().event
    use = {"type": "tool_use", "id": "t1", "name": "lookup_prices", "input": {"grade": "A36"}}
    known = {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls"}}
    assert read({"type": "assistant", "message": {"content": [use, known]}}) == []
    results = [
        {"type": "tool_result", "tool_use_id": "t2", "content": "ok"},
        {
            "type": "tool_result",
            "tool_use_id": "t1",
            "is_error": True,
            "content": [{"type": "text", "text": missing["error"]}],
        },
    ]
    assert read({"type": "user", "message": {"content": results}}) == [
        ("step", {"action": "lookup_prices", "arguments": {"grade": "A36"}, "unknown": True})
    ]


def test_claude_codes_answer_is_its_last_stream_result() -> None:
    stream = "\n".join(
        json.dumps(event)
        for event in (
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hm"}]}},
            {"type": "result", "subtype": "success", "result": "Quoted."},
        )
    )
    assert vendor_adapter._response("claude-code", stream) == "Quoted."
    assert vendor_adapter._response("claude-code", json.dumps({"result": "Old."})) == "Old."


def test_the_environment_bridge_starts_where_no_bare_python_is_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vendor_adapter.shutil, "which", lambda _name: None)
    vendor_adapter._write_environment({"workspace": str(tmp_path)})
    config = json.loads((tmp_path / ".plural/mcp.json").read_text())
    server = config["mcpServers"]["plural-environment"]
    assert server["command"] == vendor_adapter.sys.executable


def test_the_environment_bridge_finds_the_local_runtimes_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLURAL_SANDBOX_ROOT", str(tmp_path))
    environment = {"workspace": "/workspace/environment"}
    assert mcp_bridge._workspace(environment) == str(tmp_path / "workspace/environment")
    inside = {"workspace": str(tmp_path / "workspace/environment")}
    assert mcp_bridge._workspace(inside) == str(tmp_path / "workspace/environment")
    monkeypatch.delenv("PLURAL_SANDBOX_ROOT")
    assert mcp_bridge._workspace(environment) == "/workspace/environment"


def test_codex_is_given_the_environments_mcp_server(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "plural-environment": {
                        "command": "/venv/bin/python",
                        "args": ["/p/mcp_bridge.py"],
                        "env": {"PLURAL_ENVIRONMENT_FILE": "/w/environment.json"},
                    }
                }
            }
        )
    )
    command = vendor_adapter._command("codex", "openai/gpt-5.6-luna", "go", {}, config)
    overrides = [command[i + 1] for i, item in enumerate(command) if item == "-c"]
    assert 'mcp_servers.plural-environment.command="/venv/bin/python"' in overrides
    assert 'mcp_servers.plural-environment.args=["/p/mcp_bridge.py"]' in overrides
    assert (
        'mcp_servers.plural-environment.env={PLURAL_ENVIRONMENT_FILE="/w/environment.json"}'
        in overrides
    )
    assert 'mcp_servers.plural-environment.default_tools_approval_mode="approve"' in overrides
    assert command[-1] == "go"
    assert vendor_adapter._codex_mcp_args(tmp_path / "missing.json") == []
