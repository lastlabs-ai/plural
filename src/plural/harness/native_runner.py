"""Native-path OpenAI-compatible chat and environment-action loops."""

from __future__ import annotations

import contextlib
import ipaddress
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
from urllib.parse import urlsplit
from uuid import uuid4

# This module is uploaded and run as a standalone script, so it cannot import
# from the plural package. Keep these in sync with plural.apps.host.STEP_PROTOCOL,
# plural.harness.episode, plural.usage.normalize_usage, and
# plural.usage.price_own_hardware; test_episode_contract.py
# asserts they match.
STEP_PROTOCOL = "plural-step-v1"
EPISODE_SCHEMA = "plural.episode/v1"
EPISODE_FILE = "episode.jsonl"
MAX_UNKNOWN_NAME = 128
"""Longest name of a tool that doesn't exist that is still sent on to be recorded."""


def _local_command(command: list[Any]) -> list[str]:
    resolved = [str(item) for item in command]
    if resolved and resolved[0] == "python" and shutil.which("python") is None:
        resolved[0] = sys.executable
    return resolved


_CHAT_PROFILES = {"chat", "native.chat.v1"}
_ACTION_PROFILES = {"actions", "native.actions.v1"}
# An Environment with no Apps: the loop brings its own tools for the workspace.
_WORKSPACE_PROFILES = {"workspace", "native.workspace.v1"}

# Budgets cut an episode short without the Environment declaring completion.
_BUDGET_STOPS = {"max_turns", "max_seconds", "max_cost"}

# Keep in sync with plural.apps.daemon.SEAT_TOKEN.
SEAT_TOKEN = "PLURAL_SEAT_TOKEN"

# How long a model call waits for credits once the account runs out. The time
# spent waiting does not count against the episode's max_seconds.
CREDIT_PAUSE_VARIABLE = "PLURAL_CREDIT_PAUSE_SECONDS"
# Seconds after which the runner ends the episode itself, set by the engine so the
# Runtime's own timeout never kills it mid-episode. Keep in sync with
# plural.harness.deadline.STOP_VARIABLE; this runner imports nothing from plural.
STOP_VARIABLE = "PLURAL_STOP_SECONDS"
DEFAULT_CREDIT_PAUSE_SECONDS = 3600.0
_CREDIT_POLL_SECONDS = 30.0
_TURN_POLL_SECONDS = (0.1, 0.25, 0.5, 1.0)
# Waits before each retry of a rate-limited or unavailable gateway. Like credit
# waits, they do not count against max_seconds.
_GATEWAY_RETRY_SECONDS = (2.0, 5.0, 15.0)
_MAX_RETRY_AFTER_SECONDS = 60.0


