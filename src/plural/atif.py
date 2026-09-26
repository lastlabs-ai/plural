"""Export an episode as Harbor's Agent Trajectory Interchange Format (ATIF).

Every execution that records ``episode.jsonl`` also gets ``trajectory.json``,
an ATIF document of what the Agent did: the system prompt and Task, then one
``agent`` step per model call with its message, reasoning, tool calls, the
results the Agent saw, and that call's tokens and cost. See the
`ATIF RFC <https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md>`_.

Only what reached the Agent is written as step content. Reward, termination,
and Verifier scores are episode bookkeeping and stay in ``episode.jsonl`` and
the Trial result, so a trajectory loaded back as context cannot leak them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from plural.usage import TokenUsage

ATIF_VERSION = "ATIF-v1.7"
ATIF_FILE = "trajectory.json"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [
            str(item.get("text"))
            for item in value
            if isinstance(item, Mapping) and item.get("type") == "text" and item.get("text")
        ]
        if parts:
            return "\n".join(parts)
    return json.dumps(value, sort_keys=True, default=str)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


def _tool_call(call: Mapping[str, Any], fallback_id: str) -> dict[str, Any]:
    function = _mapping(call.get("function"))
    name = function.get("name") if function else call.get("name")
    arguments = function.get("arguments") if function else call.get("arguments")
    return {
        "tool_call_id": str(call.get("id") or fallback_id),
        "function_name": str(name or ""),
        "arguments": _arguments(arguments),
    }


def _metrics(usage: TokenUsage, request_id: Any, duration_ms: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "cached_tokens": usage.cached_input_tokens,
        "cost_usd": usage.cost_usd,
    }
    extra = {
        "reasoning_tokens": usage.reasoning_tokens,
        "request_id": request_id if isinstance(request_id, str) else None,
        "duration_ms": duration_ms if isinstance(duration_ms, (int, float)) else None,
    }
    metrics["extra"] = {key: value for key, value in extra.items() if value is not None}
    return {key: value for key, value in metrics.items() if value not in (None, {})}


def _result(record: Mapping[str, Any], call_id: str | None) -> dict[str, Any]:
    content = record.get("content")
    if content is None:
        observation = record.get("observation")
        content = record.get("summary") if observation is None else observation
    error = record.get("error")
    if content is None and error:
        content = {"error": error}
    extra = {
        "action": record.get("action")
        or ("finish" if record.get("kind") == "agent.finish" else None),
        "error": error,
        "duration_ms": record.get("duration_ms"),
    }
    result: dict[str, Any] = {"content": _text(content)}
    if call_id:
        result["source_call_id"] = call_id
    result["extra"] = {key: value for key, value in extra.items() if value is not None}
    return result


def episode_to_atif(
    records: Iterable[Mapping[str, Any]],
    *,
    agent_name: str,
    agent_version: str = "unknown",
    model_name: str | None = None,
    session_id: str | None = None,
    trajectory_id: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert ``plural.episode/v1`` records into one ATIF trajectory.

    Args:
        records: The episode records, in order.
        agent_name: The Agent that ran.
        agent_version: Its version.
        model_name: The model it ran on by default.
        session_id: The run this trajectory belongs to, such as the Trial id.
        trajectory_id: This document's id, such as the execution key.
        extra: Root-level metadata.

    Returns:
        The ATIF document.
    """
    ordered = sorted(
        (dict(item) for item in records if isinstance(item, Mapping)),
        key=lambda item: int(item.get("sequence") or 0),
    )
    steps: list[dict[str, Any]] = []
    agent_steps: dict[int, dict[str, Any]] = {}
    seen_messages = 0

    def add(step: dict[str, Any]) -> dict[str, Any]:
        step["step_id"] = len(steps) + 1
        steps.append(step)
        return step

    for record in ordered:
        kind = record.get("kind")
        turn = record.get("turn")
        if kind == "model.call":
            messages = _list(record.get("messages"))
            offset = int(record.get("messages_offset") or 0)
            for index, message in enumerate(messages):
                if offset + index < seen_messages or not isinstance(message, Mapping):
                    continue
                role = message.get("role")
                if role in {"system", "developer", "user"}:
                    add(
                        {
                            "timestamp": record.get("started_at"),
                            "source": "user" if role == "user" else "system",
                            "message": _text(message.get("content")),
                        }
                    )
            seen_messages = max(seen_messages, int(record.get("message_count") or 0))
            model = str(record.get("model") or model_name or "")
            raw_usage = _mapping(record.get("usage"))
            usage = TokenUsage.model_validate(
                {key: raw_usage.get(key) for key in TokenUsage.model_fields}
            )
            calls = _list(record.get("tool_calls"))
            step: dict[str, Any] = {
                "timestamp": record.get("started_at"),
                "source": "agent",
                "model_name": model or None,
                "message": _text(record.get("text")),
                "reasoning_content": record.get("reasoning") or None,
                "tool_calls": [
                    _tool_call(call, f"call-{record.get('sequence')}-{index}")
                    for index, call in enumerate(calls)
                    if isinstance(call, Mapping)
                ]
                or None,
                "metrics": _metrics(usage, record.get("request_id"), record.get("duration_ms")),
                "llm_call_count": 1,
            }
            if record.get("error"):
                step["extra"] = {"error": record["error"]}
            added = add({key: value for key, value in step.items() if value is not None})
            if isinstance(turn, int):
                agent_steps[turn] = added
        elif kind in {"environment.step", "agent.finish"}:
            owner = agent_steps.get(turn) if isinstance(turn, int) else None
            if owner is None:
                # A Harness stepped the Environment without a model call.
                synthetic = f"step-{record.get('sequence')}"
                owner = add(
                    {
                        "timestamp": record.get("started_at"),
                        "source": "agent",
                        "message": "",
                        "tool_calls": [
                            {
                                "tool_call_id": synthetic,
                                "function_name": str(record.get("action") or ""),
                                "arguments": _arguments(record.get("arguments")),
                            }
                        ],
                        "llm_call_count": 0,
                    }
                )
                if isinstance(turn, int):
                    agent_steps[turn] = owner
                record = {**record, "tool_call_id": synthetic}
            calls = owner.get("tool_calls") or []
            answered = {
                item.get("source_call_id")
                for item in _list(_mapping(owner.get("observation")).get("results"))
            }
            call_id: str | None = record.get("tool_call_id") or next(
                (
                    item["tool_call_id"]
                    for item in calls
                    if item["tool_call_id"] not in answered
                    and item["function_name"] in {record.get("action"), "finish"}
                ),
                None,
            )
            owner.setdefault("observation", {"results": []})["results"].append(
                _result(record, call_id)
            )
    return {
        "schema_version": ATIF_VERSION,
        **({"session_id": session_id} if session_id else {}),
        **({"trajectory_id": trajectory_id} if trajectory_id else {}),
        "agent": {
            "name": agent_name,
            "version": agent_version,
            **({"model_name": model_name} if model_name else {}),
        },
        "steps": steps,
        "final_metrics": final_metrics(steps),
        **({"extra": dict(extra)} if extra else {}),
    }


