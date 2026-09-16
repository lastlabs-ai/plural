"""Canonical Trace schema shared by production traffic and environments.

Examples:
    >>> from plural.tracing.schema import Trace, Outcome
    >>> t = Trace(trace_id="abc", outcome=Outcome(reward=1.0))
    >>> t.outcome.reward
    1.0
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from plural.types import ChatRequest, ChatResponse, Usage

TraceKind = Literal["production", "episode", "llm_call"]


def new_trace_id() -> str:
    """Generate a new opaque trace id.

    Returns:
        A UUID4 hex string.

    Examples:
        >>> len(new_trace_id()) == 32
        True
    """
    return uuid.uuid4().hex


class TraceContext(BaseModel):
    """Lineage supplied by a caller when creating a child trace."""

    parent_trace_id: str | None = None
    episode_trace_id: str | None = None


class Attempt(BaseModel):
    """A single provider attempt within an LLM call.

    Attributes:
        model: Model id attempted.
        provider: Provider slug.
        error: Error message if failed.
        latency_ms: Attempt latency.
        status_code: HTTP status code if available.
    """

    model: str
    provider: str
    error: str | None = None
    latency_ms: float | None = None
    status_code: int | None = None


class LLMCall(BaseModel):
    """An LLM invocation step.

    Attributes:
        type: Discriminator; always ``"llm"``.
        request: The chat request (may be redacted).
        response: The chat response (may be redacted).
        provider: Winning provider slug.
        model: Winning model id.
        usage: Token usage.
        cost: USD cost when known.
        latency_ms: End-to-end latency.
        attempts: All attempts including retries and fallbacks.
        error: Top-level error if the call ultimately failed.
    """

    type: Literal["llm"] = "llm"
    request: ChatRequest | dict[str, Any] | None = None
    response: ChatResponse | dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None
    usage: Usage | None = None
    cost: float | None = None
    latency_ms: float | None = None
    attempts: list[Attempt] = Field(default_factory=list)
    error: str | None = None


ActionSource = Literal["environment_native", "harness", "model_text"]


class ReasoningBlock(BaseModel):
    """One chain-of-thought or assistant text block from a turn."""

    kind: Literal["thinking", "text", "redacted"]
    text: str
    signature: str | None = None


class CapabilityDenial(BaseModel):
    """A capability the environment or policy removed during a trial."""

    capability: str
    layer: str
    reason: str


class ActionStep(BaseModel):
    """One action invocation and the observation it returned."""

    type: Literal["action"] = "action"
    action_id: str | None = None
    tool_call_id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    source: ActionSource = "environment_native"
    observation: Any = None
    result: Any = None
    error: str | None = None
    latency_ms: float | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    parent: str | None = None
    children: list[ActionStep] = Field(default_factory=list)


class Event(BaseModel):
    """A free-form event step.

    Attributes:
        type: Discriminator; always ``"event"``.
        name: Event name.
        data: Arbitrary event payload.
    """

    type: Literal["event"] = "event"
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class ParsedAction(BaseModel):
    """A structured action the policy chose this turn."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    source: ActionSource = "environment_native"
    action_id: str | None = None


class RewardEvent(BaseModel):
    """A dense reward attached to one turn."""

    name: str
    value: float
    reason: str | None = None


class Turn(BaseModel):
    """One model turn inside an episode: observation → action → observation."""

    type: Literal["turn"] = "turn"
    turn_id: str = Field(default_factory=new_trace_id)
    turn: int | None = None
    observation: Any = None
    model_context: ChatRequest | dict[str, Any] | None = None
    model_output: ChatResponse | dict[str, Any] | None = None
    reasoning: list[ReasoningBlock] = Field(default_factory=list)
    parsed_action: list[ParsedAction] = Field(default_factory=list)
    actions: list[ActionStep] = Field(default_factory=list)
    reward_events: list[RewardEvent] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Transition(BaseModel):
    """Gymnasium-style ``(obs, action, reward, next_obs, done)`` tuple.

    Produced by :meth:`Trace.transitions` for a future trainer.

    Attributes:
        observation: Observation at the start of the decision.
        action: Parsed actions taken.
        reward: Sum of this decision's ``reward_events``.
        next_observation: Observation after the decision (or final state).
        terminated: Whether the episode ended naturally on this step.
        truncated: Whether the episode was cut off on this step.
    """

    observation: Any = None
    action: list[ParsedAction] = Field(default_factory=list)
    reward: float = 0.0
    next_observation: Any = None
    terminated: bool = False
    truncated: bool = False


