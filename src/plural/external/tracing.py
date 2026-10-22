"""Trace an agent's runs to Plural, from any framework.

A :class:`Tracer` turns what an agent does into one trace per run. Inside a
Plural Job the run is the episode, and its trace goes to that Job with the
episode's own token, as the Agent's self-reported trace. Outside a Job it is a
production trace of the registered Agent, written with the ``PLURAL_API_KEY``
of the environment the agent runs in::

    from plural.external import Tracer

    tracer = Tracer.from_config()  # reads plural-agent.yaml
    with tracer.run(input="Where is order 42?") as run:
        run.llm(model="acme/v3", messages=[...], output="", tool_calls=[...])
        run.tool("lookup_order", {"order_id": "42"}, result={"status": "shipped"})
        run.finish("It shipped on Monday.")

Framework adapters (:mod:`plural.external.otel`, :mod:`plural.external.langchain`,
:mod:`plural.external.openai_agents`) record into the current run, or start one
per framework run when there is none. Tracing never raises into the agent: a
trace that cannot be written is logged and dropped.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import json
import logging
import os
import queue
import random
import re
import threading
import time
import weakref
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from plural.atif import ATIF_VERSION, final_metrics
from plural.external.client import KEY_VARIABLE, Episode
from plural.external.config import AgentConfig, AgentSection, Capture, FlushPolicy

log = logging.getLogger("plural.external")

_REDACTED = "[REDACTED]"
_CURRENT: contextvars.ContextVar[Run | None] = contextvars.ContextVar(
    "plural_external_run", default=None
)

Status = Literal["running", "succeeded", "failed"]


def current_run() -> Run | None:
    """The run being traced in this context.

    Returns:
        The run, or ``None`` outside one.
    """
    return _CURRENT.get()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ToolCall:
    """A tool call a model asked for."""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class _Record:
    kind: Literal["system", "user", "llm", "tool", "agent"]
    at: datetime
    text: str = ""
    model: str | None = None
    messages: tuple[Mapping[str, Any], ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    reasoning: str | None = None
    usage: Mapping[str, Any] | None = None
    name: str = ""
    call_id: str | None = None
    arguments: Mapping[str, Any] | None = None
    result: Any = None
    error: str | None = None
    latency_ms: float | None = None


class _Sink(Protocol):
    def write(self, run: Run, *, final: bool) -> None: ...


class Run:
    """One traced run of the agent. Use it as a context manager.

    Record what happens with :meth:`user`, :meth:`llm`, :meth:`tool`, and
    :meth:`message`, then :meth:`finish` with the answer. Leaving the ``with``
    block finishes the run if you did not, as failed when it raised.
    """

    def __init__(
        self,
        tracer: Tracer,
        sink: _Sink | None,
        *,
        trace_id: str,
        kind: Literal["episode", "production"],
        flush: FlushPolicy,
        capture: Capture,
        tags: Mapping[str, str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        episode: Episode | None = None,
    ) -> None:
        self.tracer = tracer
        self.trace_id = trace_id
        self.kind = kind
        self.flush_policy = flush
        self.capture = capture
        self.episode = episode
        self.started_at = _now()
        self.ended_at: datetime | None = None
        self.status: Status = "running"
        self.answer: Any = None
        self.error: str | None = None
        self.tags = dict(tags or {})
        self._metadata: dict[str, Any] = dict(metadata or {})
        self._sink = sink
        self._records: list[_Record] = []
        self._lock = threading.Lock()
        self._unflushed = 0
        self._flushed_at = time.monotonic()
        self._tokens: list[contextvars.Token[Run | None]] = []
        self._send_lock = threading.Lock()
        self._sent_final = False

    @property
    def recording(self) -> bool:
        """Whether this run is kept. An unsampled production run records nothing."""
        return self._sink is not None

    @property
    def finished(self) -> bool:
        """Whether the run has ended."""
        return self.status != "running"

    def __enter__(self) -> Run:
        self._tokens.append(_CURRENT.set(self))
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, _: Any
    ) -> None:
        if self._tokens:
            _CURRENT.reset(self._tokens.pop())
        # A run entered again, such as by tracer.run() inside an episode, ends
        # only when its outermost block does.
        if not self._tokens and not self.finished:
            if error is not None:
                self.fail(f"{type(error).__name__}: {error}")
            else:
                self.finish(self.answer)

    def system(self, text: str) -> None:
        """Record the system prompt."""
        self._add(_Record(kind="system", at=_now(), text=str(text)))

    def user(self, text: str) -> None:
        """Record a message to the agent, such as the request it is working on."""
        self._add(_Record(kind="user", at=_now(), text=str(text)))

    def message(self, text: str) -> None:
        """Record something the agent said without a model call."""
        self._add(_Record(kind="agent", at=_now(), text=str(text)))

    def llm(
        self,
        *,
        model: str | None = None,
        messages: Sequence[Mapping[str, Any]] = (),
        output: str | None = None,
        tool_calls: Sequence[ToolCall | Mapping[str, Any]] = (),
        reasoning: str | None = None,
        usage: Mapping[str, Any] | None = None,
        latency_ms: float | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        """Record one model call.

        Args:
            model: The model that answered.
            messages: What it was sent, in the OpenAI chat format.
            output: The text it returned.
            tool_calls: The tool calls it asked for.
            reasoning: Its reasoning, when it reported any.
            usage: ``prompt_tokens``, ``completion_tokens``, ``cached_tokens``,
                and ``cost_usd``, any of which may be missing.
            latency_ms: How long the call took.
            error: Why it failed, when it did.
            started_at: When it started; defaults to now.
        """
        self._add(
            _Record(
                kind="llm",
                at=started_at or _now(),
                text=output or "",
                model=model,
                messages=tuple(dict(item) for item in messages if isinstance(item, Mapping)),
                tool_calls=tuple(_tool_call(item, index) for index, item in enumerate(tool_calls)),
                reasoning=reasoning,
                usage=dict(usage) if usage else None,
                latency_ms=latency_ms,
                error=error,
            )
        )

    def tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        result: Any = None,
        *,
        call_id: str | None = None,
        error: str | None = None,
        latency_ms: float | None = None,
        started_at: datetime | None = None,
    ) -> None:
        """Record one tool call and what it returned.

        ``call_id`` ties it to the model call that asked for it; without one it
        is matched to the latest unanswered call of the same tool.
        """
        self._add(
            _Record(
                kind="tool",
                at=started_at or _now(),
                name=str(name),
                call_id=call_id,
                arguments=dict(arguments or {}),
                result=result,
                error=error,
                latency_ms=latency_ms,
            )
        )

    def metadata(self, **values: Any) -> None:
        """Attach values to the trace, such as a customer or request id."""
        with self._lock:
            self._metadata.update(values)

    def finish(self, answer: Any = None) -> None:
        """End the run with the agent's answer, and write its trace.

        In a Job this also ends the episode, so call it once, last.
        """
        if not self._close("succeeded", answer=answer):
            return
        if self.episode is not None:
            try:
                self.episode.finish(answer)
            except Exception as exc:  # noqa: BLE001 - never raise into the agent
                log.warning("Plural could not finish episode %s: %s", self.trace_id, exc)

    def fail(self, error: str) -> None:
        """End the run as failed. In a Job the episode ends with no answer."""
        if not self._close("failed", error=error):
            return
        if self.episode is not None:
            with contextlib.suppress(Exception):
                self.episode.finish(None)

    def _close(self, status: Status, *, answer: Any = None, error: str | None = None) -> bool:
        with self._lock:
            if self.finished:
                return False
            self.status = status
            self.answer = answer
            self.error = error
            self.ended_at = _now()
            if isinstance(answer, str) and answer.strip() and self._last_message() != answer:
                self._records.append(_Record(kind="agent", at=self.ended_at, text=answer))
        self.tracer._forget(self)
        self._write(final=True)
        return True

    def _last_message(self) -> str:
        for record in reversed(self._records):
            if record.kind in {"llm", "agent"} and record.text.strip():
                return record.text
        return ""

    def _add(self, record: _Record) -> None:
        if self._sink is None:
            return
        with self._lock:
            if self.finished:
                return
            self._records.append(record)
            self._unflushed += 1
            due = (
                self.flush_policy.mode == "steps"
                and self._unflushed >= self.flush_policy.every_steps
            )
        if due:
            self._write(final=False)

    def _due(self, now: float) -> bool:
        return (
            self.flush_policy.mode == "interval"
            and self._unflushed > 0
            and now - self._flushed_at >= self.flush_policy.interval_seconds
        )

    def _write(self, *, final: bool) -> None:
        if self._sink is None:
            return
        with self._lock:
            self._unflushed = 0
            self._flushed_at = time.monotonic()
        try:
            self._sink.write(self, final=final)
        except Exception as exc:  # noqa: BLE001 - never raise into the agent
            log.warning("Plural could not write trace %s: %s", self.trace_id, exc)

    def _deliver(self, send: Any, *, final: bool) -> None:
        """Send one write, never after the final one, so a late update cannot replace it."""
        with self._send_lock:
            if self._sent_final:
                return
            send()
            if final:
                self._sent_final = True

    def snapshot(self) -> tuple[list[_Record], dict[str, Any]]:
        """Read the run so far.

        Returns:
            Its records in time order, and its metadata.
        """
        with self._lock:
            records = sorted(self._records, key=lambda item: item.at)
            return records, dict(self._metadata)

    def atif(self) -> dict[str, Any]:
        """Render the trace as a Job keeps it.

        Returns:
            The ATIF document.
        """
        return self.tracer._render(self, "atif")

    def trace(self) -> dict[str, Any]:
        """Render the trace as the Traces page keeps it.

        Returns:
            The Plural ``Trace`` payload.
        """
        return self.tracer._render(self, "trace")


class _EpisodeSink:
    """Writes a run's ATIF to the Job that started the episode."""

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def write(self, run: Run, *, final: bool) -> None:
        episode = run.episode
        assert episode is not None

        def send() -> None:
            run._deliver(lambda: episode.trace(run.atif()), final=final)

        if final:
            # The episode ends right after, and refuses a trace once it has.
            send()
        else:
            self._tracer._background.submit(run, send)