def final_metrics(steps: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Totals over the steps' metrics. A total is ``None`` when no step reported it.

    Returns:
        ATIF ``final_metrics``, with how many model calls lacked tokens or cost in
        ``extra``.
    """
    steps = list(steps)
    totals: dict[str, Any] = {}
    calls = missing_tokens = missing_cost = 0
    for step in steps:
        if step.get("source") != "agent" or step.get("llm_call_count") == 0:
            continue
        calls += 1
        metrics = _mapping(step.get("metrics"))
        for field, total in (
            ("prompt_tokens", "total_prompt_tokens"),
            ("completion_tokens", "total_completion_tokens"),
            ("cached_tokens", "total_cached_tokens"),
            ("cost_usd", "total_cost_usd"),
        ):
            value = metrics.get(field)
            if isinstance(value, (int, float)):
                totals[total] = totals.get(total, 0) + value
        if metrics.get("prompt_tokens") is None or metrics.get("completion_tokens") is None:
            missing_tokens += 1
        if metrics.get("cost_usd") is None:
            missing_cost += 1
    return {
        **totals,
        "total_steps": len(steps),
        "extra": {
            "llm_calls": calls,
            "calls_missing_tokens": missing_tokens,
            "calls_missing_cost": missing_cost,
        },
    }


def validate_atif(document: Any) -> list[str]:
    """Check a document against the ATIF rules Plural relies on.

    Returns:
        One message per problem; empty when the document is valid.
    """
    if not isinstance(document, Mapping):
        return ["trajectory must be a JSON object"]
    problems: list[str] = []
    schema = document.get("schema_version")
    if not isinstance(schema, str) or not schema.startswith("ATIF-v1."):
        problems.append("schema_version must be ATIF-v1.x")
    agent = document.get("agent")
    if not isinstance(agent, Mapping) or not agent.get("name") or not agent.get("version"):
        problems.append("agent needs a name and a version")
    steps = document.get("steps")
    if not isinstance(steps, list):
        return [*problems, "steps must be a list"]
    known: set[str] = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, Mapping):
            problems.append(f"step {index} must be an object")
            continue
        if step.get("step_id") != index:
            problems.append(f"step {index} has step_id {step.get('step_id')!r}")
        source = step.get("source")
        if source not in {"system", "user", "agent"}:
            problems.append(f"step {index} has source {source!r}")
        if "message" not in step:
            problems.append(f"step {index} has no message")
        if source != "agent":
            for field in ("tool_calls", "metrics", "reasoning_content", "model_name"):
                if field in step:
                    problems.append(f"step {index} is a {source} step with {field}")
        if step.get("llm_call_count") == 0 and ("metrics" in step or "reasoning_content" in step):
            problems.append(f"step {index} made no model call but reports metrics or reasoning")
        for call in _list(step.get("tool_calls")):
            if not isinstance(call, Mapping) or not call.get("tool_call_id"):
                problems.append(f"step {index} has a tool call without tool_call_id")
                continue
            if not isinstance(call.get("arguments"), Mapping):
                problems.append(f"step {index} tool call {call['tool_call_id']} arguments")
            known.add(str(call["tool_call_id"]))
        for result in _list(_mapping(step.get("observation")).get("results")):
            source_call = result.get("source_call_id") if isinstance(result, Mapping) else None
            if source_call is not None and source_call not in known:
                problems.append(f"step {index} observes unknown tool call {source_call}")
    return problems


__all__ = [
    "ATIF_FILE",
    "ATIF_VERSION",
    "episode_to_atif",
    "final_metrics",
    "validate_atif",
]
