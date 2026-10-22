"""Trace a LangChain or LangGraph agent to Plural.

Pass the handler as a callback, and every model call, tool call, and the final
answer of each run is recorded into the current Plural run, or into a run of
its own when there is none::

    from plural.external.langchain import PluralCallbackHandler

    graph.invoke(inputs, config={"callbacks": [PluralCallbackHandler()]})
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from plural.external._adapters import Roots, text_of, usage
from plural.external.tracing import ToolCall, Tracer

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import LLMResult
except ImportError as exc:  # pragma: no cover - exercised only without LangChain
    raise ImportError(
        "The LangChain adapter needs langchain-core: pip install langchain-core"
    ) from exc

_ROLES = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}


class PluralCallbackHandler(BaseCallbackHandler):
    """Records a LangChain or LangGraph run into Plural.

    Args:
        tracer: The Plural tracer; defaults to the process's
            (:func:`plural.external.tracer`).
    """

    # Called inline so the handler sees the context, and so the run, it was called in.
    run_inline = True

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._roots = Roots(tracer)
        self._lock = threading.Lock()
        self._root_of: dict[UUID, UUID] = {}
        self._calls: dict[UUID, dict[str, Any]] = {}

    def _root(self, run_id: UUID, parent_run_id: UUID | None) -> UUID:
        with self._lock:
            # A parent this handler never saw start, such as one without it as a
            # callback, leaves this run as the root.
            root = self._root_of.get(parent_run_id, run_id) if parent_run_id else run_id
            self._root_of[run_id] = root
        if root == run_id:
            self._roots.open(root)
        return root

    def _end(self, run_id: UUID) -> UUID | None:
        with self._lock:
            return self._root_of.pop(run_id, None)

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Open a Plural run for a top-level chain or graph run."""
        self._root(run_id, parent_run_id)

    def on_chain_end(self, outputs: dict[str, Any], *, run_id: UUID, **kwargs: Any) -> None:
        """Finish a top-level run with its answer."""
        if self._end(run_id) == run_id:
            self._roots.close(run_id, answer=_answer(outputs))

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        """Finish a top-level run as failed."""
        if self._end(run_id) == run_id:
            self._roots.close(run_id, error=f"{type(error).__name__}: {error}")

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Remember a chat model call's messages until it ends."""
        self._start_call(
            run_id,
            parent_run_id,
            messages=[_message(item) for item in (messages[0] if messages else [])],
            model=_model(serialized, metadata, kwargs),
        )

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Remember a completion call's prompt until it ends."""
        self._start_call(
            run_id,
            parent_run_id,
            messages=[{"role": "user", "content": prompt} for prompt in prompts[:1]],
            model=_model(serialized, metadata, kwargs),
        )

    def _start_call(self, run_id: UUID, parent_run_id: UUID | None, **call: Any) -> None:
        root = self._root(run_id, parent_run_id)
        with self._lock:
            self._calls[run_id] = {**call, "root": root, "started": datetime.now(timezone.utc)}

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        """Record a model call."""
        call, root = self._finish_call(run_id)
        run = self._roots.get(root) if root else None
        if call is None or run is None:
            return
        generation = (
            response.generations[0][0] if response.generations and response.generations[0] else None
        )
        message = getattr(generation, "message", None)
        text = text_of(
            getattr(message, "content", None) if message else getattr(generation, "text", "")
        )
        output = response.llm_output or {}
        metadata = getattr(message, "response_metadata", None) or {}
        counts = getattr(message, "usage_metadata", None) or {}
        token_usage = output.get("token_usage") or output.get("usage") or {}
        run.llm(
            model=metadata.get("model_name") or output.get("model_name") or call["model"],
            messages=call["messages"],
            output=text,
            tool_calls=[
                ToolCall(
                    id=str(item.get("id") or ""),
                    name=str(item["name"]),
                    arguments=item.get("args") or {},
                )
                for item in getattr(message, "tool_calls", None) or []
            ],
            usage=usage(
                counts.get("input_tokens", token_usage.get("prompt_tokens")),
                counts.get("output_tokens", token_usage.get("completion_tokens")),
                (counts.get("input_token_details") or {}).get("cache_read"),
            ),
            latency_ms=_elapsed(call["started"]),
            started_at=call["started"],
        )
        if root == run_id:
            self._roots.close(root, answer=text)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        """Record a failed model call."""
        call, root = self._finish_call(run_id)
        run = self._roots.get(root) if root else None
        if call is None or run is None:
            return
        message = f"{type(error).__name__}: {error}"
        run.llm(
            model=call["model"],
            messages=call["messages"],
            error=message,
            latency_ms=_elapsed(call["started"]),
            started_at=call["started"],
        )
        if root == run_id:
            self._roots.close(root, error=message)

    def _finish_call(self, run_id: UUID) -> tuple[dict[str, Any] | None, UUID | None]:
        with self._lock:
            call = self._calls.pop(run_id, None)
        return call, self._end(run_id)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Remember a tool call's arguments until it ends."""
        root = self._root(run_id, parent_run_id)
        arguments = inputs if isinstance(inputs, Mapping) else {"input": input_str}
        with self._lock:
            self._calls[run_id] = {
                "root": root,
                "name": str((serialized or {}).get("name") or kwargs.get("name") or "tool"),
                "arguments": dict(arguments),
                "call_id": kwargs.get("tool_call_id"),
                "started": datetime.now(timezone.utc),
            }

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        """Record a tool call and its result."""
        self._tool(run_id, result=output)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        """Record a failed tool call."""
        self._tool(run_id, error=f"{type(error).__name__}: {error}")

    def _tool(self, run_id: UUID, *, result: Any = None, error: str | None = None) -> None:
        call, root = self._finish_call(run_id)
        run = self._roots.get(root) if root else None
        if call is None or run is None:
            return
        call_id = call["call_id"] or getattr(result, "tool_call_id", None)
        run.tool(
            call["name"],
            call["arguments"],
            getattr(result, "content", result),
            call_id=str(call_id) if call_id else None,
            error=error,
            latency_ms=_elapsed(call["started"]),
            started_at=call["started"],
        )
        if root == run_id:
            self._roots.close(root, error=error)


