"""Native-path OpenAI-compatible chat and environment-action loops."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# This module is uploaded and run as a standalone script, so it cannot import
# from the plural package. Keep these in sync with plural.environments.runner.PROTOCOL,
# plural.harness.episode, and plural.usage.normalize_usage; test_episode_contract.py
# asserts they match.
STEP_PROTOCOL = "plural-step-v1"
EPISODE_SCHEMA = "plural.episode/v1"
EPISODE_FILE = "episode.jsonl"


def _local_command(command: list[Any]) -> list[str]:
    resolved = [str(item) for item in command]
    if resolved and resolved[0] == "python" and shutil.which("python") is None:
        resolved[0] = sys.executable
    return resolved


_CHAT_PROFILES = {"chat", "native.chat.v1"}
_ACTION_PROFILES = {"actions", "native.actions.v1"}

# Budgets cut an episode short without the Environment declaring completion.
_BUDGET_STOPS = {"max_turns", "max_seconds", "max_cost"}

_FINISH = "finish"
_FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": _FINISH,
        "description": (
            "End the episode. Call this when the task is complete or when you "
            "cannot make further progress."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "A short description of the outcome.",
                }
            },
            "required": [],
        },
    },
}


@dataclass
class _ToolOutcome:
    """One dispatched tool call: what the Agent sees and what the record keeps."""

    message: dict[str, Any]
    transition: dict[str, Any] | None = None
    reward: dict[str, Any] | None = None
    terminated: bool = False
    truncated: bool = False
    finished: bool = False
    summary: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _started() -> tuple[str, float]:
    return _now(), time.monotonic()


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value)


def _cost(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _request_id(response: dict[str, Any]) -> str | None:
    """The gateway's id for this call, which links its billed usage to the Trial."""
    value = response.get("plural_request_id")
    return value if isinstance(value, str) and value else None


def _usage(raw: Any) -> dict[str, Any]:
    """``plural.usage.normalize_usage`` for a script that cannot import the package.

    Unreported values stay ``None``, never zero.
    """
    usage = raw if isinstance(raw, dict) else {}
    output = _count(usage.get("completion_tokens"))
    if output is None:
        output = _count(usage.get("output_tokens"))
    completion_details = usage.get("completion_tokens_details")
    reasoning = (
        _count(completion_details.get("reasoning_tokens"))
        if isinstance(completion_details, dict)
        else None
    )
    if "prompt_tokens" in usage:
        prompt = _count(usage.get("prompt_tokens"))
        details = usage.get("prompt_tokens_details")
        cached = _count(details.get("cached_tokens")) if isinstance(details, dict) else None
    else:
        base = _count(usage.get("input_tokens"))
        read = _count(usage.get("cache_read_input_tokens"))
        written = _count(usage.get("cache_creation_input_tokens"))
        prompt = None if base is None else base + (read or 0) + (written or 0)
        cached = read
    if cached is not None and prompt is not None:
        cached = min(cached, prompt)
    cost = _cost(usage.get("cost"))
    if cost is None:
        cost = _cost(usage.get("cost_usd"))
    return {
        "input_tokens": prompt,
        "output_tokens": output,
        "cached_input_tokens": cached,
        "reasoning_tokens": reasoning,
        "cost_usd": cost,
    }


