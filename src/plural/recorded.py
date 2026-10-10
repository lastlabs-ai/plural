"""Score conversations an agent already had, without running it again.

A recorded trace is an OpenAI-style message list: the conversation an agent
had, with its tool calls and their results. :meth:`plural.Job.from_traces`
turns each one into a Task and replays it through Plural's native Harness, so
the Task's Verifiers, any hindsight rewarders, ``plural rewards``, and the
training export all see it exactly as they would a live run. No model is
called and nothing in the recorded systems is touched.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import Field

from plural.agents.models import Agent, AgentDefinition
from plural.common import FrozenModel, HarnessBinding

RECORDING_KEY = "plural.recording"
"""The Task metadata key the replay Harness reads its conversation from."""


class RecordedTrace(FrozenModel):
    """One conversation an agent already had."""

    trace_id: str = Field(min_length=1)
    messages: tuple[dict[str, Any], ...] = Field(min_length=1)
    model: str = "recorded"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def instructions(self) -> str:
        """The first user message, which is what the agent was asked to do."""
        for message in self.messages:
            if message.get("role") == "user":
                text = _text(message.get("content"))
                if text.strip():
                    return text
        return f"Recorded trace {self.trace_id}."

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        """Every tool call with its recorded result, as replay App recordings.

        Returns:
            ``{"action", "arguments", "result"}`` entries, in call order.
        """
        from plural.apps.replay import normalize_recordings

        return normalize_recordings(list(self.messages))


def recordings_by_app(
    traces: Iterable[RecordedTrace], *, default_app: str = "recorded"
) -> dict[str, list[dict[str, Any]]]:
    """Every recorded tool call, grouped by the App it belongs to.

    A call named ``crm__get_record`` belongs to App ``crm`` as action
    ``get_record``, the names an Environment with several Apps exposes. Other
    calls belong to ``default_app``.

    Returns:
        App name to replay App recordings, in call order.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trace in traces:
        for call in trace.tool_calls:
            app, separator, action = str(call["action"]).partition("__")
            if not separator or not app or not action:
                app, action = default_app, str(call["action"])
            grouped.setdefault(app, []).append({**call, "action": action})
    return grouped


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
        )
    return ""


def _from_plural_trace(payload: Mapping[str, Any]) -> RecordedTrace | None:
    """The fullest conversation in a Plural ``Trace``: its longest model call.

    Returns:
        The recorded conversation, or ``None`` when the Trace made no model call.
    """
    best: list[dict[str, Any]] = []
    model = payload.get("model")
    for step in payload.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "llm":
            continue
        raw_request, raw_response = step.get("request"), step.get("response")
        request = raw_request if isinstance(raw_request, dict) else {}
        response = raw_response if isinstance(raw_response, dict) else {}
        messages = [item for item in request.get("messages") or [] if isinstance(item, dict)]
        choices = response.get("choices") or []
        reply = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
        if isinstance(reply, dict):
            messages.append(reply)
        if len(messages) >= len(best):
            best = messages
            model = step.get("model") or model
    if not best:
        return None
    return RecordedTrace(
        trace_id=str(payload["trace_id"]),
        messages=tuple(best),
        model=str(model or "recorded"),
        metadata=dict(payload.get("metadata") or {}),
    )


def recorded_trace(payload: Mapping[str, Any] | RecordedTrace, index: int = 0) -> RecordedTrace:
    """Read one recorded conversation.

    Accepts ``{"messages": [...]}`` (OpenAI chat logs and fine-tuning files,
    optionally with ``id`` or ``trace_id``, ``model``, and ``metadata``) and a
    Plural ``Trace`` with model-call steps.

    Returns:
        The conversation.

    Raises:
        ValueError: The payload holds no conversation.
    """
    if isinstance(payload, RecordedTrace):
        return payload
    if isinstance(payload.get("messages"), list):
        return RecordedTrace(
            trace_id=str(payload.get("trace_id") or payload.get("id") or f"trace-{index + 1}"),
            messages=tuple(item for item in payload["messages"] if isinstance(item, dict)),
            model=str(payload.get("model") or "recorded"),
            metadata=dict(payload.get("metadata") or {}),
        )
    if payload.get("trace_id") and isinstance(payload.get("steps"), list):
        found = _from_plural_trace(payload)
        if found is not None:
            return found
    raise ValueError(
        f"Trace {index + 1} has no conversation. Give each trace a 'messages' list "
        "(OpenAI chat format) or a Plural Trace with model-call steps."
    )


def read_traces(
    source: str | Path | Iterable[Mapping[str, Any] | RecordedTrace],
) -> list[RecordedTrace]:
    """Read recorded conversations from a JSONL or JSON file, or from objects.

    Returns:
        The conversations, in order.

    Raises:
        ValueError: The source is empty or a trace holds no conversation.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            items: list[Any] = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else [parsed]
    else:
        items = list(source)
    traces = [recorded_trace(item, index) for index, item in enumerate(items)]
    if not traces:
        raise ValueError("No recorded traces to read.")
    return traces


def _task_names(traces: Sequence[RecordedTrace]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for trace in traces:
        base = re.sub(r"[^a-z0-9]+", "-", trace.trace_id.lower()).strip("-") or "trace"
        name, suffix = base, 2
        while name in seen:
            name, suffix = f"{base}-{suffix}", suffix + 1
        seen.add(name)
        names.append(name)
    return names


class _RecordedAgent(Agent):
    """The agent that already ran: its recorded turns, replayed."""

    def _definition(self) -> AgentDefinition:
        from plural.harness.packages import native_replay_v1

        package = native_replay_v1()
        return AgentDefinition(
            name=self.name,
            revision=self.version,
            model=self.model,
            harness=HarnessBinding.from_package(package),
            harness_package=package,
            auth_mode="none",
            metadata={"recorded": True},
        )


def traces_benchmark(
    traces: Sequence[RecordedTrace],
    *,
    verifiers: Sequence[Any],
    environment: Any = None,
    name: str = "recorded-traces",
    initial_state: dict[str, Any] | None = None,
    reset_options: dict[str, Any] | None = None,
) -> Any:
    """One Task per recorded trace, each carrying its conversation.

    Returns:
        The Benchmark to run with :func:`recorded_agent`.
    """
    from plural.environments import Environment, Runtime
    from plural.tasks import Benchmark, Task

    target = environment or Environment(name=name, runtime=Runtime.local())
    tasks = [
        Task(
            name=task_name,
            instructions=trace.instructions,
            environment=target,
            verifiers=tuple(verifiers),
            initial_state=dict(initial_state or {}),
            reset_options=dict(reset_options or {}),
            metadata={
                RECORDING_KEY: {
                    "trace_id": trace.trace_id,
                    "model": trace.model,
                    "messages": list(trace.messages),
                },
                **trace.metadata,
            },
        )
        for task_name, trace in zip(_task_names(traces), traces, strict=True)
    ]
    return Benchmark(name=name, version="0.1.0", tasks=tuple(tasks))


def recorded_agent(traces: Sequence[RecordedTrace]) -> Agent:
    """The participant that replays recorded traces.

    Returns:
        An Agent named for the traces' model, which needs no catalog entry or key.
    """
    models = {trace.model for trace in traces}
    model = models.pop() if len(models) == 1 else "recorded"
    return _RecordedAgent.model_construct(
        model=model,
        name=model.rsplit("/", 1)[-1],
        version="0.1.0",
        auth_mode="none",
    )


__all__ = [
    "RECORDING_KEY",
    "RecordedTrace",
    "read_traces",
    "recorded_agent",
    "recordings_by_app",
    "recorded_trace",
    "traces_benchmark",
]
