"""Stdio MCP server that exposes Plural Environment actions as tools."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def main() -> None:
    """Serve Environment actions over MCP stdio."""
    environment = _load_environment()
    tools = _tools(environment)
    reset = environment.get("reset_command") or []
    if isinstance(reset, list) and reset:
        _run_command(tuple(str(item) for item in reset), cwd=_workspace(environment))
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        message = json.loads(line)
        response = _handle(message, environment, tools)
        if response is not None:
            print(json.dumps(response, separators=(",", ":")), flush=True)


def _handle(
    message: dict[str, Any],
    environment: dict[str, Any],
    tools: list[dict[str, Any]],
) -> dict[str, Any] | None:
    method = message.get("method")
    ident = message.get("id")
    if method == "initialize":
        return _result(
            ident,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "plural-environment", "version": "1"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(ident, {"tools": tools})
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(ident, f"tool arguments must be an object for {name!r}")
        try:
            observation = _call_action(environment, name, arguments)
        except Exception as exc:  # noqa: BLE001 - surface tool failures to the vendor CLI
            return _result(
                ident,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        return _result(
            ident,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(observation, sort_keys=True),
                    }
                ]
            },
        )
    if ident is not None:
        return _error(ident, f"unknown MCP method {method!r}")
    return None


def _call_action(
    environment: dict[str, Any],
    name: str,
    arguments: dict[str, Any],
) -> Any:
    actions = {
        str(item.get("name")): item
        for item in environment.get("actions") or []
        if isinstance(item, dict)
    }
    action = actions.get(name)
    if action is None:
        raise ValueError(f"unknown Environment action {name!r}")
    command = action.get("command") or []
    if not isinstance(command, list) or not command:
        raise ValueError(f"Environment action {name!r} has no command")
    completed = _run_command(
        tuple(str(item) for item in command),
        cwd=_workspace(environment),
        stdin=json.dumps(arguments),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace")
        raise RuntimeError(detail.strip() or f"action {name!r} failed")
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return {"ok": True}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"output": text}


def _tools(environment: dict[str, Any]) -> list[dict[str, Any]]:
    tools = []
    for item in environment.get("actions") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        schema = item.get("parameters") or {"type": "object", "additionalProperties": True}
        tools.append(
            {
                "name": item["name"],
                "description": item.get("description")
                or f"Call Environment action {item['name']}.",
                "inputSchema": schema,
            }
        )
    return tools


def _load_environment() -> dict[str, Any]:
    path = Path(os.environ.get("PLURAL_ENVIRONMENT_FILE", ".plural/environment.json"))
    if not path.is_file():
        return {"actions": [], "workspace": os.environ.get("PLURAL_ENVIRONMENT_WORKSPACE", ".")}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _workspace(environment: dict[str, Any]) -> str:
    return str(
        environment.get("workspace")
        or os.environ.get("PLURAL_ENVIRONMENT_WORKSPACE")
        or "/workspace/environment"
    )


def _run_command(
    command: tuple[str, ...],
    *,
    cwd: str,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        cwd=cwd,
        input=None if stdin is None else stdin.encode(),
        capture_output=True,
        check=False,
    )


def _result(ident: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _error(ident: Any, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": ident,
        "error": {"code": -32601, "message": message},
    }


if __name__ == "__main__":
    main()