class GatewayError(RuntimeError):
    """A model call the gateway, not the Agent, failed.

    ``code`` is an ``ErrorCode`` value the engine records, so the attempt is
    excluded from scores instead of scored as the Agent's failure.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    records: list[dict[str, Any]] = field(default_factory=list)
    _recorded_messages: int = 0
    stream: Path | None = None
    """Where each record is appended as it happens, so a run checkpoint can read
    the Agent's context while the episode is still going."""

    def document(self) -> dict[str, Any]:
        """Return the messages and transitions of the episode."""
        return {
            "messages": self.messages,
            "transitions": self.transitions,
        }

    def record(
        self, kind: str, started: tuple[str, float], *, turn: int | None, **fields: Any
    ) -> None:
        """Append one ``episode.jsonl`` record."""
        record = {
            "schema": EPISODE_SCHEMA,
            "sequence": len(self.records) + 1,
            "event_id": f"e{len(self.records) + 1}",
            "kind": kind,
            "turn": turn,
            "started_at": started[0],
            "ended_at": _now(),
            "duration_ms": round((time.monotonic() - started[1]) * 1000, 3),
            **fields,
        }
        self.records.append(record)
        if self.stream is not None:
            with self.stream.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    def compacted(
        self,
        started: tuple[str, float],
        *,
        turn: int,
        policy: dict[str, Any],
        before: int,
        dropped: int,
        summary: str | None,
        usage: dict[str, Any] | None,
        model: str | None,
    ) -> None:
        """Record one compaction of the Agent's context, with the context it left.

        The next model call is recorded from offset 0, so anything that rebuilds
        the context from the records gets the compacted one.
        """
        self.record(
            "context.compaction",
            started,
            turn=turn,
            strategy=str(policy.get("strategy") or ""),
            tokens_before=before,
            tokens_after=_context_tokens(self.messages),
            dropped_messages=dropped,
            summary=summary,
            messages=list(self.messages),
            message_count=len(self.messages),
            usage=usage or {},
            model=model,
        )
        self._recorded_messages = 0

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
    episode = _Episode(stream=Path(EPISODE_FILE))
    with contextlib.suppress(OSError):
        Path(EPISODE_FILE).unlink()
    try:
        result, episode, trace_id = _run(profile, request, episode)
    except Exception as exc:  # noqa: BLE001
        # Keep the steps and model calls that happened before the failure.
        episode.write(Path(EPISODE_FILE))
        event = {"type": "error", "message": str(exc)}
        if isinstance(exc, GatewayError):
            event["kind"] = exc.code
        _emit(event)
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
    if profile not in _CHAT_PROFILES | _ACTION_PROFILES | _WORKSPACE_PROFILES:
        raise ValueError(f"unknown native profile {profile!r}")
    agent = _mapping(request.get("agent"), "agent")
    environment = _mapping(request.get("environment"), "environment")
    limits = _mapping(environment.get("limits"), "environment.limits")
    raw_turns = limits.get("max_turns")
    # A missing or null turn cap means no limit. Time still stops the run.
    max_turns = None if raw_turns is None else int(raw_turns)
    max_seconds = float(limits.get("max_seconds", 600))
    max_cost = limits.get("max_cost_usd")
    stop = float(os.environ.get(STOP_VARIABLE) or max_seconds)
    deadline = time.monotonic() + min(max_seconds, stop)
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
    prompt = _prompt(request, environment)
    system = str(agent.get("instructions") or "").strip()
    if denials:
        system = "\n\n".join(part for part in (system, _denial_text(denials)) if part)
    resume = request.get("resume") if isinstance(request.get("resume"), dict) else None
    if resume is not None and resume.get("history") == "native":
        # The history is this Agent's own conversation; its own instructions lead it.
        history = [
            dict(item)
            for item in resume.get("messages") or ()
            if isinstance(item, dict) and item.get("role") != "system"
        ]
        episode.messages.extend([{"role": "system", "content": system}, *history])
        after = _after_history(resume, reset)
        if after:
            episode.messages.append({"role": "user", "content": after})
    else:
        if resume is not None:
            prompt = _resumed_prompt(prompt, resume, reset)
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
    finish_allowed = bool(environment.get("allow_finish", True))
    autonomous = bool(environment.get("autonomous")) and "wait" in actions
    if profile in _ACTION_PROFILES and _FINISH not in actions and finish_allowed:
        tools.append(_FINISH_TOOL)
    policy = agent.get("context") if isinstance(agent.get("context"), dict) else {}
    workspace = _WorkspaceTools(environment, denials) if profile in _WORKSPACE_PROFILES else None
    if workspace is not None:
        tools = workspace.declarations()
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
    seen_view: Any = None
    # Limits count the whole episode, so a fork continues the original's turn count.
    turn = int(resume.get("turn") or 0) if resume is not None else 0
    while stop_reason is None:
        turn += 1
        if max_turns is not None and turn > max_turns:
            stop_reason = "max_turns"
            break
        if environment.get("turn_command"):
            seat = _await_turn(environment, deadline)
            if seat is None:
                stop_reason = "max_seconds"
                break
            if seat.get("terminated") or seat.get("truncated"):
                terminated = terminated or bool(seat.get("terminated"))
                truncated = truncated or bool(seat.get("truncated"))
                stop_reason = (
                    "environment_terminated" if seat.get("terminated") else "environment_truncated"
                )
                break
            view = seat.get("observation")
            if view is not None and view != seen_view:
                seen_view = view
                messages.append(
                    {"role": "user", "content": f"Your turn.\n\n{_observation_text(view)}"}
                )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stop_reason = "max_seconds"
            break
        offered = tools if profile not in _CHAT_PROFILES else []
        if policy:
            compaction_cost, paused = _compact(
                episode,
                policy,
                model=execution_model,
                routing=_mapping(agent.get("routing") or {}, "agent.routing"),
                timeout=remaining,
                turn=turn,
            )
            deadline += paused
            if compaction_cost is not None:
                total_cost = (total_cost or 0.0) + compaction_cost
        started = _started()
        try:
            response, paused = _model_call(
                model=execution_model,
                routing=_mapping(agent.get("routing") or {}, "agent.routing"),
                messages=messages,
                tools=offered,
                timeout=remaining,
            )
        except (TimeoutError, urllib.error.URLError) as exc:
            timed_out = isinstance(exc, TimeoutError) or isinstance(exc.reason, TimeoutError)
            if not timed_out or time.monotonic() < deadline:
                raise
            stop_reason = "max_seconds"
            break
        deadline += paused
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
            raise GatewayError(
                "configuration",
                "max_cost_usd requires the gateway to return usage.cost_usd or usage.cost",
            )
        if cost is not None:
            total_cost = (total_cost or 0.0) + cost
        messages.append(message)
        if max_cost is not None and (total_cost or 0.0) > float(max_cost):
            stop_reason = "max_cost"
            break
        calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        if autonomous and not calls and profile not in _CHAT_PROFILES:
            # In an autonomous Environment the Agent can't end the episode by replying:
            # a reply without a tool call lets time pass until something happens.
            call = {"id": "", "function": {"name": "wait", "arguments": "{}"}}
            started = _started()
            outcome = _run_action(call, "wait", actions, environment, deadline, turn)
            _record_outcome(episode, started, turn, call, outcome, implicit=True)
            if outcome.transition is not None:
                episode.transitions.append(outcome.transition)
            messages.append(
                {"role": "user", "content": f"(You waited.)\n{outcome.message.get('content')}"}
            )
            terminated = terminated or outcome.terminated
            truncated = truncated or outcome.truncated
            if outcome.terminated:
                stop_reason = "environment_terminated"
            elif outcome.truncated:
                stop_reason = "environment_truncated"
            continue
        if profile in _CHAT_PROFILES or not calls:
            final_message = message
            stop_reason = "agent_response"
            break
        for call in calls:
            started = _started()
            if workspace is not None:
                outcome = workspace.dispatch(call, deadline, turn)
                if outcome.transition is not None:
                    _record_outcome(episode, started, turn, call, outcome)
                messages.append(outcome.message)
                continue
            outcome = _dispatch_tool(
                call, actions, environment, denials, deadline, turn, finish=finish_allowed
            )
            _record_outcome(episode, started, turn, call, outcome)
            messages.append(outcome.message)
            if outcome.transition is not None:
                episode.transitions.append(outcome.transition)
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
    *,
    implicit: bool = False,
) -> None:
    """Record one dispatched tool call as an Environment step or the Agent finishing.

    An ``implicit`` step is one the loop took for the Agent, such as waiting after
    a reply with no tool call; the Agent sees its result as a user message.
    """
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
        rewards=step.get("rewards") or [],
        terminated=step.get("terminated"),
        truncated=step.get("truncated"),
        info=info,
        view=step.get("view") or None,
        error=str(error) if error else None,
        **({"implicit": True} if implicit else {}),
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
) -> tuple[dict[str, Any], float]:
    """Call the model, waiting while the account is out of credits.

    Returns:
        The response, and the seconds spent waiting for credits.
    """
    if not model:
        raise ValueError("Agent model is required")
    endpoint = (os.environ.get("PLURAL_AGENT_ENDPOINT") or "").rstrip("/")
    if endpoint:
        base = endpoint
        key = os.environ.get("PLURAL_AGENT_ENDPOINT_KEY")
    else:
        base = (os.environ.get("PLURAL_GATEWAY_URL") or "").rstrip("/")
        if not base:
            raise GatewayError(
                "configuration", "native runner requires PLURAL_GATEWAY_URL for its model calls"
            )
        key = os.environ.get("PLURAL_API_KEY")
        if not key and os.environ.get("PLURAL_ALLOW_NO_AUTH") != "1":
            raise GatewayError(
                "configuration",
                "native runner requires PLURAL_API_KEY "
                "(or PLURAL_ALLOW_NO_AUTH=1 for an explicitly unauthenticated local gateway)",
            )
    body: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        body["tools"] = tools
    for name in ("temperature", "max_tokens"):
        if routing.get(name) is not None:
            body[name] = routing[name]
    headers = {"Content-Type": "application/json"}
    if not endpoint:
        body["routing"] = routing
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
    budget = float(os.environ.get(CREDIT_PAUSE_VARIABLE) or DEFAULT_CREDIT_PAUSE_SECONDS)
    paused = 0.0
    retries = iter(_GATEWAY_RETRY_SECONDS)
    while True:
        try:
            with urllib.request.urlopen(request, timeout=max(0.1, timeout)) as response:  # noqa: S310
                payload = json.loads(response.read())
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode(errors="replace")
            failure = f"model gateway returned HTTP {exc.code}: {detail}"
            if exc.code in {401, 403} or (exc.code == 429 and "auth_locked_out" in detail):
                raise GatewayError("authentication", failure) from exc
            if exc.code == 429 or exc.code >= 500:
                code = "rate_limited" if exc.code == 429 else "provider_unavailable"
                wait = next(retries, None)
                if wait is None:
                    raise GatewayError(code, failure) from exc
                wait = max(wait, _retry_after(exc.headers.get("Retry-After")))
                print(f"{failure.splitlines()[0][:200]}; retrying in {wait:g}s.", file=sys.stderr)
                time.sleep(wait)
                paused += wait
                continue
            if exc.code != 402 or not _out_of_credits(detail):
                raise RuntimeError(failure) from exc
            if paused >= budget:
                raise RuntimeError(
                    f"Out of credits: this Trial waited {round(paused / 60)} minutes for "
                    "credits. Add credits, then run it again with `plural trial rerun`."
                ) from exc
            if not paused:
                print("Out of credits: waiting for credits to resume.", file=sys.stderr)
            wait = min(_CREDIT_POLL_SECONDS, budget - paused)
            time.sleep(wait)
            paused += wait
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise
            wait = next(retries, None)
            if wait is None:
                raise GatewayError(
                    "provider_unavailable", f"model gateway unreachable: {exc.reason}"
                ) from exc
            time.sleep(wait)
            paused += wait
    if not isinstance(payload, dict):
        raise GatewayError("provider_unavailable", "model gateway response must be an object")
    return _price_own_hardware(payload, endpoint), paused