class _PluralSink:
    """Writes a run's Trace to the Plural API, off the agent's thread."""

    def __init__(self, tracer: Tracer, studio: Any) -> None:
        self._tracer = tracer
        self._studio = studio
        self._agent_id: str | None = None
        self._resolved = False
        self._lock = threading.Lock()

    def write(self, run: Run, *, final: bool) -> None:
        self._tracer._background.submit(
            run, lambda: run._deliver(lambda: self._send(run, final=final), final=final)
        )

    def _send(self, run: Run, *, final: bool) -> None:
        links: dict[str, Any] = {"in_progress": not final}
        agent_id = self._agent()
        if agent_id:
            links["agent_id"] = agent_id
        self._studio.traces.create(run.trace(), **links)

    def _agent(self) -> str | None:
        with self._lock:
            if self._resolved:
                return self._agent_id
            self._resolved = True
        from plural.studio import slugify

        name = self._tracer.config.agent.name
        try:
            found = self._studio.agents.find(slugify(name, fallback="agent"))
        except Exception as exc:  # noqa: BLE001 - traces still go up without the link
            log.warning("Plural could not look up Agent %r: %s", name, exc)
            found = None
        if found is None:
            log.warning(
                "Agent %r is not registered in Plural, so its traces are not linked to it. "
                "Run `plural external register`.",
                name,
            )
        with self._lock:
            self._agent_id = str(found["id"]) if found else None
            return self._agent_id