@dataclass
class _Episode:
    """The recorded episode, kept separately from the Agent's context.

    ``records`` is the ``episode.jsonl`` account of the run, in the same
    ``plural.episode/v1`` shape a class Harness's runner writes.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    rewards: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    _recorded_messages: int = 0

    def document(self) -> dict[str, Any]:
        """Return the messages, transitions, and rewards of the episode."""
        return {
            "messages": self.messages,
            "transitions": self.transitions,
            "rewards": self.rewards,
        }

    def total_reward(self) -> float:
        return sum(float(item.get("value") or 0) for item in self.rewards)

    def record(
        self, kind: str, started: tuple[str, float], *, turn: int | None, **fields: Any
    ) -> None:
        """Append one ``episode.jsonl`` record."""
        self.records.append(
            {
                "schema": EPISODE_SCHEMA,
                "sequence": len(self.records) + 1,
                "kind": kind,
                "turn": turn,
                "started_at": started[0],
                "ended_at": _now(),
                "duration_ms": round((time.monotonic() - started[1]) * 1000, 3),
                **fields,
            }
        )

    def model_call(
        self,
        started: tuple[str, float],
        *,
        turn: int,
        model: str,
        tools: list[dict[str, Any]],
        response: dict[str, Any],
        message: dict[str, Any],
    ) -> None:
        """Record one model call, storing only the messages added since the last."""
        offset = self._recorded_messages
        choices = response.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else {}
        calls = message.get("tool_calls")
        content = message.get("content")
        self.record(
            "model.call",
            started,
            turn=turn,
            model=str(response.get("model") or model),
            messages_offset=offset,
            messages=self.messages[offset:],
            message_count=len(self.messages),
            tools=[str((item.get("function") or {}).get("name") or "") for item in tools],
            text=content if isinstance(content, str) else "",
            reasoning=message.get("reasoning") or message.get("reasoning_content"),
            tool_calls=calls if isinstance(calls, list) else [],
            finish_reason=first.get("finish_reason") if isinstance(first, dict) else None,
            usage=_usage(response.get("usage")),
            request_id=_request_id(response),
            error=None,
        )
        self._recorded_messages = len(self.messages)

    def write(self, path: Path) -> None:
        path.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in self.records),
            encoding="utf-8",
        )


def main() -> None:
    """Run one model-backed native profile without evaluating its own answer."""
    profile = sys.argv[1] if len(sys.argv) > 1 else "native.chat.v1"
    request = json.loads(sys.stdin.readline())
    episode = _Episode()
    try:
        result, episode, trace_id = _run(profile, request, episode)
    except Exception as exc:  # noqa: BLE001
        # Keep the steps and model calls that happened before the failure.
        episode.write(Path(EPISODE_FILE))
        _emit({"type": "error", "message": str(exc)})
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    Path("result.json").write_text(
        json.dumps(result, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    episode.write(Path(EPISODE_FILE))
    _emit(
        {
            "type": "result",
            "status": "succeeded",
            "outputs": ["result.json"],
            "artifacts": [EPISODE_FILE],
            "trace_id": trace_id,
        }
    )


def _run(
    profile: str, request: dict[str, Any], episode: _Episode | None = None
) -> tuple[dict[str, Any], _Episode, str]:
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
    episode = episode if episode is not None else _Episode()
    started = _started()
    reset = _reset_episode(request, environment, declared)
    episode.transitions.append(reset)
    episode.record(
        "environment.reset",
        started,
        turn=None,
        observation=reset.get("observation"),
        info=reset.get("info") or {},
        view=reset.get("view") or None,
        error=None,
    )
    prompt = _prompt(request, environment, denials)
    system = str(agent.get("instructions") or "").strip()
    if denials:
        system = "\n\n".join(part for part in (system, _denial_text(denials)) if part)
    episode.messages.extend(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
    )
    messages = episode.messages
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
    if profile in _ACTION_PROFILES and _FINISH not in actions:
        tools.append(_FINISH_TOOL)
    catalog_model = str(agent.get("model") or "")
    execution_model = _execution_model(request, catalog_model)
    total_cost: float | None = None
    final_message: dict[str, Any] | None = None
    summary: str | None = None
    stop_reason: str | None = None
    terminated = bool(reset.get("terminated"))
    truncated = bool(reset.get("truncated"))
    if terminated or truncated:
        stop_reason = "environment_terminated" if terminated else "environment_truncated"
    for turn in range(1, max_turns + 1):
        if stop_reason is not None:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stop_reason = "max_seconds"
            break
        offered = tools if profile in _ACTION_PROFILES else []
        started = _started()
        response = _model_call(
            model=execution_model,
            routing=_mapping(agent.get("routing") or {}, "agent.routing"),
            messages=messages,
            tools=offered,
            timeout=remaining,
        )
        message = _response_message(response)
        episode.model_call(
            started,
            turn=turn,
            model=execution_model,
            tools=offered,
            response=response,
            message=message,
        )
        cost = episode.records[-1]["usage"]["cost_usd"]
        if max_cost is not None and cost is None:
            raise ValueError(
                "max_cost_usd requires the gateway to return usage.cost_usd or usage.cost"
            )
        if cost is not None:
            total_cost = (total_cost or 0.0) + cost
        messages.append(message)
        if max_cost is not None and (total_cost or 0.0) > float(max_cost):
            stop_reason = "max_cost"
            break
        calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        if profile in _CHAT_PROFILES or not calls:
            final_message = message
            stop_reason = "agent_response"
            break
        for call in calls:
            started = _started()
            outcome = _dispatch_tool(call, actions, environment, denials, deadline, turn)
            _record_outcome(episode, started, turn, call, outcome)
            messages.append(outcome.message)
            if outcome.transition is not None:
                episode.transitions.append(outcome.transition)
            if outcome.reward is not None:
                episode.rewards.append(outcome.reward)
            if outcome.finished:
                summary = outcome.summary
                stop_reason = "agent_finished"
            elif outcome.terminated:
                stop_reason = "environment_terminated"
            elif outcome.truncated:
                stop_reason = "environment_truncated"
            terminated = terminated or outcome.terminated
            truncated = truncated or outcome.truncated
            if stop_reason is not None:
                break
    if stop_reason is None:
        stop_reason = "max_turns"
    response_text = summary if summary is not None else _final_text(final_message, messages)
    trace_id = str(uuid4())
    return (
        {
            "profile": profile,
            "task_id": _mapping(request.get("task"), "task").get("task_id"),
            "response": response_text,
            "model": execution_model,
            "catalog_model": catalog_model,
            "turns": len([item for item in messages if item.get("role") == "assistant"]),
            "cost_usd": total_cost,
            "stop_reason": stop_reason,
            "terminated": terminated,
            "truncated": truncated or stop_reason in _BUDGET_STOPS,
            "total_reward": episode.total_reward(),
            "trace_id": trace_id,
        },
        episode,
        trace_id,
    )


def _record_outcome(
    episode: _Episode,
    started: tuple[str, float],
    turn: int,
    call: Any,
    outcome: _ToolOutcome,
) -> None:
    """Record one dispatched tool call as an Environment step or the Agent finishing."""
    call_id = str(call.get("id") or "") if isinstance(call, dict) else ""
    function = call.get("function") if isinstance(call, dict) else None
    name = str(function.get("name") or "") if isinstance(function, dict) else ""
    visible = outcome.message.get("content")
    transition = outcome.transition or {}
    if transition.get("type") == "finish":
        episode.record(
            "agent.finish",
            started,
            turn=turn,
            tool_call_id=call_id,
            summary=transition.get("summary") or "",
            content=visible,
        )
        return
    try:
        arguments = _arguments(function) if isinstance(function, dict) else {}
    except (TypeError, ValueError):
        arguments = {}
    step = transition if transition.get("type") == "step" else {}
    raw_info = step.get("info")
    info = raw_info if isinstance(raw_info, dict) else {}
    error = info.get("error")
    if not step:
        try:
            parsed = json.loads(visible) if isinstance(visible, str) else None
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("error"):
            error = str(parsed.get("reason") or parsed["error"])
    episode.record(
        "environment.step",
        started,
        turn=turn,
        tool_call_id=call_id,
        action=str(step.get("action") or name),
        arguments=arguments,
        observation=step.get("observation"),
        content=visible,
        reward=step.get("reward"),
        terminated=step.get("terminated"),
        truncated=step.get("truncated"),
        info=info,
        view=step.get("view") or None,
        error=str(error) if error else None,
    )


def _final_text(
    final_message: dict[str, Any] | None,
    messages: list[dict[str, Any]],
) -> str:
    """Return the Agent's closing text, if it produced any."""
    if final_message is not None:
        content = final_message.get("content")
        return content if isinstance(content, str) else ""
    for item in reversed(messages):
        if item.get("role") == "assistant" and isinstance(item.get("content"), str):
            return str(item["content"])
    return ""