def _on_own_hardware(endpoint: str) -> bool:
    host = (urlsplit(endpoint).hostname or "").lower()
    if host in {"localhost", "host.docker.internal"} or host.endswith((".localhost", ".local")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_loopback or address.is_private or address.is_link_local or address.is_unspecified
    )


def _price_own_hardware(response: dict[str, Any], endpoint: str) -> dict[str, Any]:
    if not endpoint or not _on_own_hardware(endpoint):
        return response
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = response["usage"] = {}
    if response.get("cost") is None and usage.get("cost") is None and usage.get("cost_usd") is None:
        usage["cost"] = 0.0
    return response


def _retry_after(value: str | None) -> float:
    try:
        seconds = float(value or 0)
    except ValueError:
        return 0.0
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER_SECONDS)


def _out_of_credits(detail: str) -> bool:
    try:
        error = json.loads(detail).get("error")
    except (ValueError, AttributeError):
        return False
    return isinstance(error, dict) and error.get("type") == "insufficient_credits"


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


def _tool_observation(
    call: dict[str, Any], name: str, payload: dict[str, Any] | str
) -> dict[str, Any]:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "role": "tool",
        "tool_call_id": str(call.get("id") or name),
        "content": content[:100_000],
    }


def _observation_text(observation: Any, rendered: Any = None) -> str:
    """The Agent's view of an observation: its ``render()`` text.

    Falls back to the ``text`` field, then to the populated fields as JSON for an
    Environment that renders nothing. Empty fields are never sent.
    """
    if isinstance(rendered, str) and rendered.strip():
        return rendered
    if not isinstance(observation, dict):
        return "" if observation is None else str(observation)
    text = observation.get("text")
    if isinstance(text, str) and text.strip():
        return text
    fields = {
        key: value
        for key, value in observation.items()
        if key != "text" and value not in (None, "", {}, [])
    }
    return json.dumps(fields, sort_keys=True) if fields else ""


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
    rendered = parsed.get("rendered")
    signals = parsed.get("rewards")
    if not isinstance(signals, list) and isinstance(info, dict):
        signals = info.get("rewards")
    return {
        "observation": observation if isinstance(observation, dict) else {},
        "rendered": rendered if isinstance(rendered, str) else None,
        "rewards": [item for item in signals if isinstance(item, dict)]
        if isinstance(signals, list)
        else [],
        "terminated": bool(parsed.get("terminated")),
        "truncated": bool(parsed.get("truncated")),
        "info": info if isinstance(info, dict) else {},
        "view": parsed.get("view") if isinstance(parsed.get("view"), dict) else None,
    }