class _Background:
    """One daemon thread that sends traces and flushes runs on an interval.

    A run's newer write replaces its older pending one, so a slow API never
    backs up more than one write per run.
    """

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = weakref.ref(tracer)
        self._pending: dict[str, tuple[Run, Any]] = {}
        self._order: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._busy = 0
        self._thread: threading.Thread | None = None

    def submit(self, run: Run, send: Any) -> None:
        with self._lock:
            fresh = run.trace_id not in self._pending
            self._pending[run.trace_id] = (run, send)
            if fresh:
                self._busy += 1
                self._order.put(run.trace_id)
            self._start()

    def start(self) -> None:
        with self._lock:
            self._start()

    def _start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._loop, name="plural-external-traces", daemon=True
            )
            self._thread.start()

    def drain(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._lock:
            while self._busy:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._idle.wait(left)
        return True

    def _loop(self) -> None:
        while True:
            try:
                trace_id = self._order.get(timeout=1.0)
            except queue.Empty:
                trace_id = None
            tracer = self._tracer()
            if tracer is None:
                return
            if trace_id is None:
                tracer._tick()
                continue
            with self._lock:
                run, send = self._pending.pop(trace_id, (None, None))
            try:
                if send is not None:
                    send()
            except Exception as exc:  # noqa: BLE001 - never raise into the agent
                log.warning("Plural could not write trace %s: %s", trace_id, exc)
            finally:
                with self._lock:
                    self._busy -= 1
                    self._idle.notify_all()
            del run, tracer


class Tracer:
    """Traces an agent's runs, as ``plural-agent.yaml`` says.

    Args:
        config: The agent and tracing config.
        environ: Where the API key and overrides are read; defaults to
            ``os.environ``.
        studio: The Plural API client, for tests. Built from the API key when
            omitted.

    Raises:
        ConfigurationError: When production tracing is on and the API key's
            environment variable is not set.
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        environ: Mapping[str, str] | None = None,
        studio: Any = None,
    ) -> None:
        env = os.environ if environ is None else environ
        self.config = config.with_environment(env)
        self._background = _Background(self)
        self._runs: weakref.WeakSet[Run] = weakref.WeakSet()
        self._runs_lock = threading.Lock()
        tracing = self.config.tracing
        secrets = (
            env.get(self.config.plural.api_key, ""),
            env.get(KEY_VARIABLE, ""),
            env.get(self.config.agent.signing_key, ""),
        )
        self._secrets = tuple(value for value in secrets if len(value) >= 8)
        self._patterns = tuple(re.compile(pattern) for pattern in tracing.redact)
        self._production: _PluralSink | None = None
        if tracing.enabled and tracing.production:
            self._production = _PluralSink(self, studio or self.config.studio(env))
        self._episodes = _EpisodeSink(self)
        _LIVE.add(self)

    @classmethod
    def from_config(
        cls, path: str | None = None, *, environ: Mapping[str, str] | None = None
    ) -> Tracer:
        """A tracer for ``plural-agent.yaml``, or the file ``PLURAL_AGENT_CONFIG`` names.

        Returns:
            The tracer.
        """
        return cls(AgentConfig.load(path, environ=environ), environ=environ)

    @classmethod
    def for_agent(
        cls, name: str, version: str, *, model: str = "", environ: Mapping[str, str] | None = None
    ) -> Tracer:
        """A tracer with default settings and no config file.

        Returns:
            The tracer.
        """
        agent = AgentSection(name=name, version=version, model=model)
        return cls(AgentConfig(agent=agent), environ=environ)

    def run(
        self,
        *,
        input: str | None = None,  # noqa: A002 - the run's input, as frameworks call it
        trace_id: str | None = None,
        flush: FlushPolicy | str | Mapping[str, Any] | None = None,
        capture: Capture | Mapping[str, bool] | None = None,
        tags: Mapping[str, str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Run:
        """Start a run. Inside a traced episode it is that episode's run.

        Args:
            input: The request the agent is working on, recorded as a user message.
            trace_id: The trace's id; a new one when omitted.
            flush: When to write the trace, overriding the config for this run.
            capture: Which optional fields to keep, overriding the config.
            tags: Labels for this run, added to the config's.
            metadata: Values to attach to the trace.

        Returns:
            The run; use it as a context manager.
        """
        active = current_run()
        if active is not None and active.kind == "episode" and not active.finished:
            if input:
                active.user(input)
            if metadata:
                active.metadata(**metadata)
            return active
        tracing = self.config.tracing
        keep = (
            tracing.enabled
            and self._production is not None
            and random.random() < tracing.sample_rate  # noqa: S311 - sampling, not security
        )
        run = Run(
            self,
            self._production if keep else None,
            trace_id=trace_id or os.urandom(16).hex(),
            kind="production",
            flush=FlushPolicy.parse(flush) if flush is not None else tracing.flush,
            capture=_capture(tracing.capture, capture),
            tags={**tracing.tags, **(tags or {})},
            metadata=metadata,
        )
        self._track(run)
        if input:
            run.user(input)
        return run

    def episode(
        self,
        episode: Episode,
        *,
        flush: FlushPolicy | str | Mapping[str, Any] | None = None,
        capture: Capture | Mapping[str, bool] | None = None,
    ) -> Run:
        """The run for one episode of a Plural Job. Its trace goes to that Job.

        The Task's instructions are recorded as the first user message, and
        :meth:`Run.finish` also finishes the episode.

        Returns:
            The run; use it as a context manager.
        """
        tracing = self.config.tracing
        run = Run(
            self,
            self._episodes if tracing.enabled else None,
            trace_id=episode.start.episode_id,
            kind="episode",
            flush=FlushPolicy.parse(flush) if flush is not None else tracing.flush,
            capture=_capture(tracing.capture, capture),
            tags=tracing.tags,
            episode=episode,
        )
        self._track(run)
        if episode.task.instructions:
            run.user(episode.task.instructions)
        return run

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until every pending trace is written.

        Returns:
            Whether everything was written within ``timeout`` seconds.
        """
        return self._background.drain(timeout)

    def _track(self, run: Run) -> None:
        if run.flush_policy.mode != "interval" or not run.recording:
            return
        with self._runs_lock:
            self._runs.add(run)
        self._background.start()

    def _forget(self, run: Run) -> None:
        with self._runs_lock:
            self._runs.discard(run)

    def _tick(self) -> None:
        now = time.monotonic()
        with self._runs_lock:
            due = [run for run in self._runs if not run.finished and run._due(now)]
        for run in due:
            run._write(final=False)

    def _render(self, run: Run, shape: Literal["atif", "trace"]) -> dict[str, Any]:
        records, metadata = run.snapshot()
        limit = self.config.tracing.max_trace_bytes
        kept = len(records)
        document = self._shape(run, records, metadata, shape, dropped=0)
        if len(json.dumps(document, default=str)) > limit:
            low, high = 0, len(records)
            while low < high:
                middle = (low + high + 1) // 2
                candidate = self._shape(run, records[:middle], metadata, shape, dropped=0)
                if len(json.dumps(candidate, default=str)) <= limit:
                    low = middle
                else:
                    high = middle - 1
            kept = low
            document = self._shape(
                run, records[:kept], metadata, shape, dropped=len(records) - kept
            )
        return document

    def _shape(
        self,
        run: Run,
        records: Sequence[_Record],
        metadata: Mapping[str, Any],
        shape: Literal["atif", "trace"],
        *,
        dropped: int,
    ) -> dict[str, Any]:
        capture = run.capture
        details: dict[str, Any] = {
            "status": run.status,
            "started_at": _iso(run.started_at),
            "ended_at": _iso(run.ended_at) if run.ended_at else None,
            "error": run.error,
            "tags": run.tags,
        }
        if capture.metadata and metadata:
            details["metadata"] = _jsonable(metadata)
        if dropped:
            details["dropped_steps"] = dropped
        if shape == "atif":
            document = _atif(self.config.agent, run, records, capture, details)
        else:
            document = _trace(self.config.agent, run, records, capture, details)
        redacted: dict[str, Any] = self._redact(document)
        return redacted

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, _REDACTED)
            for pattern in self._patterns:
                value = pattern.sub(_REDACTED, value)
            return value
        if isinstance(value, Mapping):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact(item) for item in value]
        return value


