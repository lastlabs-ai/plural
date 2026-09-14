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


_CHAT_PROFILES = {"chat", "native.chat.v1"}
_ACTION_PROFILES = {"actions", "native.actions.v1"}


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
        json.dumps({"messages": trajectory}, sort_keys=True) + "\n",
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
    declared = {
        str(item["name"]): item
        for item in environment.get("actions", [])
        if isinstance(item, dict) and item.get("name")
    }
    actions = {name: item for name, item in declared.items() if name not in {"reset", "step"}}
    if profile in _ACTION_PROFILES and not actions:
        raise ValueError(f"{profile} requires at least one environment native action")
    denials = _denials(request)
    trajectory: list[dict[str, Any]] = []
    _reset_episode(request, environment, declared, trajectory)
    prompt = _prompt(request, environment, denials)
    system = str(agent.get("instructions") or "").strip()
    if denials:
        system = "\n\n".join(part for part in (system, _denial_text(denials)) if part)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
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
    catalog_model = str(agent.get("model") or "")
    execution_model = _execution_model(request, catalog_model)
    total_cost = 0.0
    final_message: dict[str, Any] | None = None
    for _turn in range(1, max_turns + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{profile} exceeded max_seconds={max_seconds}")
        response = _model_call(
            model=execution_model,
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
        messages.append(message)
        calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        if profile in _CHAT_PROFILES or not calls:
            final_message = message
            break
        for call in calls:
            messages.append(_dispatch_tool(call, actions, environment, denials, deadline))
    if final_message is None:
        raise RuntimeError(f"{profile} reached max_turns={max_turns} without a final response")
    trace_id = str(uuid4())
    return (
        {
            "profile": profile,
            "task_id": _mapping(request.get("task"), "task").get("task_id"),
            "response": final_message.get("content"),
            "model": execution_model,
            "catalog_model": catalog_model,
            "turns": len([item for item in messages if item.get("role") == "assistant"]),
            "cost_usd": total_cost,
            "trace_id": trace_id,
        },
        messages,
        trace_id,
    )


def _execution_model(request: dict[str, Any], catalog_model: str) -> str:
    resolution = request.get("model_resolution")
    resolved = resolution if isinstance(resolution, dict) else {}
    if os.environ.get("PLURAL_GATEWAY_URL"):
        return str(resolved.get("catalog_model_id") or catalog_model)
    return str(resolved.get("upstream_id") or catalog_model)


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


def _denials(request: dict[str, Any]) -> list[dict[str, str]]:
    raw = request.get("capability_denials") or []
    denials: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("capability"):
                denials.append(
                    {
                        "capability": str(item["capability"]),
                        "reason": str(item.get("reason") or "Environment policy"),
                    }
                )
    for name in request.get("denied_capabilities") or []:
        if not any(item["capability"] == str(name) for item in denials):
            denials.append({"capability": str(name), "reason": "Environment policy"})
    return denials


def _denial_text(denials: list[dict[str, str]]) -> str:
    lines = ["These harness tools are unavailable in this Environment:"]
    for item in denials:
        lines.append(f"- `{item['capability']}` is unavailable because {item['reason']}.")
    return "\n".join(lines)


def _tool_observation(call: dict[str, Any], name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": str(call.get("id") or name),
        "content": json.dumps(payload)[:100_000],
    }


def _dispatch_tool(
    call: Any,
    actions: dict[str, dict[str, Any]],
    environment: dict[str, Any],
    denials: list[dict[str, str]],
    deadline: float,
) -> dict[str, Any]:
    if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
        raise ValueError("model emitted an invalid action call")
    function = call["function"]
    name = str(function.get("name") or "")
    denied = {item["capability"]: item["reason"] for item in denials}
    if name.startswith("harness."):
        tool = name.removeprefix("harness.")
        reason = denied.get(tool, "unknown harness tool")
        return _tool_observation(call, name, {"error": "denied", "reason": reason, "tool": name})
    action_name = name.removeprefix("environment.") if name.startswith("environment.") else name
    if action_name not in actions:
        return _tool_observation(
            call,
            name,
            {"error": "denied", "reason": f"unknown tool {name!r}", "tool": name},
        )
    return _run_action(call, action_name, actions, environment, deadline)


def _run_action(
    call: dict[str, Any],
    name: str,
    actions: dict[str, dict[str, Any]],
    environment: dict[str, Any],
    deadline: float,
) -> dict[str, Any]:
    function = call["function"]
    declaration = actions[name]
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


def _prompt(
    request: dict[str, Any],
    environment: dict[str, Any],
    denials: list[dict[str, str]],
) -> str:
    task = _mapping(request.get("task"), "task")
    payload = {
        "instructions": task.get("instructions"),
        "task_info": task.get("info"),
        "metadata": task.get("metadata", {}),
        "observation": environment.get("observation"),
        "tools": {
            "environment": [
                str(item.get("name"))
                for item in environment.get("actions") or []
                if isinstance(item, dict) and item.get("name")
            ],
            "harness_denied": denials,
        },
    }
    return json.dumps(payload, sort_keys=True)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _workspace_path(path: str) -> str:
    root = os.environ.get("PLURAL_SANDBOX_ROOT")
    if root and path.startswith("/"):
        return str(Path(root) / path.removeprefix("/"))
    return path


def _reset_episode(
    request: dict[str, Any],
    environment: dict[str, Any],
    declared: dict[str, dict[str, Any]],
    trajectory: list[dict[str, Any]],
) -> None:
    workspace = Path(_workspace_path(str(environment.get("workspace") or "/workspace/environment")))
    workspace.mkdir(parents=True, exist_ok=True)
    task = _mapping(request.get("task"), "task")
    (workspace / "task.json").write_text(json.dumps(task, sort_keys=True) + "\n", encoding="utf-8")
    command = [str(item) for item in environment.get("reset_command") or ()]
    if not command:
        reset = declared.get("reset") or {}
        command = [str(item) for item in reset.get("command") or ()]
    if not command:
        return
    completed = subprocess.run(
        _local_command(command),
        input=b"{}",
        cwd=str(workspace),
        env={
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
        },
        capture_output=True,
        timeout=float((declared.get("reset") or {}).get("timeout_seconds") or 30),
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode(errors="replace")[:1000]
        raise RuntimeError(f"environment reset failed: {error or completed.returncode}")
    observation_path = workspace / "observation.json"
    if observation_path.exists():
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
        if isinstance(observation, dict):
            environment["observation"] = observation
    else:
        raw = completed.stdout.decode(errors="replace").strip()
        observation = json.loads(raw) if raw else {}
        if isinstance(observation, dict):
            environment["observation"] = observation
    trajectory.append(
        {
            "turn": 0,
            "type": "reset",
            "observation": environment.get("observation"),
        }
    )


def _emit(value: dict[str, Any]) -> None:
    print(
        json.dumps({"protocol": "plural-harness-v1", **value}, sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
