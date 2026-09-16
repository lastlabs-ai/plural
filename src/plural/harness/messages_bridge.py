"""Translate Anthropic Messages requests to Plural's OpenAI-compatible gateway."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def start(host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Start a local Messages compatibility server.

    Returns:
        The server and the base URL Claude Code should call.
    """
    server = ThreadingHTTPServer((host, port), _Handler)
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
            response = _forward_messages(payload if isinstance(payload, dict) else {})
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


def _forward_messages(payload: dict[str, Any]) -> dict[str, Any]:
    request = _to_openai(payload)
    upstream = _gateway_request(request)
    model = str(payload.get("model") or request.get("model") or "model")
    return _from_openai(upstream, model=model)


def _to_openai(payload: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = payload.get("system")
    if isinstance(system, str) and system.strip():
        messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        text = "".join(
            item.get("text", "")
            for item in system
            if isinstance(item, dict) and item.get("type") == "text"
        )
        if text:
            messages.append({"role": "system", "content": text})
    for item in payload.get("messages") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")
        content = item.get("content")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if isinstance(content, list):
            text = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
            messages.append({"role": role, "content": text})
    return {
        "model": payload.get("model") or os.environ.get("PLURAL_MODEL") or "model",
        "messages": messages,
        "max_tokens": payload.get("max_tokens"),
        "temperature": payload.get("temperature"),
        "stream": False,
    }


def _from_openai(payload: dict[str, Any], *, model: str) -> dict[str, Any]:
    choices = payload.get("choices") or []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    text = ""
    if isinstance(message, dict):
        content = message.get("content")
        text = content if isinstance(content, str) else ""
    raw_usage = payload.get("usage")
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    return {
        "id": payload.get("id") or "msg_plural",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": usage.get("prompt_tokens") or 0,
            "output_tokens": usage.get("completion_tokens") or 0,
        },
    }


def _gateway_request(payload: dict[str, Any]) -> dict[str, Any]:
    base = (os.environ.get("PLURAL_GATEWAY_URL") or os.environ.get("OPENAI_BASE_URL") or "").rstrip(
        "/"
    )
    if not base:
        raise RuntimeError(
            "Claude Code needs PLURAL_GATEWAY_URL or OPENAI_BASE_URL from Job(client=...)"
        )
    key = (
        os.environ.get("PLURAL_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    )
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
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("gateway returned a non-object response")
        return payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"gateway rejected Claude Code request: {detail[:1000]}") from exc


if __name__ == "__main__":
    server, url = start()
    print(url, flush=True)
    threading.Event().wait()
