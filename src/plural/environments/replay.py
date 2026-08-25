"""Deterministically replay and verify recorded environment actions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from plural.environments.env import Environment
from plural.environments.rollout import Rollout
from plural.environments.runtime import LocalRuntime, Runtime
from plural.environments.stop import is_stopped
from plural.environments.task import TaskData
from plural.environments.types import serialize_observation
from plural.tracing.schema import ToolCallStep, Trace


class ReplayMismatch(BaseModel):
    """One difference between a recorded trace and its replay."""

    kind: str
    message: str
    decision_index: int | None = None
    expected: Any = None
    actual: Any = None


class ReplayResult(BaseModel):
    """Structured result of replaying and comparing an episode."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rollout: Rollout | None = None
    mismatches: list[ReplayMismatch] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether replay matched every verified field."""
        return not self.mismatches

    @property
    def matched(self) -> bool:
        """Alias for :attr:`ok`."""
        return self.ok


def replay_actions(
    environment: Environment[Any, Any],
    trace: Trace,
    *,
    task: TaskData | None = None,
    runtime: Runtime | None = None,
    verify_fingerprint: bool = True,
) -> ReplayResult:
    """Replay recorded decision actions without calling a model.

    Args:
        environment: Fresh or closed environment instance to replay.
        trace: Episode trace containing recorded decisions.
        task: Explicit task, required when trace metadata cannot reconstruct it.
        runtime: Optional tool runtime.
        verify_fingerprint: Check the environment fingerprint before execution.

    Returns:
        Replay rollout and structured mismatches.

    Raises:
        ValueError: If no replay task can be reconstructed.
        RuntimeError: If replay execution itself fails.
    """
    redacted_fields = trace.metadata.get("redacted_fields")
    redaction = trace.metadata.get("redaction")
    if (isinstance(redacted_fields, list) and redacted_fields) or (
        isinstance(redaction, dict) and bool(redaction)
    ):
        first_field = (
            redacted_fields[0] if isinstance(redacted_fields, list) and redacted_fields else None
        )
        raise ValueError(
            "cannot deterministically replay a trace with redacted content; "
            f"redacted fields include {first_field!r}"
        )

    replay_task = task or _task_from_trace(trace)
    if replay_task is None:
        raise ValueError(
            "replay requires an explicit task or trace.metadata['task'] with task_id and input"
        )

    mismatches: list[ReplayMismatch] = []
    actual_fingerprint = environment.fingerprint()
    if verify_fingerprint and trace.environment_fingerprint != actual_fingerprint:
        mismatches.append(
            ReplayMismatch(
                kind="fingerprint",
                message="environment fingerprint does not match the recorded trace",
                expected=trace.environment_fingerprint,
                actual=actual_fingerprint,
            )
        )
        return ReplayResult(mismatches=mismatches)

    if runtime is None:
        runtime = LocalRuntime(environment.tool_functions)
    environment.reset(replay_task, model=trace.model)
    replay_episode = environment._require_episode(allow_stopped=True)
    _compare(
        mismatches,
        kind="initial_state",
        message="initial safe snapshot differs",
        expected=trace.initial_state,
        actual=replay_episode.trace.initial_state,
    )
    decisions = trace.decisions()
    expected_transitions = trace.transitions(source="events")

    for index, decision in enumerate(decisions):
        episode = environment._require_episode()
        _compare(
            mismatches,
            kind="observation",
            message="policy observation differs",
            expected=decision.observation,
            actual=serialize_observation(episode.observation),
            decision_index=index,
        )
        try:
            result = environment.step(list(decision.parsed_action), runtime=runtime)
        except Exception as exc:
            raise RuntimeError(f"replay execution failed at decision {index}: {exc}") from exc

        actual_decisions = environment._require_episode(allow_stopped=True).trace.decisions()
        if index >= len(actual_decisions):
            mismatches.append(
                ReplayMismatch(
                    kind="decision_count",
                    message="replay did not record the applied decision",
                    decision_index=index,
                    expected=index + 1,
                    actual=len(actual_decisions),
                )
            )
        else:
            actual_decision = actual_decisions[index]
            _compare(
                mismatches,
                kind="tool_calls",
                message="tool call results, errors, or children differ",
                expected=[_tool_result_payload(tool) for tool in decision.tool_calls],
                actual=[_tool_result_payload(tool) for tool in actual_decision.tool_calls],
                decision_index=index,
            )
            _compare(
                mismatches,
                kind="reward_events",
                message="reward events differ",
                expected=[event.model_dump(mode="json") for event in decision.reward_events],
                actual=[event.model_dump(mode="json") for event in actual_decision.reward_events],
                decision_index=index,
            )

        if index < len(expected_transitions):
            expected = expected_transitions[index]
            _compare(
                mismatches,
                kind="reward",
                message="step reward differs",
                expected=expected.reward,
                actual=result.reward,
                decision_index=index,
            )
            _compare(
                mismatches,
                kind="terminated",
                message="terminated flag differs",
                expected=expected.terminated,
                actual=result.terminated,
                decision_index=index,
            )
            _compare(
                mismatches,
                kind="truncated",
                message="truncated flag differs",
                expected=expected.truncated,
                actual=result.truncated,
                decision_index=index,
            )

        stopped = is_stopped(result.info.get("stop_reason"))
        if stopped and index + 1 < len(decisions):
            mismatches.append(
                ReplayMismatch(
                    kind="decision_count",
                    message="replay stopped before all recorded decisions were applied",
                    decision_index=index,
                    expected=len(decisions),
                    actual=index + 1,
                )
            )
            break

    rollout = environment.close_episode()
    _compare(
        mismatches,
        kind="final_state",
        message="final safe snapshot differs",
        expected=trace.final_state,
        actual=rollout.trace.final_state,
    )
    _compare(
        mismatches,
        kind="terminated",
        message="final terminated flag differs",
        expected=trace.terminated,
        actual=rollout.trace.terminated,
    )
    _compare(
        mismatches,
        kind="truncated",
        message="final truncated flag differs",
        expected=trace.truncated,
        actual=rollout.trace.truncated,
    )
    _compare(
        mismatches,
        kind="stop_reason",
        message="final stop reason differs",
        expected=trace.stop_reason,
        actual=rollout.trace.stop_reason,
    )
    _compare(
        mismatches,
        kind="failed",
        message="final failure flag differs",
        expected=trace.failed,
        actual=rollout.trace.failed,
    )
    expected_scores = trace.outcome.scores if trace.outcome is not None else None
    actual_scores = rollout.trace.outcome.scores if rollout.trace.outcome is not None else None
    _compare(
        mismatches,
        kind="outcome_scores",
        message="final outcome scores differ",
        expected=expected_scores,
        actual=actual_scores,
    )
    expected_reward = trace.outcome.reward if trace.outcome is not None else None
    actual_reward = rollout.trace.outcome.reward if rollout.trace.outcome is not None else None
    _compare(
        mismatches,
        kind="outcome_reward",
        message="final outcome reward differs",
        expected=expected_reward,
        actual=actual_reward,
    )
    return ReplayResult(rollout=rollout, mismatches=mismatches)


def verify_replay(
    environment: Environment[Any, Any],
    trace: Trace,
    *,
    task: TaskData | None = None,
    runtime: Runtime | None = None,
    verify_fingerprint: bool = True,
) -> ReplayResult:
    """Replay a trace and return all deterministic verification mismatches.

    Returns:
        Replay rollout and structured mismatches.
    """
    return replay_actions(
        environment,
        trace,
        task=task,
        runtime=runtime,
        verify_fingerprint=verify_fingerprint,
    )


def _task_from_trace(trace: Trace) -> TaskData | None:
    payload = trace.metadata.get("task")
    if isinstance(payload, TaskData):
        return payload
    if not isinstance(payload, dict):
        return None
    try:
        return TaskData.model_validate(payload)
    except (TypeError, ValueError):
        return None


def _compare(
    mismatches: list[ReplayMismatch],
    *,
    kind: str,
    message: str,
    expected: Any,
    actual: Any,
    decision_index: int | None = None,
) -> None:
    if expected != actual:
        mismatches.append(
            ReplayMismatch(
                kind=kind,
                message=message,
                decision_index=decision_index,
                expected=expected,
                actual=actual,
            )
        )


def _tool_result_payload(tool: ToolCallStep) -> dict[str, Any]:
    """Return deterministic tool execution fields, excluding timing and ids."""
    return {
        "name": tool.name,
        "result": tool.result,
        "error": tool.error,
        "children": [_tool_result_payload(child) for child in tool.children],
    }
