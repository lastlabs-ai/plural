"""Native-path OpenAI-compatible chat and environment-action loops."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4


def _local_command(command: list[Any]) -> list[str]:
    resolved = [str(item) for item in command]
    if resolved and resolved[0] == "python" and shutil.which("python") is None:
        resolved[0] = sys.executable
    return resolved


_CHAT_PROFILES = {"native.chat.v1"}
_ACTION_PROFILES = {"native.actions.v1"}


def main() -> None:
    """Run one model-backed native profile without evaluating its own answer."""
    profile = sys.argv[1] if len(sys.argv) > 1 else "native.chat.v1"
    request = json.loads(sys.stdin.readline())
    try:
        result, trajectory, trace_id = _run(profile, request)
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "message": str(exc)})
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    Path("result.json").write_text(
        json.dumps(result, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path("trajectory.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in trajectory),
        encoding="utf-8",
    )
    _emit(
        {
            "type": "result",
            "status": "succeeded",
            "outputs": ["result.json"],
            "artifacts": ["trajectory.jsonl"],
            "trace_id": trace_id,
        }
    )


def _run(profile: str, request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    if profile not in _CHAT_PROFILES | _ACTION_PROFILES:
        raise ValueError(f"unknown native profile {profile!r}")
    agent = _mapping(request.get("agent"), "agent")
    environment = _mapping(request.get("environment"), "environment")
    limits = _mapping(environment.get("limits"), "environment.limits")
    max_turns = int(limits.get("max_turns", 8))
    max_seconds = float(limits.get("max_seconds", 120))
    max_cost = limits.get("max_cost_usd")
    deadline = time.monotonic() + max_seconds
    actions = {
        str(item["name"]): item
        for item in environment.get("actions", [])
        if isinstance(item, dict) and item.get("name")
    }
    if profile in _ACTION_PROFILES and not actions:
        raise ValueError(f"{profile} requires at least one environment native action")
    prompt = _prompt(request, environment)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": str(environment.get("instructions") or "")},
        {"role": "user", "content": prompt},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": str(action.get("description") or name),
                "parameters": action.get("parameters")
                or {"type": "object", "additionalProperties": True},
            },
        }
        for name, action in actions.items()
    ]
    trajectory: list[dict[str, Any]] = []
    total_cost = 0.0
    final_message: dict[str, Any] | None = None
    for turn in range(1, max_turns + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{profile} exceeded max_seconds={max_seconds}")
        response = _model_call(
            model=str(agent.get("model") or ""),
            routing=_mapping(agent.get("routing") or {}, "agent.routing"),
            messages=messages,
            tools=tools if profile in _ACTION_PROFILES else [],
            timeout=remaining,
        )
        message = _response_message(response)
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        cost = usage.get("cost_usd", usage.get("cost")) if isinstance(usage, dict) else None
        if max_cost is not None and cost is None:
            raise ValueError(
                "max_cost_usd requires the gateway to return usage.cost_usd or usage.cost"
            )
        total_cost += float(cost or 0)
        if max_cost is not None and total_cost > float(max_cost):
            raise RuntimeError(f"{profile} exceeded max_cost_usd={max_cost}")
        trajectory.append(
            {
                "turn": turn,
                "model": response.get("model", agent.get("model")),
                "message": message,
                "usage": usage,
                "cumulative_cost_usd": total_cost,
            }
        )
        messages.append(message)
        calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        if profile in _CHAT_PROFILES or not calls:
            final_message = message
            break
        for call in calls:
            observation = _run_action(call, actions, environment, deadline)
            messages.append(observation)
            trajectory.append({"turn": turn, "observation": observation})
    if final_message is None:
        raise RuntimeError(f"{profile} reached max_turns={max_turns} without a final response")
    trace_id = str(uuid4())
    return (
        {
            "profile": profile,
            "task_id": _mapping(request.get("task"), "task").get("task_id"),
            "response": final_message.get("content"),
            "model": agent.get("model"),
            "turns": len([item for item in trajectory if "message" in item]),
            "cost_usd": total_cost,
            "trace_id": trace_id,
        },
        trajectory,
        trace_id,
    )


def _model_call(
    *,
    model: str,
    routing: dict[str, Any],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    if not model:
        raise ValueError("Agent model is required")
    base = (
        os.environ.get("PLURAL_GATEWAY_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    key = os.environ.get("PLURAL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key and os.environ.get("PLURAL_ALLOW_NO_AUTH") != "1":
        raise ValueError(
            "native runner requires PLURAL_API_KEY or OPENAI_API_KEY "
            "(or PLURAL_ALLOW_NO_AUTH=1 for an explicitly unauthenticated local gateway)"
        )
    body: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        body["tools"] = tools
    for name in ("temperature", "max_tokens"):
        if routing.get(name) is not None:
            body[name] = routing[name]
    if os.environ.get("PLURAL_GATEWAY_URL"):
        body["routing"] = routing
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, timeout)) as response:  # noqa: S310
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode(errors="replace")
        raise RuntimeError(f"model gateway returned HTTP {exc.code}: {detail}") from exc
    if not isinstance(payload, dict):
        raise ValueError("model gateway response must be an object")
    return payload


def _run_action(
    call: Any,
    actions: dict[str, dict[str, Any]],
    environment: dict[str, Any],
    deadline: float,
) -> dict[str, Any]:
    if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
        raise ValueError("model emitted an invalid action call")
    function = call["function"]
    name = str(function.get("name") or "")
    declaration = actions.get(name)
    if declaration is None:
        raise ValueError(f"model requested undeclared environment action {name!r}")
    raw_arguments = function.get("arguments") or "{}"
    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    remaining = deadline - time.monotonic()
    timeout = min(float(declaration.get("timeout_seconds", 30)), remaining)
    if timeout <= 0:
        raise TimeoutError("environment action deadline expired")
    command = declaration.get("command") or []
    if not command:
        raise ValueError(f"environment action {name!r} has no command to execute")
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
    }
    completed = subprocess.run(
        _local_command(command),
        input=json.dumps(arguments).encode(),
        cwd=_workspace_path(str(environment.get("workspace") or "/workspace/environment")),
        env=clean_env,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout.decode(errors="replace")
    if completed.returncode != 0:
        error = completed.stderr.decode(errors="replace")[:1000]
        output = json.dumps({"error": error, "exit_code": completed.returncode})
    return {
        "role": "tool",
        "tool_call_id": str(call.get("id") or name),
        "content": output[:100_000],
    }


def _response_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("model gateway response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("model gateway response has no message")
    return dict(message)


def _prompt(request: dict[str, Any], environment: dict[str, Any]) -> str:
    task = _mapping(request.get("task"), "task")
    return json.dumps(
        {
            "context": environment.get("context"),
            "task": {
                "task_id": task.get("task_id"),
                "input": task.get("input"),
                "metadata": task.get("metadata", {}),
            },
        },
        sort_keys=True,
    )


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _workspace_path(path: str) -> str:
    root = os.environ.get("PLURAL_SANDBOX_ROOT")
    if root and path.startswith("/"):
        return str(Path(root) / path.removeprefix("/"))
    return path


def _emit(value: dict[str, Any]) -> None:
    print(
        json.dumps({"protocol": "plural-harness-v1", **value}, sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
