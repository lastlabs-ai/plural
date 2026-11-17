"""Serve OpenAI Responses requests, as Codex sends them, from Plural's chat completions gateway.

Codex speaks only the Responses API; the gateway serves chat completions. The bridge
translates one turn at a time and streams the answer back as Responses events. It also
passes chat completions through as they are, for a CLI such as Hermes that speaks them
but can't be given the gateway's key, which only the bridge holds.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from plural.harness.deadline import call_timeout, episode_deadline
from plural.harness.messages_bridge import _gateway_request


def start(
    host: str = "127.0.0.1", port: int = 0, *, deadline: float | None = None
) -> tuple[ThreadingHTTPServer, str]:
    """Start a local Responses compatibility server.

    Each forwarded call may wait until ``deadline``, the ``time.monotonic()`` at
    which the episode runs out of time; by default, ``PLURAL_STOP_SECONDS`` from now.

    Returns:
        The server and the base URL, ending in ``/v1``, Codex should call.
    """
    server = ThreadingHTTPServer((host, port), _Handler)
    server.deadline = episode_deadline() if deadline is None else deadline  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{int(server.server_address[1])}/v1"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"data": [{"id": os.environ.get("PLURAL_MODEL", "model")}]})
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads((self.rfile.read(length) if length else b"{}").decode() or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "invalid JSON"}})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": {"message": "the request is not a JSON object"}})
            return
        timeout = call_timeout(getattr(self.server, "deadline", episode_deadline()))
        if self.path.rstrip("/").endswith("/chat/completions"):
            self._chat(payload, timeout)
            return
        if not self.path.rstrip("/").endswith("/responses"):
            self._json(404, {"error": {"message": "not found"}})
            return
        try:
            request, tools = to_chat(payload)
            response = from_chat(_gateway_request(request, timeout), tools)
        except Exception as exc:  # noqa: BLE001 - return a usable vendor error
            self._json(502, {"error": {"message": str(exc)}})
            return
        if payload.get("stream") is False:
            self._json(200, response)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for event in stream_events(response):
            data = json.dumps(event)
            self.wfile.write(f"event: {event['type']}\ndata: {data}\n\n".encode())
        self.wfile.flush()

    def _chat(self, payload: dict[str, Any], timeout: float) -> None:
        stream = bool(payload.pop("stream", False))
        payload.pop("stream_options", None)
        messages = payload.get("messages")
        if isinstance(messages, list):
            # OpenAI's newer name for a system message, which the gateway doesn't take.
            payload["messages"] = [
                {**item, "role": "system"}
                if isinstance(item, dict) and item.get("role") == "developer"
                else item
                for item in messages
            ]
        try:
            response = _gateway_request(payload, timeout)
        except Exception as exc:  # noqa: BLE001 - return a usable vendor error
            self._json(502, {"error": {"message": str(exc)}})
            return
        if not stream:
            self._json(200, response)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for chunk in chat_chunks(response):
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def chat_chunks(response: dict[str, Any]) -> list[dict[str, Any]]:
    """One chat completion as the chunks a streaming client reads.

    Returns:
        A chunk with each choice's message, one with its finish reason, and one
        with the usage, if the gateway reported it.
    """
    base = {
        "id": response.get("id") or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": response.get("created") or 0,
        "model": response.get("model") or "",
    }
    chunks: list[dict[str, Any]] = []
    for choice in response.get("choices") or ():
        index = choice.get("index", 0)
        message = choice.get("message") or {}
        delta: dict[str, Any] = {"role": "assistant"}
        if message.get("content") is not None:
            delta["content"] = message["content"]
        calls = [
            {**call, "index": position}
            for position, call in enumerate(message.get("tool_calls") or ())
        ]
        if calls:
            delta["tool_calls"] = calls
        chunks.append(
            {**base, "choices": [{"index": index, "delta": delta, "finish_reason": None}]}
        )
        finish = choice.get("finish_reason") or ("tool_calls" if calls else "stop")
        chunks.append({**base, "choices": [{"index": index, "delta": {}, "finish_reason": finish}]})
    if response.get("usage"):
        chunks.append({**base, "choices": [], "usage": response["usage"]})
    return chunks


@dataclass
class Tools:
    """What a turn's tools need, to turn chat tool calls back into Responses items."""

    custom: set[str] = field(default_factory=set)
    """Chat names of the freeform tools, called with one string."""
    namespaces: set[str] = field(default_factory=set)
    """Namespaces other than ``functions``, folded into chat names."""


