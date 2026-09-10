"""ACP JSON-RPC client adapter to ``plural-harness-v1``."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TextIO, cast
from uuid import uuid4

ACP_PROTOCOL_VERSION = 1


def main() -> None:
    """Run an ACP agent command and translate lifecycle events."""
    if "--" not in sys.argv:
        raise SystemExit("usage: acp_adapter.py -- <acp-agent> [args...]")
    split = sys.argv.index("--")
    command = sys.argv[split + 1 :]
    if not command:
        raise SystemExit("ACP adapter requires an agent command")
    if command[0] == "python" and shutil.which("python") is None:
        command[0] = sys.executable
    request = json.loads(sys.stdin.readline())
    environment = request.get("environment") or {}
    limits = environment.get("limits") or {}
    timeout = float(limits.get("max_seconds", 120))
    deadline = time.monotonic() + timeout
    workspace = _workspace_path(
        str(environment.get("workspace") or request.get("workspace") or ".")
    )
    child = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0,
        cwd=workspace,
        env=os.environ.copy(),
    )
    if child.stdin is None or child.stdout is None:
        raise RuntimeError("failed to open ACP stdio")
    child_stdin = cast(TextIO, child.stdin)
    child_stdout = cast(TextIO, child.stdout)
    trajectory: list[dict[str, Any]] = []
    text_chunks: list[str] = []
    try:
        initialize = _request(
            child,
            child_stdin,
            child_stdout,
            1,
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
            deadline,
            trajectory,
            text_chunks,
        )
        if int(initialize.get("protocolVersion", ACP_PROTOCOL_VERSION)) != ACP_PROTOCOL_VERSION:
            raise RuntimeError("ACP protocol version mismatch")
        session = _request(
            child,
            child_stdin,
            child_stdout,
            2,
            "session/new",
            {
                "cwd": workspace,
                "mcpServers": [],
            },
            deadline,
            trajectory,
            text_chunks,
        )
        session_id = session.get("sessionId") or session.get("session_id")
        if not session_id:
            raise RuntimeError("ACP session/new response omitted sessionId")
        prompt = json.dumps(
            {
                "task": request.get("task"),
                "agent": request.get("agent"),
                "observation": environment.get("observation"),
            },
            sort_keys=True,
        )
        final = _request(
            child,
            child_stdin,
            child_stdout,
            3,
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": prompt}],
            },
            deadline,
            trajectory,
            text_chunks,
        )
        trace_id = str(uuid4())
        result = {
            "response": "".join(text_chunks),
            "session_id": session_id,
            "stop_reason": final.get("stopReason") or final.get("stop_reason"),
            "trace_id": trace_id,
        }
        Path("result.json").write_text(json.dumps(result, sort_keys=True) + "\n")
        Path("trajectory.jsonl").write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in trajectory)
        )
        print(
            json.dumps(
                {
                    "protocol": "plural-harness-v1",
                    "type": "result",
                    "status": "succeeded",
                    "outputs": ["result.json"],
                    "artifacts": ["trajectory.jsonl"],
                    "trace_id": trace_id,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def _request(
    child: subprocess.Popen[str],
    stdin: TextIO,
    stdout: TextIO,
    request_id: int,
    method: str,
    params: dict[str, Any],
    deadline: float,
    trajectory: list[dict[str, Any]],
    chunks: list[str],
) -> dict[str, Any]:
    stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n"
    )
    stdin.flush()
    selector = selectors.DefaultSelector()
    selector.register(stdout, selectors.EVENT_READ)
    pending_line: str | None = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _cancel(stdin, params.get("sessionId"))
                raise TimeoutError(f"ACP {method} timed out")
            if pending_line is None:
                if not selector.select(remaining):
                    _cancel(stdin, params.get("sessionId"))
                    raise TimeoutError(f"ACP {method} timed out")
                line = stdout.readline()
            else:
                line = pending_line
                pending_line = None
            if not line:
                stderr = child.stderr.read() if child.stderr is not None else ""
                raise RuntimeError(f"ACP agent exited during {method}: {stderr[:1000]}")
            message = json.loads(line)
            trajectory.append(message)
            if message.get("method") == "session/update":
                chunks.extend(_text_values(message.get("params")))
                pending_line = stdout.readline()
                continue
            if "method" in message and "id" in message:
                stdin.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "error": {
                                "code": -32601,
                                "message": "ACP client capability is not available",
                            },
                        }
                    )
                    + "\n"
                )
                stdin.flush()
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"ACP {method} failed: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"ACP {method} returned a non-object result")
            return result
    finally:
        selector.close()


def _cancel(stdin: TextIO, session_id: Any) -> None:
    if session_id:
        stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session/cancel",
                    "params": {"sessionId": session_id},
                }
            )
            + "\n"
        )
        stdin.flush()


def _text_values(value: Any) -> list[str]:
    output: list[str] = []
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            output.append(value["text"])
        for item in value.values():
            output.extend(_text_values(item))
    elif isinstance(value, list):
        for item in value:
            output.extend(_text_values(item))
    return output


def _workspace_path(path: str) -> str:
    root = os.environ.get("PLURAL_SANDBOX_ROOT")
    if root and path.startswith("/"):
        return str(Path(root) / path.removeprefix("/"))
    return path


if __name__ == "__main__":
    main()