def _execution_model(request: dict[str, Any], catalog_model: str) -> str:
    resolution = request.get("model_resolution")
    resolved = resolution if isinstance(resolution, dict) else {}
    return str(resolved.get("catalog_model_id") or catalog_model)


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
    base = (os.environ.get("PLURAL_GATEWAY_URL") or "").rstrip("/")
    if not base:
        raise ValueError("native runner requires PLURAL_GATEWAY_URL for its model calls")
    key = os.environ.get("PLURAL_API_KEY")
    if not key and os.environ.get("PLURAL_ALLOW_NO_AUTH") != "1":
        raise ValueError(
            "native runner requires PLURAL_API_KEY "
            "(or PLURAL_ALLOW_NO_AUTH=1 for an explicitly unauthenticated local gateway)"
        )
    body: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        body["tools"] = tools
    for name in ("temperature", "max_tokens"):
        if routing.get(name) is not None:
            body[name] = routing[name]
    body["routing"] = routing
    headers = {"Content-Type": "application/json"}
    project = os.environ.get("PLURAL_PROJECT_ID")
    if project:
        headers["X-Plural-Project"] = project
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


def _parse_envelope(text: str) -> dict[str, Any] | None:
    """Return the step envelope emitted by the Environment runner, if present."""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or parsed.get("protocol") != STEP_PROTOCOL:
        return None
    observation = parsed.get("observation")
    info = parsed.get("info")
    return {
        "observation": observation if isinstance(observation, dict) else {},
        "reward": float(parsed.get("reward") or 0),
        "terminated": bool(parsed.get("terminated")),
        "truncated": bool(parsed.get("truncated")),
        "info": info if isinstance(info, dict) else {},
        "view": parsed.get("view") if isinstance(parsed.get("view"), dict) else None,
    }