_LOCAL_SHELL = {
    "type": "object",
    "properties": {
        "command": {"type": "array", "items": {"type": "string"}},
        "workdir": {"type": "string"},
        "timeout_ms": {"type": "integer"},
    },
    "required": ["command"],
}


def to_chat(payload: dict[str, Any]) -> tuple[dict[str, Any], Tools]:
    """A Responses request as a chat completions request.

    A freeform (``custom``) tool becomes a function taking one string, ``input``.

    Returns:
        The request, and what its tools need to be read back.
    """
    messages: list[dict[str, Any]] = []
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages.append({"role": "system", "content": instructions})
    items = payload.get("input")
    if isinstance(items, str):
        items = [{"type": "message", "role": "user", "content": items}]
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            _add_item(messages, item)
    declared = list(payload.get("tools") or [])
    for item in items if isinstance(items, list) else []:
        # Codex sends its tools as an input item, grouped in namespaces.
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            declared.extend(item.get("tools") or [])
    tools: list[dict[str, Any]] = []
    known = Tools()
    for tool, namespace in _flatten(declared):
        if namespace != _DEFAULT_NAMESPACE:
            known.namespaces.add(namespace)
        kind, name = tool.get("type"), _chat_name(namespace, str(tool.get("name") or ""))
        if kind == "function" and tool.get("name"):
            parameters = tool.get("parameters") or {"type": "object", "properties": {}}
            tools.append(_function(name, tool.get("description"), parameters))
        elif kind == "custom" and tool.get("name"):
            known.custom.add(name)
            parameters = {
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
            }
            tools.append(_function(name, tool.get("description"), parameters))
        elif kind == "local_shell":
            tools.append(_function("local_shell", "Run a command.", _LOCAL_SHELL))
    request: dict[str, Any] = {
        "model": payload.get("model") or os.environ.get("PLURAL_MODEL") or "model",
        "messages": messages,
        "max_tokens": payload.get("max_output_tokens"),
        "temperature": payload.get("temperature"),
        "stream": False,
    }
    if tools:
        request["tools"] = tools
        choice = payload.get("tool_choice")
        request["tool_choice"] = choice if choice in {"auto", "none", "required"} else "auto"
        if isinstance(payload.get("parallel_tool_calls"), bool):
            request["parallel_tool_calls"] = payload["parallel_tool_calls"]
    return request, known


_DEFAULT_NAMESPACE = "functions"
_SEPARATOR = "__"


def _flatten(
    tools: list[Any], namespace: str = _DEFAULT_NAMESPACE
) -> list[tuple[dict[str, Any], str]]:
    flat: list[tuple[dict[str, Any], str]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "namespace":
            flat.extend(_flatten(tool.get("tools") or [], str(tool.get("name") or namespace)))
        else:
            flat.append((tool, namespace))
    return flat


def _chat_name(namespace: str | None, name: str) -> str:
    if not namespace or namespace == _DEFAULT_NAMESPACE or name.startswith(namespace):
        return name
    return f"{namespace}{_SEPARATOR}{name}"


def _split_name(name: str, namespaces: set[str]) -> tuple[str | None, str]:
    for namespace in sorted(namespaces, key=len, reverse=True):
        prefix = f"{namespace}{_SEPARATOR}"
        if name.startswith(prefix):
            return namespace, name.removeprefix(prefix)
    return None, name


def _function(name: str, description: Any, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": str(description or ""), "parameters": parameters},
    }


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"}
    )


