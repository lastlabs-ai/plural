"""Synchronous policy interfaces and built-in adapters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from enroute.client import Enroute
from enroute.tracing.schema import ParsedAction, TraceContext
from enroute.types import ChatRequest, ChatResponse

PolicyOutput = ChatResponse | ParsedAction | list[ParsedAction]


@runtime_checkable
class Policy(Protocol):
    """A synchronous policy that chooses an action for one request."""

    def act(
        self,
        request: ChatRequest,
        *,
        trace_context: TraceContext | None = None,
    ) -> PolicyOutput:
        """Choose an action from the exact environment request."""
        ...


class EnroutePolicy:
    """Policy adapter backed by :class:`~enroute.client.Enroute`.

    Args:
        client: Enroute client used for model calls.
        model: Primary model id.
        fallbacks: Optional fallback model chain.
        temperature: Optional sampling temperature.
        tags: Trace tags attached to each model call.
        record_llm_traces: Persist linked model-call traces.
    """

    def __init__(
        self,
        client: Enroute,
        model: str,
        *,
        fallbacks: list[str] | None = None,
        temperature: float | None = None,
        tags: dict[str, str] | None = None,
        record_llm_traces: bool = False,
    ) -> None:
        self.client = client
        self.model = model
        self.fallbacks = list(fallbacks) if fallbacks is not None else None
        self.temperature = temperature
        self.tags = dict(tags or {})
        self.record_llm_traces = record_llm_traces

    def act(
        self,
        request: ChatRequest,
        *,
        trace_context: TraceContext | None = None,
    ) -> ChatResponse:
        """Call Enroute without dropping any normalized request fields.

        Returns:
            The normalized chat response.
        """
        request.model = self.model
        if request.models is None:
            request.models = self.fallbacks
        if request.temperature is None:
            request.temperature = self.temperature
        return self.client.chat(
            model=request.model,
            messages=request.messages,
            models=request.models,
            tools=request.tools,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            metadata=request.metadata,
            tags=self.tags,
            write_trace=self.record_llm_traces,
            trace_context=trace_context,
            top_p=request.top_p,
            stop=request.stop,
            tool_choice=request.tool_choice,
            response_format=request.response_format,
            stream=request.stream,
            seed=request.seed,
            user=request.user,
            provider=request.provider,
            extra=request.extra,
        )


class ScriptedPolicy:
    """Deterministic policy that returns preconfigured actions in order."""

    def __init__(self, actions: Iterable[PolicyOutput]) -> None:
        self.actions = list(actions)
        self.index = 0

    def act(
        self,
        request: ChatRequest,
        *,
        trace_context: TraceContext | None = None,
    ) -> PolicyOutput:
        """Return the next scripted action.

        Raises:
            RuntimeError: If the script has no action left.
        """
        del request, trace_context
        if self.index >= len(self.actions):
            raise RuntimeError("ScriptedPolicy exhausted: no actions remain")
        action = self.actions[self.index]
        self.index += 1
        return action