_DEFAULT: Tracer | None = None
_DEFAULT_LOCK = threading.Lock()
_LIVE: weakref.WeakSet[Tracer] = weakref.WeakSet()
_EXIT_FLUSH_SECONDS = 5.0


@atexit.register
def _flush_at_exit() -> None:
    # Traces go out on a daemon thread, which would die with a script that never flushed.
    for item in list(_LIVE):
        item.flush(_EXIT_FLUSH_SECONDS)


def tracer() -> Tracer:
    """The process's tracer: the one :func:`set_tracer` gave, or one for ``plural-agent.yaml``.

    Returns:
        The tracer.
    """
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = Tracer.from_config()
        return _DEFAULT


def set_tracer(value: Tracer | None) -> None:
    """Use ``value`` wherever no tracer is passed, such as in adapters."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = value


@contextlib.contextmanager
def episode_run(episode: Episode, tracer_: Tracer | None = None) -> Iterator[Run]:
    """Trace one episode with the process's tracer; a shortcut for :meth:`Tracer.episode`.

    Yields:
        The episode's run.
    """
    with (tracer_ or tracer()).episode(episode) as run:
        yield run


def _capture(base: Capture, override: Capture | Mapping[str, bool] | None) -> Capture:
    if override is None:
        return base
    if isinstance(override, Capture):
        return override
    return Capture.model_validate({**base.model_dump(), **dict(override)})


def _tool_call(value: ToolCall | Mapping[str, Any], index: int) -> ToolCall:
    if isinstance(value, ToolCall):
        return value
    function = value.get("function") if isinstance(value.get("function"), Mapping) else None
    name = (function or value).get("name") or ""
    arguments = (function or value).get("arguments")
    return ToolCall(
        id=str(value.get("id") or value.get("tool_call_id") or f"call-{index}"),
        name=str(name),
        arguments=_arguments(arguments),
    )


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"input": raw}
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    return {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [
            str(item.get("text"))
            for item in value
            if isinstance(item, Mapping) and item.get("text") is not None
        ]
        if parts:
            return "\n".join(parts)
    return json.dumps(_jsonable(value), sort_keys=True)


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


def _metrics(record: _Record) -> dict[str, Any]:
    usage = dict(record.usage or {})
    metrics = {
        key: usage.get(key)
        for key in ("prompt_tokens", "completion_tokens", "cached_tokens", "cost_usd")
        if isinstance(usage.get(key), (int, float))
    }
    if record.latency_ms is not None:
        metrics["extra"] = {"duration_ms": record.latency_ms}
    return metrics


def _incoming(records: Sequence[_Record]) -> list[_Record]:
    """Records with each model call's new system and user messages pulled out as steps.

    Frameworks send a model the whole conversation each time; only the messages
    not already recorded become steps.

    Returns:
        The records, with those messages before the call that first sent them,
        and a system prompt seen before any agent step first of all.
    """
    out: list[_Record] = []
    seen: set[tuple[str, str]] = {
        (record.kind, record.text) for record in records if record.kind in {"system", "user"}
    }
    for record in records:
        if record.kind == "llm":
            for message in record.messages:
                role = message.get("role")
                if role not in {"user", "system", "developer"}:
                    continue
                kind: Literal["user", "system"] = "user" if role == "user" else "system"
                text = _text(message.get("content"))
                if (kind, text) in seen or not text:
                    continue
                seen.add((kind, text))
                pulled = _Record(kind=kind, at=record.at, text=text)
                opening = all(item.kind in {"system", "user"} for item in out)
                if kind == "system" and opening:
                    out.insert(sum(1 for item in out if item.kind == "system"), pulled)
                else:
                    out.append(pulled)
        out.append(record)
    return out


def _atif(
    agent: AgentSection,
    run: Run,
    records: Sequence[_Record],
    capture: Capture,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    open_calls: list[tuple[dict[str, Any], ToolCall]] = []

    def add(step: dict[str, Any]) -> dict[str, Any]:
        step["step_id"] = len(steps) + 1
        steps.append(step)
        return step

    for record in _incoming(records):
        moment = _iso(record.at)
        if record.kind in {"system", "user"}:
            keep = capture.system_prompt if record.kind == "system" else capture.messages
            text = record.text if keep else ""
            add({"timestamp": moment, "source": record.kind, "message": text})
        elif record.kind == "agent":
            add(
                {
                    "timestamp": moment,
                    "source": "agent",
                    "message": record.text if capture.messages else "",
                    "llm_call_count": 0,
                }
            )
        elif record.kind == "llm":
            step: dict[str, Any] = {
                "timestamp": moment,
                "source": "agent",
                "message": record.text if capture.messages else "",
                "llm_call_count": 1,
            }
            model = record.model or agent.model
            if model:
                step["model_name"] = model
            if record.reasoning and capture.reasoning:
                step["reasoning_content"] = record.reasoning
            if record.tool_calls:
                step["tool_calls"] = [
                    {
                        "tool_call_id": call.id,
                        "function_name": call.name,
                        "arguments": _jsonable(dict(call.arguments))
                        if capture.tool_arguments
                        else {},
                    }
                    for call in record.tool_calls
                ]
            metrics = _metrics(record) if capture.usage else {}
            if metrics:
                step["metrics"] = metrics
            if record.error:
                step["extra"] = {"error": record.error}
            added = add(step)
            open_calls.extend((added, call) for call in record.tool_calls)
        else:
            owner, call_id = _owner(open_calls, record)
            if owner is None:
                call_id = record.call_id or f"tool-{len(steps) + 1}"
                owner = add(
                    {
                        "timestamp": moment,
                        "source": "agent",
                        "message": "",
                        "llm_call_count": 0,
                        "tool_calls": [
                            {
                                "tool_call_id": call_id,
                                "function_name": record.name,
                                "arguments": _jsonable(dict(record.arguments or {}))
                                if capture.tool_arguments
                                else {},
                            }
                        ],
                    }
                )
            content = record.result if record.error is None else {"error": record.error}
            result: dict[str, Any] = {
                "source_call_id": call_id,
                "content": _text(content) if capture.tool_results else "",
            }
            if record.latency_ms is not None:
                result["extra"] = {"duration_ms": record.latency_ms}
            owner.setdefault("observation", {"results": []})["results"].append(result)
    return {
        "schema_version": ATIF_VERSION,
        "session_id": run.trace_id,
        "agent": {
            "name": agent.name,
            "version": agent.version,
            **({"model_name": agent.model} if agent.model else {}),
        },
        "steps": steps,
        "final_metrics": final_metrics(steps),
        "extra": {key: value for key, value in details.items() if value not in (None, {})},
    }


def _owner(
    open_calls: list[tuple[dict[str, Any], ToolCall]], record: _Record
) -> tuple[dict[str, Any] | None, str | None]:
    for index, (step, call) in enumerate(open_calls):
        if (record.call_id and call.id == record.call_id) or (
            not record.call_id and call.name == record.name
        ):
            del open_calls[index]
            return step, call.id
    return None, None


def _trace(
    agent: AgentSection,
    run: Run,
    records: Sequence[_Record],
    capture: Capture,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    """Shape the run as a Plural ``Trace`` (schema 3.0.0), with model calls in the OpenAI shape.

    Returns:
        The Trace payload.
    """
    steps: list[dict[str, Any]] = []
    for record in records:
        if record.kind == "llm":
            messages = [
                _message(item, capture)
                for item in record.messages
                if item.get("role") not in {"system", "developer"} or capture.system_prompt
            ]
            reply: dict[str, Any] = {
                "role": "assistant",
                "content": (record.text if capture.messages else "") or None,
            }
            if record.tool_calls:
                reply["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(
                                _jsonable(dict(call.arguments)) if capture.tool_arguments else {}
                            ),
                        },
                    }
                    for call in record.tool_calls
                ]
            if record.reasoning and capture.reasoning:
                reply["reasoning"] = record.reasoning
            usage = dict(record.usage or {}) if capture.usage else {}
            steps.append(
                {
                    "type": "llm",
                    "model": record.model or agent.model or None,
                    "request": {"model": record.model or agent.model, "messages": messages},
                    "response": {"choices": [{"message": reply}]},
                    "usage": _usage(usage) if usage else None,
                    "cost": usage.get("cost_usd"),
                    "latency_ms": record.latency_ms if capture.usage else None,
                    "error": record.error,
                }
            )
        elif record.kind == "tool":
            steps.append(
                {
                    "type": "action",
                    "name": record.name,
                    "tool_call_id": record.call_id,
                    "source": "harness",
                    "arguments": _jsonable(dict(record.arguments or {}))
                    if capture.tool_arguments
                    else {},
                    "result": _jsonable(record.result) if capture.tool_results else None,
                    "error": record.error,
                    "latency_ms": record.latency_ms,
                    "started_at": _iso(record.at),
                }
            )
        else:
            keep = capture.system_prompt if record.kind == "system" else capture.messages
            steps.append(
                {
                    "type": "event",
                    "name": f"{record.kind}.message",
                    "data": {"text": record.text if keep else ""},
                }
            )
    usage_steps = [step for step in steps if step["type"] == "llm"]
    metrics: dict[str, Any] = {
        "llm_calls": len(usage_steps),
        "tool_calls": sum(1 for step in steps if step["type"] == "action"),
    }
    costs = [step["cost"] for step in usage_steps if isinstance(step.get("cost"), (int, float))]
    if costs:
        metrics["cost_usd"] = sum(costs)
    if run.ended_at is not None:
        metrics["latency_ms"] = (run.ended_at - run.started_at).total_seconds() * 1000
    answer = (
        {"answer": _jsonable(run.answer)} if run.answer is not None and capture.messages else {}
    )
    return {
        "trace_id": run.trace_id,
        "trace_kind": "production",
        "model": agent.model or None,
        "harness": "external",
        "steps": steps,
        "metrics": metrics,
        "failed": run.status == "failed",
        "tags": {
            **{key: str(value) for key, value in details.get("tags", {}).items()},
            "agent": agent.name,
            "agent_version": agent.version,
            "source": "plural-external",
        },
        "metadata": {
            **{key: value for key, value in details.items() if key != "tags" and value is not None},
            **answer,
        },
        "created_at": _iso(run.started_at),
        "schema_version": "3.0.0",
    }


def _usage(usage: Mapping[str, Any]) -> dict[str, Any]:
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    out: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cost": usage.get("cost_usd"),
    }
    if isinstance(usage.get("cached_tokens"), int):
        out["cache_read_tokens"] = usage["cached_tokens"]
    return out


def _message(message: Mapping[str, Any], capture: Capture) -> dict[str, Any]:
    out = {key: _jsonable(value) for key, value in message.items()}
    role = out.get("role")
    kept = {
        "tool": capture.tool_results,
        "system": capture.system_prompt,
        "developer": capture.system_prompt,
        "user": capture.messages,
        "assistant": capture.messages,
    }
    if not kept.get(str(role), True):
        out["content"] = ""
    if not capture.tool_arguments:
        for call in out.get("tool_calls") or []:
            if isinstance(call, dict) and isinstance(call.get("function"), dict):
                call["function"]["arguments"] = "{}"
    return out


__all__ = [
    "Run",
    "ToolCall",
    "Tracer",
    "current_run",
    "episode_run",
    "set_tracer",
    "tracer",
]