def _message(message: BaseMessage) -> dict[str, Any]:
    out: dict[str, Any] = {
        "role": _ROLES.get(message.type, message.type),
        "content": text_of(message.content),
    }
    calls = getattr(message, "tool_calls", None) or []
    if calls:
        out["tool_calls"] = [
            {
                "id": str(call.get("id") or ""),
                "type": "function",
                "function": {"name": str(call["name"]), "arguments": call.get("args") or {}},
            }
            for call in calls
        ]
    call_id = getattr(message, "tool_call_id", None)
    if call_id:
        out["tool_call_id"] = str(call_id)
    return out


def _model(
    serialized: Mapping[str, Any] | None,
    metadata: Mapping[str, Any] | None,
    extra: Mapping[str, Any],
) -> str | None:
    params = extra.get("invocation_params") or {}
    for value in (
        (metadata or {}).get("ls_model_name"),
        params.get("model") if isinstance(params, Mapping) else None,
        params.get("model_name") if isinstance(params, Mapping) else None,
        ((serialized or {}).get("kwargs") or {}).get("model"),
    ):
        if isinstance(value, str) and value:
            return value
    return None


def _answer(outputs: Any) -> str | None:
    """The final answer of a chain or graph run.

    Returns:
        The last AI message of a LangGraph state, or the ``output`` of a chain.
    """
    if isinstance(outputs, Mapping):
        messages = outputs.get("messages")
        if isinstance(messages, Sequence) and not isinstance(messages, str):
            for message in reversed(messages):
                if isinstance(message, BaseMessage) and message.type == "ai":
                    return text_of(message.content) or None
        for key in ("output", "answer", "result"):
            if key in outputs:
                return text_of(getattr(outputs[key], "content", outputs[key])) or None
        return None
    if isinstance(outputs, BaseMessage):
        return text_of(outputs.content) or None
    return text_of(outputs) or None if outputs is not None else None


def _elapsed(started: datetime) -> float:
    return (datetime.now(timezone.utc) - started).total_seconds() * 1000


__all__ = ["PluralCallbackHandler"]