# Keep in sync with the tools plural.harness.packages declares for native.workspace.v1;
# test_native_workspace.py asserts they match.
WORKSPACE_TOOLS: dict[str, dict[str, Any]] = {
    "read_file": {
        "description": "Read a text file. Paths are relative to your working folder.",
        "capability": "file_read",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    "write_file": {
        "description": (
            "Write a text file, replacing it if it exists and creating its folders. "
            "Paths are relative to your working folder."
        ),
        "capability": "file_edit",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    "list_files": {
        "description": (
            "List files under a folder, to any depth. Paths are relative to your working "
            "folder; the default is the working folder itself."
        ),
        "capability": "file_read",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": [],
        },
    },
    "run": {
        "description": "Run a shell command in your working folder and see its output.",
        "capability": "shell",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "number"},
            },
            "required": ["command"],
        },
    },
}
_WORKSPACE_OUTPUT_CHARS = 20_000
_WORKSPACE_LIST_LIMIT = 500
_RUN_TIMEOUT_SECONDS = 120.0


class _WorkspaceTools:
    """The native loop's own tools in an Environment with no Apps.

    They act on the sandbox workspace directly, as another Harness's tools do, and
    each call is reported to the App host, when there is one, as a Harness tool step.
    """

    def __init__(self, environment: dict[str, Any], denials: list[dict[str, str]]) -> None:
        self.environment = environment
        self.cwd = Path(
            _workspace_path(str(environment.get("workspace") or "/workspace/environment"))
        )
        self.root = Path(_workspace_path("/workspace")).resolve()
        denied = {item["capability"] for item in denials}
        self.offered = {
            name: spec for name, spec in WORKSPACE_TOOLS.items() if spec["capability"] not in denied
        }

    def declarations(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["description"],
                    "parameters": spec["parameters"],
                },
            }
            for name, spec in self.offered.items()
        ]

    def dispatch(self, call: Any, deadline: float, turn: int) -> _ToolOutcome:
        """Run one call and report it; the model sees the output, or the error.

        Returns:
            The tool message, and the step the host numbered it, once it has.
        """
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            raise ValueError("model emitted an invalid tool call")
        name = str(call["function"].get("name") or "")
        try:
            arguments = _arguments(call["function"])
        except (TypeError, ValueError):
            arguments = {}
        output: Any = None
        error: str | None = None
        background = False
        if name not in self.offered:
            error = f"unknown tool {name!r}"
        else:
            try:
                output, background = getattr(self, f"_{name}")(arguments, deadline)
            except (OSError, ValueError, UnicodeDecodeError, subprocess.SubprocessError) as exc:
                error = str(exc) or type(exc).__name__
        number = self._report(name, arguments, output, error, background)
        visible = f"Error: {error}" if error else output
        text = visible if isinstance(visible, str) else json.dumps(visible)
        message = _tool_observation(call, name, text)
        if number is None:
            return _ToolOutcome(message=message)
        return _ToolOutcome(
            message=message,
            transition={
                "type": "step",
                "turn": turn,
                "action": name,
                "arguments": arguments,
                "observation": None if output is None else {"text": text},
                "info": {"step": number, **({"error": error} if error else {})},
            },
        )

    def _path(self, arguments: dict[str, Any], default: str | None = None) -> Path:
        raw = arguments.get("path", default)
        if not isinstance(raw, str) or not raw:
            raise ValueError("path is required")
        path = (self.cwd / raw).resolve()
        if path != self.root and not path.is_relative_to(self.root):
            raise ValueError(f"{raw} is outside the workspace")
        if any(part.startswith(".plural") for part in path.relative_to(self.root).parts):
            raise ValueError(f"{raw} is not readable")
        return path

    def _read_file(self, arguments: dict[str, Any], deadline: float) -> tuple[str, bool]:
        text = self._path(arguments).read_text(encoding="utf-8")
        if len(text) > _WORKSPACE_OUTPUT_CHARS:
            text = text[:_WORKSPACE_OUTPUT_CHARS] + "\n[truncated]"
        return text, False

    def _write_file(self, arguments: dict[str, Any], deadline: float) -> tuple[str, bool]:
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        path = self._path(arguments)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content.encode())} bytes to {arguments['path']}.", False

    def _list_files(self, arguments: dict[str, Any], deadline: float) -> tuple[str, bool]:
        folder = self._path(arguments, ".")
        found = []
        for path in sorted(folder.rglob("*")):
            relative = path.relative_to(self.root)
            if any(part.startswith(".plural") for part in relative.parts) or not path.is_file():
                continue
            found.append(os.path.relpath(path, self.cwd))
            if len(found) >= _WORKSPACE_LIST_LIMIT:
                found.append("[more files not shown]")
                break
        return "\n".join(found) or "(no files)", False

    def _run(self, arguments: dict[str, Any], deadline: float) -> tuple[str, bool]:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command is required")
        requested = arguments.get("timeout_seconds")
        limit = float(requested) if isinstance(requested, (int, float)) and requested > 0 else None
        timeout = min(
            limit or _RUN_TIMEOUT_SECONDS, _RUN_TIMEOUT_SECONDS, deadline - time.monotonic()
        )
        if timeout <= 0:
            raise TimeoutError("episode deadline expired")
        try:
            completed = subprocess.run(
                ["sh", "-c", command],
                cwd=self.cwd,
                env=_action_environment(self.environment),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout:.0f} seconds.", False
        text = (completed.stdout + completed.stderr).decode(errors="replace")
        if len(text) > _WORKSPACE_OUTPUT_CHARS:
            text = text[-_WORKSPACE_OUTPUT_CHARS:]
        return f"exit code {completed.returncode}\n{text}", False

    def _report(
        self, name: str, arguments: dict[str, Any], output: Any, error: str | None, background: bool
    ) -> int | None:
        command = self.environment.get("tool_command")
        if not command:
            return None
        payload = {
            "arguments": arguments,
            "output": output,
            "error": error,
            "background": background,
        }
        try:
            completed = subprocess.run(
                [*_local_command(list(command)), name],
                input=json.dumps(payload).encode(),
                cwd=self.cwd,
                env=_action_environment(self.environment),
                capture_output=True,
                timeout=30,
                check=False,
            )
            answer = json.loads(completed.stdout or b"null")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            # A missing report loses the step, never the episode.
            return None
        number = answer.get("step") if isinstance(answer, dict) else None
        return number if isinstance(number, int) and not isinstance(number, bool) else None