Step = Annotated[
    LLMCall | ActionStep | Event | Turn,
    Field(discriminator="type"),
]


class Outcome(BaseModel):
    """Labeled outcome attached to a trace.

    Attributes:
        scores: Named Verifier outputs.
        reward: Scalar reward used for RL / ranking.
        labels: Discrete labels (e.g. intent, success/fail).
        feedback: Free-form human or automated feedback.
    """

    scores: dict[str, float] = Field(default_factory=dict)
    reward: float | None = None
    labels: dict[str, Any] = Field(default_factory=dict)
    feedback: str | None = None


class TraceArtifactReference(BaseModel):
    """Hashed external artifact referenced by a semantic Trace."""

    name: str
    digest: str
    media_type: str
    size_bytes: int = Field(ge=0)


class TraceVerifierResult(BaseModel):
    """Final Verifier or pending human-review state."""

    name: str
    digest: str
    kind: Literal["deterministic", "agent", "human"]
    status: Literal["succeeded", "failed", "awaiting_review"]
    reward: float | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    feedback: str = ""


class Trace(BaseModel):
    """A complete record of an LLM interaction or environment rollout.

    Production traffic and environment rollouts emit the same shape so that
    datasets, benchmarks, and a future autorouter can consume either source.

    Attributes:
        trace_id: Opaque unique id.
        environment: Environment name when produced by a rollout.
        environment_version: Environment version string.
        environment_fingerprint: Hash of the Environment revision.
        task_id: Task identity for this Trial.
        model: Policy / model id used for this episode.
        initial_state: Explicitly safe Environment snapshot at reset.
        steps: Ordered steps (decisions, LLM calls, tool calls, events).
        final_state: Explicitly safe Environment snapshot at episode close.
        outcome: Optional labeled outcome. ``outcome.reward`` is the return.
        metrics: Episode aggregates (turns, cost, latency, tool counts).
        terminated: Natural end (``env.done()``).
        truncated: Cut off by ``max_turns``.
        tags: Free-form tags for filtering.
        metadata: Arbitrary metadata.
        created_at: Creation timestamp (UTC).
        schema_version: Trace schema version for stability.

    Examples:
        >>> t = Trace(trace_id="t1", tags={"env": "prod"})
        >>> t.schema_version
        '3.0.0'
    """

    trace_id: str = Field(default_factory=new_trace_id)
    trace_kind: TraceKind = "production"
    parent_trace_id: str | None = None
    episode_trace_id: str | None = None
    stop_reason: str | None = None
    environment: str | None = None
    environment_version: str | None = None
    environment_fingerprint: str | None = None
    task_id: str | None = None
    model: str | None = None
    harness: str | None = None
    harness_implementation: Literal["declared", "runnable"] | None = None
    granted_capabilities: tuple[str, ...] = ()
    denied_capabilities: tuple[str, ...] = ()
    capability_denials: tuple[CapabilityDenial, ...] = ()
    task_revision_digest: str | None = None
    environment_revision_digest: str | None = None
    verifier_revision_digests: tuple[str, ...] = ()
    agent_revision_digest: str | None = None
    harness_revision_digest: str | None = None
    job_id: str | None = None
    trial_id: str | None = None
    job_mode: Literal["eval", "train"] | None = None
    initial_state: dict[str, Any] | None = None
    steps: list[Step] = Field(default_factory=list)
    final_state: dict[str, Any] | None = None
    outcome: Outcome | None = None
    verifier_results: list[TraceVerifierResult] = Field(default_factory=list)
    artifacts: list[TraceArtifactReference] = Field(default_factory=list)
    tito_artifact: TraceArtifactReference | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    terminated: bool | None = None
    truncated: bool | None = None
    failed: bool = False
    tags: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: Literal["3.0.0"] = "3.0.0"

    def add_llm(
        self,
        *,
        request: ChatRequest | dict[str, Any] | None,
        response: ChatResponse | None,
        attempts: list[Attempt] | None = None,
        error: str | None = None,
    ) -> LLMCall:
        """Append an LLM call step.

        Args:
            request: Chat request.
            response: Chat response if successful.
            attempts: Attempt records.
            error: Error message if failed.

        Returns:
            The appended :class:`LLMCall`.
        """
        step = LLMCall(
            request=request,
            response=response,
            provider=response.provider if response else None,
            model=response.model
            if response
            else (request.model if isinstance(request, ChatRequest) else None),
            usage=response.usage if response else None,
            cost=response.usage.cost if response else None,
            latency_ms=response.latency_ms if response else None,
            attempts=attempts or [],
            error=error,
        )
        self.steps.append(step)
        return step

    def add_action(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        action_id: str | None = None,
        tool_call_id: str | None = None,
        source: ActionSource = "environment_native",
        observation: Any = None,
        result: Any = None,
        error: str | None = None,
        latency_ms: float | None = None,
    ) -> ActionStep:
        """Append an action step."""  # noqa: DOC201
        step = ActionStep(
            name=name,
            arguments=arguments,
            action_id=action_id,
            tool_call_id=tool_call_id,
            source=source,
            observation=observation if observation is not None else result,
            result=result,
            error=error,
            latency_ms=latency_ms,
        )
        self.steps.append(step)
        return step

    def add_turn(
        self,
        *,
        observation: Any = None,
        model_context: ChatRequest | dict[str, Any] | None = None,
        model_output: ChatResponse | None = None,
        parsed_action: list[ParsedAction] | None = None,
        actions: list[ActionStep] | None = None,
        reward_events: list[RewardEvent] | None = None,
        reasoning: list[ReasoningBlock] | None = None,
        turn: int | None = None,
    ) -> Turn:
        """Append a turn step for one model turn."""  # noqa: DOC201
        now = datetime.now(timezone.utc)
        step = Turn(
            turn=turn,
            observation=observation,
            model_context=model_context,
            model_output=model_output,
            reasoning=reasoning or [],
            parsed_action=parsed_action or [],
            actions=actions or [],
            reward_events=reward_events or [],
            started_at=now,
            ended_at=now,
            timestamp=now,
        )
        self.steps.append(step)
        return step

    def transitions(
        self,
        *,
        source: Literal["outcome", "events", "both"] = "outcome",
    ) -> list[Transition]:
        """Flatten this episode into step-by-step transitions.

        Prefers :class:`Turn` steps. Falls back to grouping flat
        ``llm`` / ``action`` steps so production traces still export.

        Args:
            source: Reward source, matching :meth:`turn_rewards`.

        Returns:
            One :class:`Transition` per turn.
        """
        turns = self.turns()
        if turns:
            return self._transitions_from_turns(turns, source=source)
        return self._transitions_from_flat_steps(source=source)

    def turns(self) -> list[Turn]:
        """Return turn steps in order."""
        return [s for s in self.steps if isinstance(s, Turn)]

    def credit(
        self,
        value: float,
        *,
        name: str = "late",
        reason: str | None = None,
        turn_index: int | None = None,
    ) -> RewardEvent | Outcome:
        """Inject reward after the fact — episode-wide or onto one turn.

        Use this when the signal arrives late (likes, a human review, a
        downstream KPI). Credit assignment across earlier actions is
        :meth:`returns`, not the environment's job.

        Args:
            value: Reward to add.
            name: Reward source (``"likes"``, ``"review"``, …).
            reason: Optional human-readable reason.
            turn_index: Which turn to attribute to. ``None`` updates
                ``outcome.reward`` (and ``outcome.scores[name]``). Negative
                indices count from the end.

        Returns:
            The new :class:`RewardEvent` or the updated :class:`Outcome`.

        Raises:
            IndexError: If ``turn_index`` is out of range.
        """
        if turn_index is None:
            current = self.outcome or Outcome()
            current.scores[name] = current.scores.get(name, 0.0) + float(value)
            current.reward = (current.reward or 0.0) + float(value)
            self.outcome = current
            return current
        turns = self.turns()
        if not turns:
            raise IndexError("trace has no turn steps to credit")
        index = turn_index if turn_index >= 0 else len(turns) + turn_index
        if index < 0 or index >= len(turns):
            raise IndexError(f"turn_index {turn_index} out of range")
        event = RewardEvent(name=name, value=float(value), reason=reason)
        turns[index].reward_events.append(event)
        return event

    def turn_rewards(
        self,
        *,
        source: Literal["outcome", "events", "both"] = "outcome",
    ) -> list[float]:
        """Per-turn reward used as ``r_t`` before discounting."""  # noqa: DOC201
        turns = self.turns()
        if not turns:
            return []
        rewards = [sum(event.value for event in item.reward_events) for item in turns]
        terminal = self.outcome.reward if self.outcome and self.outcome.reward is not None else None
        if source == "events":
            return rewards
        if source == "outcome":
            out = [0.0] * len(turns)
            if terminal is not None:
                out[-1] = float(terminal)
            return out
        if terminal is not None:
            rewards[-1] += float(terminal)
        return rewards

    def returns(
        self,
        gamma: float = 1.0,
        *,
        source: Literal["outcome", "events", "both"] = "outcome",
    ) -> list[float]:
        """Discounted return ``G_t = r_t + γ G_{t+1}`` for each decision.

        This is how a trainer gives the *research* action credit for a later
        post's likes: the environment does not rewrite history; the trainer
        walks the episode backward.

        Args:
            gamma: Discount factor in ``[0, 1]``.
            source: See :meth:`turn_rewards`.

        Returns:
            One return per turn, same order as :meth:`turns`.

        Examples:
            >>> t = Trace(outcome=Outcome(reward=1.0))
            >>> t.add_turn(parsed_action=[ParsedAction(name="search")])
            >>> t.add_turn(parsed_action=[ParsedAction(name="answer")])
            >>> t.returns(gamma=0.9)
            [0.9, 1.0]
        """
        rewards = self.turn_rewards(source=source)
        out = [0.0] * len(rewards)
        running = 0.0
        for i in range(len(rewards) - 1, -1, -1):
            running = rewards[i] + gamma * running
            out[i] = running
        return out

    def _transitions_from_turns(
        self,
        turns: list[Turn],
        *,
        source: Literal["outcome", "events", "both"],
    ) -> list[Transition]:
        out: list[Transition] = []
        rewards = self.turn_rewards(source=source)
        for i, turn in enumerate(turns):
            is_last = i == len(turns) - 1
            next_obs = turns[i + 1].observation if not is_last else self.final_state
            out.append(
                Transition(
                    observation=turn.observation,
                    action=list(turn.parsed_action),
                    reward=rewards[i],
                    next_observation=next_obs,
                    terminated=bool(self.terminated) if is_last else False,
                    truncated=bool(self.truncated) if is_last else False,
                )
            )
        return out

    def _transitions_from_flat_steps(
        self,
        *,
        source: Literal["outcome", "events", "both"],
    ) -> list[Transition]:
        groups: list[tuple[Any, list[ParsedAction]]] = []
        current_obs: Any = self.initial_state
        pending_actions: list[ParsedAction] = []
        started = False

        def flush() -> None:
            if not started:
                return
            groups.append((current_obs, list(pending_actions)))

        for step in self.steps:
            if isinstance(step, LLMCall):
                if started:
                    flush()
                    pending_actions = []
                started = True
                if isinstance(step.request, ChatRequest) and step.request.messages:
                    current_obs = step.request.messages[-1].content
                elif isinstance(step.request, dict):
                    msgs = step.request.get("messages") or []
                    if msgs:
                        current_obs = msgs[-1].get("content")
            elif isinstance(step, ActionStep):
                started = True
                pending_actions.append(ParsedAction(name=step.name, arguments=step.arguments))
        if started:
            flush()

        out: list[Transition] = []
        for i, (obs, actions) in enumerate(groups):
            is_last = i == len(groups) - 1
            next_obs = groups[i + 1][0] if not is_last else self.final_state
            reward = 0.0
            if (
                source in {"outcome", "both"}
                and is_last
                and self.outcome
                and self.outcome.reward is not None
            ):
                reward = float(self.outcome.reward)
            out.append(
                Transition(
                    observation=obs,
                    action=actions,
                    reward=reward,
                    next_observation=next_obs,
                    terminated=bool(self.terminated) if is_last else False,
                    truncated=bool(self.truncated) if is_last else False,
                )
            )
        return out

    def label(
        self,
        *,
        scores: dict[str, float] | None = None,
        reward: float | None = None,
        labels: dict[str, Any] | None = None,
        feedback: str | None = None,
    ) -> Outcome:
        """Attach or update the outcome.

        Args:
            scores: Named Verifier outputs.
            reward: Scalar reward.
            labels: Discrete labels.
            feedback: Free-form feedback.

        Returns:
            The updated :class:`Outcome`.
        """
        current = self.outcome or Outcome()
        if scores:
            current.scores.update(scores)
        if reward is not None:
            current.reward = reward
        if labels:
            current.labels.update(labels)
        if feedback is not None:
            current.feedback = feedback
        self.outcome = current
        return current