def _add_item(messages: list[dict[str, Any]], item: dict[str, Any]) -> None:
    kind = item.get("type") or ("message" if "role" in item else None)
    if kind == "message":
        role = str(item.get("role") or "user")
        text = _text(item.get("content"))
        if text:
            messages.append({"role": "system" if role == "developer" else role, "content": text})
        return
    call: tuple[str, str] | None = None
    name = _chat_name(item.get("namespace"), str(item.get("name") or ""))
    if kind == "function_call":
        call = (name, str(item.get("arguments") or "{}"))
    elif kind == "custom_tool_call":
        call = (name, json.dumps({"input": item.get("input") or ""}))
    elif kind == "local_shell_call":
        raw = item.get("action")
        action: dict[str, Any] = raw if isinstance(raw, dict) else {}
        arguments = {"command": action.get("command") or []}
        if action.get("working_directory"):
            arguments["workdir"] = action["working_directory"]
        call = ("local_shell", json.dumps(arguments))
    if call is not None:
        entry = {
            "id": str(item.get("call_id") or item.get("id") or ""),
            "type": "function",
            "function": {"name": call[0], "arguments": call[1]},
        }
        last = messages[-1] if messages else None
        if last is not None and last["role"] == "assistant" and "tool_calls" in last:
            last["tool_calls"].append(entry)
        else:
            messages.append({"role": "assistant", "content": None, "tool_calls": [entry]})
        return
    if kind in {"function_call_output", "custom_tool_call_output"}:
        output = item.get("output")
        if isinstance(output, dict):
            output = output.get("content") or output.get("output") or json.dumps(output)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": str(item.get("call_id") or ""),
                "content": output if isinstance(output, str) else _text(output),
            }
        )


def from_chat(payload: dict[str, Any], tools: Tools) -> dict[str, Any]:
    """A chat completion as a finished Responses object.

    Returns:
        The response, its ``output`` the message and each tool call as its own item.
    """
    choices = payload.get("choices") or []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    raw_message = first.get("message")
    message: dict[str, Any] = raw_message if isinstance(raw_message, dict) else {}
    output: list[dict[str, Any]] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        output.append(
            {
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex}",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    for index, call in enumerate(message.get("tool_calls") or []):
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        name = str(function.get("name") or "")
        arguments = str(function.get("arguments") or "{}")
        call_id = str(call.get("id") or f"call_plural_{index}")
        output.append(_call_item(name, arguments, call_id, tools))
    raw = payload.get("usage")
    usage = raw if isinstance(raw, dict) else {}
    prompt, completion = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "status": "completed",
        "model": payload.get("model"),
        "output": output,
        "usage": {
            "input_tokens": prompt,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": completion,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": prompt + completion,
        },
    }


def _call_item(name: str, arguments: str, call_id: str, tools: Tools) -> dict[str, Any]:
    item_id = f"fc_{uuid.uuid4().hex}"
    namespace, bare = _split_name(name, tools.namespaces)
    named = {"name": bare, **({"namespace": namespace} if namespace else {})}
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        parsed = None
    if name in tools.custom:
        value = parsed.get("input") if isinstance(parsed, dict) else arguments
        return {
            "type": "custom_tool_call",
            "id": item_id,
            "call_id": call_id,
            **named,
            "input": str(value or ""),
            "status": "completed",
        }
    if name == "local_shell" and isinstance(parsed, dict):
        return {
            "type": "local_shell_call",
            "id": item_id,
            "call_id": call_id,
            "status": "completed",
            "action": {
                "type": "exec",
                "command": parsed.get("command") or [],
                "working_directory": parsed.get("workdir"),
                "timeout_ms": parsed.get("timeout_ms"),
            },
        }
    return {
        "type": "function_call",
        "id": item_id,
        "call_id": call_id,
        **named,
        "arguments": arguments,
        "status": "completed",
    }


def stream_events(response: dict[str, Any]) -> list[dict[str, Any]]:
    """The Responses streaming events for a response that is already complete.

    Returns:
        ``response.created``, each item added, its text, and done, then ``response.completed``.
    """
    events: list[dict[str, Any]] = [
        {"type": "response.created", "response": {**response, "status": "in_progress"}}
    ]
    for index, item in enumerate(response["output"]):
        events.append({"type": "response.output_item.added", "output_index": index, "item": item})
        if item["type"] == "message":
            text = item["content"][0]["text"]
            events.append(
                {
                    "type": "response.output_text.delta",
                    "item_id": item["id"],
                    "output_index": index,
                    "content_index": 0,
                    "delta": text,
                }
            )
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    events.append({"type": "response.completed", "response": response})
    for number, event in enumerate(events):
        event["sequence_number"] = number
    return events


if __name__ == "__main__":
    server, url = start()
    print(url, flush=True)
    threading.Event().wait()