def _dispatch_tool(
    call: Any,
    actions: dict[str, dict[str, Any]],
    environment: dict[str, Any],
    denials: list[dict[str, str]],
    deadline: float,
    turn: int,
    *,
    finish: bool = True,
) -> _ToolOutcome:
    if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
        raise ValueError("model emitted an invalid action call")
    function = call["function"]
    name = str(function.get("name") or "")
    denied = {item["capability"]: item["reason"] for item in denials}
    if name == _FINISH and _FINISH not in actions and finish:
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
    host = environment.get("reset_command") or []
    if action_name not in actions and host and 0 < len(action_name) <= MAX_UNKNOWN_NAME:
        # The App host records the call as an unknown_action step, and answers it.
        unknown = {"command": [*host[:-1], "unknown", action_name]}
        return _run_action(call, action_name, {action_name: unknown}, environment, deadline, turn)
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
    timeout = min(float(declaration.get("timeout_seconds") or 30), remaining)
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
    # The Agent sees the rendered observation and its own errors.
    visible = _observation_text(envelope["observation"], envelope["rendered"])
    error = envelope["info"].get("error")
    if error:
        visible = "\n\n".join(part for part in (f"Error: {error}", visible) if part)
    return _ToolOutcome(
        message=_tool_observation(call, name, visible),
        transition={
            "type": "step",
            "turn": turn,
            "action": name,
            "arguments": arguments,
            "observation": envelope["observation"],
            "rewards": envelope["rewards"],
            "terminated": envelope["terminated"],
            "truncated": envelope["truncated"],
            "info": envelope["info"],
            "view": envelope["view"],
        },
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


def _resumed_prompt(prompt: str, resume: dict[str, Any], reset: dict[str, Any]) -> str:
    """The opening message of a fork that gets the history as text, or none at all."""
    now = _observation_text(reset.get("observation")) or _observation_text(
        resume.get("observation"), resume.get("rendered")
    )
    parts = [prompt]
    transcript = str(resume.get("transcript") or "").strip()
    if resume.get("history") == "transcript" and transcript:
        parts.append(transcript)
    else:
        parts.append("This episode is already under way; earlier steps are not shown.")
    if now:
        parts.append(f"Where things stand now:\n{now}")
    if resume.get("note"):
        parts.append(str(resume["note"]))
    return "\n\n".join(parts)


def _after_history(resume: dict[str, Any], reset: dict[str, Any]) -> str:
    """What follows a native history: a forced action's result, and a diagnostic note."""
    parts: list[str] = []
    raw = reset.get("info")
    info: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if info.get("step") is not None and info.get("step") != resume.get("step"):
        now = _observation_text(reset.get("observation"))
        if now:
            parts.append(f"Your next action ran. Where things stand now:\n{now}")
    if resume.get("note"):
        parts.append(str(resume["note"]))
    return "\n\n".join(parts)


def _prompt(request: dict[str, Any], environment: dict[str, Any]) -> str:
    """The opening user message: the Task, then the first observation, as text.

    Tools reach the model as tool schemas and denials in the system prompt, so
    neither is repeated here.
    """
    task = _mapping(request.get("task"), "task")
    parts: list[str] = []
    instructions = task.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        parts.append(instructions.strip())
    for label, value in (("Task info", task.get("info")), ("Metadata", task.get("metadata"))):
        if value not in (None, "", {}, []):
            parts.append(f"{label}:\n{json.dumps(value, sort_keys=True, indent=2)}")
    observation = _observation_text(
        environment.get("observation"), environment.get("observation_rendered")
    )
    if observation:
        parts.append(observation)
    return "\n\n".join(parts)


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
    # A seat's directions are its own: they go in its folder, not the one every seat shares.
    own = Path(_workspace_path(str(request.get("workspace")))) if task.get("seat") else workspace
    (own / "task.json").write_text(json.dumps(task, sort_keys=True) + "\n", encoding="utf-8")
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
        environment["observation_rendered"] = envelope["rendered"]
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


def _await_turn(environment: dict[str, Any], deadline: float) -> dict[str, Any] | None:
    """Wait until this seat may act or the episode ends, and return its view.

    Returns:
        The host's ``turn`` answer, or ``None`` when the deadline passed first.
    """
    command = _local_command(list(environment.get("turn_command") or ()))
    workspace = _workspace_path(str(environment.get("workspace") or "/workspace/environment"))
    polls = 0
    while time.monotonic() < deadline:
        completed = subprocess.run(
            command,
            input=b"",
            cwd=workspace,
            env=_action_environment(environment),
            capture_output=True,
            timeout=max(1.0, min(30.0, deadline - time.monotonic())),
            check=False,
        )
        if completed.returncode != 0:
            error = completed.stderr.decode(errors="replace")[:1000]
            raise RuntimeError(f"environment turn failed: {error or completed.returncode}")
        answer = json.loads(completed.stdout.decode(errors="replace") or "{}")
        if not isinstance(answer, dict):
            raise RuntimeError("environment turn answered something other than an object")
        if answer.get("your_turn") or answer.get("terminated") or answer.get("truncated"):
            return answer
        time.sleep(_TURN_POLL_SECONDS[min(polls, len(_TURN_POLL_SECONDS) - 1)])
        polls += 1
    return None


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
        "HOME",
        "SYSTEMROOT",
        "PLURAL_APPS_MANAGED",
        SEAT_TOKEN,
        *environment.get("variable_names", []),
    }
    values = {key: value for key, value in os.environ.items() if key in names}
    values["PLURAL_RESOURCES_DIR"] = _workspace_path("/workspace/resources")
    return values