def _dispatch_tool(
    call: Any,
    actions: dict[str, dict[str, Any]],
    environment: dict[str, Any],
    denials: list[dict[str, str]],
    deadline: float,
    turn: int,
) -> _ToolOutcome:
    if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
        raise ValueError("model emitted an invalid action call")
    function = call["function"]
    name = str(function.get("name") or "")
    denied = {item["capability"]: item["reason"] for item in denials}
    if name == _FINISH and _FINISH not in actions:
        return _finish(call, function, turn)
    if name.startswith("harness."):
        tool = name.removeprefix("harness.")
        reason = denied.get(tool, "unknown harness tool")
        return _ToolOutcome(
            message=_tool_observation(
                call, name, {"error": "denied", "reason": reason, "tool": name}
            )
        )
    action_name = name.removeprefix("environment.") if name.startswith("environment.") else name
    if action_name not in actions:
        return _ToolOutcome(
            message=_tool_observation(
                call,
                name,
                {"error": "denied", "reason": f"unknown tool {name!r}", "tool": name},
            )
        )
    return _run_action(call, action_name, actions, environment, deadline, turn)


def _finish(call: dict[str, Any], function: dict[str, Any], turn: int) -> _ToolOutcome:
    """Record the Agent's decision to end the episode."""
    arguments = _arguments(function)
    raw = arguments.get("summary")
    summary = raw if isinstance(raw, str) else ""
    return _ToolOutcome(
        message=_tool_observation(call, _FINISH, {"status": "episode ended"}),
        transition={"type": "finish", "turn": turn, "action": _FINISH, "summary": summary},
        finished=True,
        summary=summary,
    )


def _arguments(function: dict[str, Any]) -> dict[str, Any]:
    raw = function.get("arguments") or "{}"
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    return parsed if isinstance(parsed, dict) else {}


