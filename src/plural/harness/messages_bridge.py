"""Translate Anthropic Messages requests to Plural's OpenAI-compatible gateway."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from plural.harness.deadline import call_timeout, episode_deadline


def start(
    host: str = "127.0.0.1", port: int = 0, *, deadline: float | None = None
) -> tuple[ThreadingHTTPServer, str]:
    """Start a local Messages compatibility server.

    Each forwarded call may wait until ``deadline``, the ``time.monotonic()`` at
    which the episode runs out of time; by default, ``PLURAL_STOP_SECONDS`` from now.

    Returns:
        The server and the base URL Claude Code should call.
    """
    server = ThreadingHTTPServer((host, port), _Handler)
    server.deadline = episode_deadline() if deadline is None else deadline  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    assigned = int(server.server_address[1])
    return server, f"http://{host}:{assigned}"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/v1/models") or self.path.startswith("/models"):
            self._json(200, {"data": [{"id": os.environ.get("PLURAL_MODEL", "model")}]})
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "invalid JSON"}})
            return
        if not self.path.startswith("/v1/messages") and not self.path.startswith("/messages"):
            self._json(404, {"error": {"message": "not found"}})
            return
        try:
            response = _forward_messages(
                payload if isinstance(payload, dict) else {},
                call_timeout(getattr(self.server, "deadline", episode_deadline())),
            )
        except Exception as exc:  # noqa: BLE001 - return a usable vendor error
            self._json(502, {"error": {"message": str(exc)}})
            return
        self._json(200, response)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _forward_messages(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = _to_openai(payload)
    upstream = _gateway_request(request, timeout)
    model = str(payload.get("model") or request.get("model") or "model")
    return _from_openai(upstream, model=model)


def _to_openai(payload: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = payload.get("system")
    if isinstance(system, str) and system.strip():
        messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        text = _text(system)
        if text:
            messages.append({"role": "system", "content": text})
    for item in payload.get("messages") or []:
        if isinstance(item, dict):
            messages.extend(_message(item))
    request: dict[str, Any] = {
        "model": payload.get("model") or os.environ.get("PLURAL_MODEL") or "model",
        "messages": messages,
        "max_tokens": payload.get("max_tokens"),
        "temperature": payload.get("temperature"),
        "stop": payload.get("stop_sequences"),
        "stream": False,
    }
    tools = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description") or "",
                "parameters": tool.get("input_schema") or {"type": "object"},
            },
        }
        for tool in payload.get("tools") or []
        if isinstance(tool, dict) and tool.get("name") and "input_schema" in tool
    ]
    if tools:
        request["tools"] = tools
        request["tool_choice"] = _tool_choice(payload.get("tool_choice"))
    return request


def _text(blocks: list[Any]) -> str:
    return "".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _message(item: dict[str, Any]) -> list[dict[str, Any]]:
    """One Messages turn as OpenAI messages: tool results become ``tool`` messages."""
    role = str(item.get("role") or "user")
    content = item.get("content")
    if isinstance(content, str):
        return [{"role": role, "content": content}]
    if not isinstance(content, list):
        return []
    blocks = [block for block in content if isinstance(block, dict)]
    text = _text(blocks)
    if role == "assistant":
        calls = [
            {
                "id": str(block.get("id") or ""),
                "type": "function",
                "function": {
                    "name": str(block.get("name") or ""),
                    "arguments": json.dumps(block.get("input") or {}),
                },
            }
            for block in blocks
            if block.get("type") == "tool_use"
        ]
        message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if calls:
            message["tool_calls"] = calls
        return [message] if text or calls else []
    out = [
        {
            "role": "tool",
            "tool_call_id": str(block.get("tool_use_id") or ""),
            "content": _result_text(block),
        }
        for block in blocks
        if block.get("type") == "tool_result"
    ]
    if text:
        out.append({"role": role, "content": text})
    return out


def _result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    text = content if isinstance(content, str) else _text(content or [])
    return f"Error: {text}" if block.get("is_error") else text


def _tool_choice(choice: Any) -> Any:
    kind = choice.get("type") if isinstance(choice, dict) else None
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    if kind == "tool" and isinstance(choice, dict) and choice.get("name"):
        return {"type": "function", "function": {"name": choice["name"]}}
    return "auto"


def _from_openai(payload: dict[str, Any], *, model: str) -> dict[str, Any]:
    choices = payload.get("choices") or []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message")
    content: list[dict[str, Any]] = []
    calls: list[Any] = []
    if isinstance(message, dict):
        text = message.get("content")
        if isinstance(text, str) and text:
            content.append({"type": "text", "text": text})
        calls = message.get("tool_calls") or []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        content.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or f"toolu_plural_{index}"),
                "name": str(function.get("name") or ""),
                "input": arguments if isinstance(arguments, dict) else {},
            }
        )
    if not content:
        content.append({"type": "text", "text": ""})
    stop_reason = "end_turn"
    if any(block["type"] == "tool_use" for block in content):
        stop_reason = "tool_use"
    elif first.get("finish_reason") == "length":
        stop_reason = "max_tokens"
    raw_usage = payload.get("usage")
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    return {
        "id": payload.get("id") or "msg_plural",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": usage.get("prompt_tokens") or 0,
            "output_tokens": usage.get("completion_tokens") or 0,
        },
    }


def _gateway_request(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    base = (os.environ.get("PLURAL_GATEWAY_URL") or "").rstrip("/")
    if not base:
        raise RuntimeError("the bridge needs PLURAL_GATEWAY_URL from Job(client=...)")
    key = os.environ.get("PLURAL_API_KEY") or ""
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(
            {key: value for key, value in payload.items() if value is not None}
        ).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {key}"} if key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("gateway returned a non-object response")
        return payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"the gateway rejected the request: {detail[:1000]}") from exc


if __name__ == "__main__":
    server, url = start()
    print(url, flush=True)
    threading.Event().wait()