def _context_tokens(messages: list[dict[str, Any]]) -> int:
    """A rough size of a context in tokens: four characters each."""
    return len(json.dumps(messages, default=str)) // 4


def _turn_starts(messages: list[dict[str, Any]]) -> list[int]:
    """Where each turn starts: each assistant message, with what answers it after."""
    return [index for index, item in enumerate(messages) if item.get("role") == "assistant"]


def _compact(
    episode: _Episode,
    policy: dict[str, Any],
    *,
    model: str,
    routing: dict[str, Any],
    timeout: float,
    turn: int,
) -> tuple[float | None, float]:
    """Apply the Agent's context policy before a model call, and record what it did.

    ``window`` drops the oldest turns, keeping the instructions, the Task, and the
    last ``keep_last_turns`` turns. ``summarize`` replaces everything but the
    instructions and the last turns with a summary the Agent's own model writes.
    ``none`` does nothing. Either runs only once the context is over ``max_tokens``.

    Returns:
        What a summary cost, if one was written, and the seconds spent waiting for credits.
    """
    strategy = str(policy.get("strategy") or "none")
    limit = policy.get("max_tokens")
    messages = episode.messages
    if strategy == "none" or not limit:
        return None, 0.0
    before = _context_tokens(messages)
    if before <= int(limit):
        return None, 0.0
    keep = max(1, int(policy.get("keep_last_turns") or 4))
    starts = _turn_starts(messages)
    if len(starts) <= keep:
        return None, 0.0
    cut = starts[-keep]
    head = [item for item in messages[:1] if item.get("role") == "system"]
    started = _started()
    if strategy == "window":
        # The Task's own message stays; the oldest turns after it go.
        opening = messages[len(head) : len(head) + 1]
        dropped = cut - len(head) - len(opening)
        if dropped <= 0:
            return None, 0.0
        messages[:] = [*head, *opening, *messages[cut:]]
        episode.compacted(
            started,
            turn=turn,
            policy=policy,
            before=before,
            dropped=dropped,
            summary=None,
            usage=None,
            model=None,
        )
        return None, 0.0
    older = messages[len(head) : cut]
    transcript = "\n\n".join(
        f"{item.get('role')}: {item.get('content') or ''}"
        + (
            "\n" + json.dumps(item.get("tool_calls"), default=str)[:2000]
            if item.get("tool_calls")
            else ""
        )
        for item in older
    )[-60_000:]
    response, paused = _model_call(
        model=model,
        routing=routing,
        messages=[
            {
                "role": "system",
                "content": "Summarize this conversation so the assistant can carry on with "
                "its work. Keep what it was asked to do, decisions made, and anything still "
                "pending.",
            },
            {"role": "user", "content": transcript},
        ],
        tools=[],
        timeout=timeout,
    )
    summary = str(_response_message(response).get("content") or "").strip()
    usage = _usage(response.get("usage"))
    messages[:] = [
        *head,
        {"role": "user", "content": f"Summary of the conversation so far:\n{summary}"},
        *messages[cut:],
    ]
    episode.compacted(
        started,
        turn=turn,
        policy=policy,
        before=before,
        dropped=len(older),
        summary=summary,
        usage=usage,
        model=str(response.get("model") or model),
    )
    return usage.get("cost_usd"), paused


if __name__ == "__main__":
    main()