def _run_action(
    call: dict[str, Any],
    name: str,
    actions: dict[str, dict[str, Any]],
    environment: dict[str, Any],
    deadline: float,
    turn: int,
) -> _ToolOutcome:
    declaration = actions[name]
    arguments = _arguments(call["function"])
    remaining = deadline - time.monotonic()
    timeout = min(float(declaration.get("timeout_seconds", 30)), remaining)
    if timeout <= 0:
        raise TimeoutError("environment action deadline expired")
    command = declaration.get("command") or []
    if not command:
        raise ValueError(f"environment action {name!r} has no command to execute")
    clean_env = _action_environment(environment)
    completed = subprocess.run(
        _local_command(command),
        input=json.dumps(arguments).encode(),
        cwd=_workspace_path(str(environment.get("workspace") or "/workspace/environment")),
        env=clean_env,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode(errors="replace")[:1000]
        payload = {"error": error, "exit_code": completed.returncode}
        return _ToolOutcome(message=_tool_observation(call, name, payload))
    output = completed.stdout.decode(errors="replace")
    envelope = _parse_envelope(output)
    if envelope is None:
        # A custom action command that does not speak the step protocol.
        return _ToolOutcome(
            message={
                "role": "tool",
                "tool_call_id": str(call.get("id") or name),
                "content": output[:100_000],
            }
        )
    environment["observation"] = envelope["observation"]
    # The Agent sees the observation and its own errors. Reward stays out of
    # context so it cannot be used to infer the answer.
    visible = dict(envelope["observation"])
    error = envelope["info"].get("error")
    if error:
        visible["error"] = error
    signals = envelope["info"].get("rewards")
    reward = None
    if envelope["reward"] or signals:
        reward = {
            "type": "reward",
            "turn": turn,
            "action": name,
            "value": envelope["reward"],
            "signals": signals if isinstance(signals, list) else [],
        }
    return _ToolOutcome(
        message=_tool_observation(call, name, visible),
        transition={
            "type": "step",
            "turn": turn,
            "action": name,
            "arguments": arguments,
            "observation": envelope["observation"],
            "reward": envelope["reward"],
            "terminated": envelope["terminated"],
            "truncated": envelope["truncated"],
            "info": envelope["info"],
            "view": envelope["view"],
        },
        reward=reward,
        terminated=envelope["terminated"],
        truncated=envelope["truncated"],
    )


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
) -> dict[str, Any]:
    """Start the episode and return its opening trajectory record."""
    workspace = Path(_workspace_path(str(environment.get("workspace") or "/workspace/environment")))
    workspace.mkdir(parents=True, exist_ok=True)
    task = _mapping(request.get("task"), "task")
    (workspace / "task.json").write_text(json.dumps(task, sort_keys=True) + "\n", encoding="utf-8")
    record: dict[str, Any] = {"type": "reset", "turn": 0}
    command = [str(item) for item in environment.get("reset_command") or ()]
    if not command:
        reset = declared.get("reset") or {}
        command = [str(item) for item in reset.get("command") or ()]
    if not command:
        record["observation"] = environment.get("observation")
        return record
    completed = subprocess.run(
        _local_command(command),
        input=b"{}",
        cwd=str(workspace),
        env=_action_environment(environment),
        capture_output=True,
        timeout=float((declared.get("reset") or {}).get("timeout_seconds") or 30),
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode(errors="replace")[:1000]
        raise RuntimeError(f"environment reset failed: {error or completed.returncode}")
    envelope = _parse_envelope(completed.stdout.decode(errors="replace"))
    if envelope is not None:
        environment["observation"] = envelope["observation"]
        record.update(
            {
                "observation": envelope["observation"],
                "terminated": envelope["terminated"],
                "truncated": envelope["truncated"],
                "info": envelope["info"],
            }
        )
        if envelope["view"]:
            record["view"] = envelope["view"]
        return record
    observation_path = workspace / "observation.json"
    if observation_path.exists():
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
    else:
        raw = completed.stdout.decode(errors="replace").strip()
        observation = json.loads(raw) if raw else {}
    if isinstance(observation, dict):
        environment["observation"] = observation
    record["observation"] = environment.get("observation")
    return record


def _emit(value: dict[str, Any]) -> None:
    print(
        json.dumps({"protocol": "plural-harness-v1", **value}, sort_keys=True),
        flush=True,
    )


def _action_environment(environment: dict[str, Any]) -> dict[str, str]:
    names = {
        "PATH",
        "PYTHONPATH",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SYSTEMROOT",
        *environment.get("variable_names", []),
    }
    values = {key: value for key, value in os.environ.items() if key in names}
    values["PLURAL_RESOURCES_DIR"] = _workspace_path("/workspace/resources")
    return values


if __name__ == "__main__":
    main()
