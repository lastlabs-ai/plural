from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from plural import ActionResult, PluralPolicy, Policy, Redactor, ScriptedPolicy, StopReason
from plural.environments import (
    Environment,
    EpisodeError,
    EpisodeState,
    Observation,
    ReplayResult,
    State,
    TaskData,
    is_text_action,
    is_tool_action,
    normalize_action,
    action,
    replay_actions,
    verify_replay,
)
from plural.environments.runtime import Runtime
from plural.tracing.schema import ActionStep, ParsedAction, RewardEvent
from plural.types import ChatResponse, Choice, Message


class AlphaState(State):
    count: int = 0
    target: int = 2


class AlphaObservation(Observation):
    count: int = 0

    def render(self) -> str:
        return f"count={self.count}"


class AlphaEnv(Environment[AlphaObservation, AlphaState]):
    name = "alpha-counter"
    version = "1.0.0"

    def setup(self, task: TaskData) -> None:
        super().setup(task)
        self.state = AlphaState(target=int(task.metadata.get("target", 2)))

    def observe(self) -> AlphaObservation:
        return AlphaObservation(count=self.state.count)

    def done(self) -> bool:
        return self.state.count >= self.state.target

    def snapshot(self) -> dict[str, Any]:
        return {"count": self.state.count, "target": self.state.target}

    def step_reward(self, tool_name: str, result: Any) -> float | None:
        del result
        return 0.5 if tool_name == "inc" else None

    @action
    def inc(self, by: int = 1) -> int:
        """Increment the counter."""
        self.state.count += by
        return self.state.count


def _task(*, target: int = 2, expected: Any = None) -> TaskData:
    return TaskData(
        task_id="alpha",
        input="count",
        expected=expected,
        metadata={"target": target},
    )


def _response(content: str) -> ChatResponse:
    return ChatResponse(
        id="response",
        model="scripted",
        choices=[Choice(message=Message(role="assistant", content=content))],
    )


def test_lifecycle_guards_and_reset_after_close() -> None:
    env = AlphaEnv()
    assert env.episode_state is EpisodeState.IDLE
    for operation in (env.messages, env.close_episode, lambda: env.step([])):
        with pytest.raises(EpisodeError) as exc_info:
            operation()
        assert exc_info.value.state is EpisodeState.IDLE

    env.reset(_task())
    assert env.episode_state is EpisodeState.OPEN
    with pytest.raises(EpisodeError) as exc_info:
        env.reset(_task())
    assert exc_info.value.state is EpisodeState.OPEN

    env.close_episode()
    assert env.episode_state is EpisodeState.CLOSED
    for operation in (env.messages, env.close_episode, lambda: env.step([])):
        with pytest.raises(EpisodeError) as exc_info:
            operation()
        assert exc_info.value.state is EpisodeState.CLOSED

    env.reset(_task())
    assert env.episode_state is EpisodeState.OPEN
    env.close_episode()


def test_step_override_is_rejected_at_class_definition() -> None:
    with pytest.raises(
        TypeError,
        match=r"Environment\.step\(\) is framework-owned; override apply_action\(\) instead",
    ):

        class CustomStep(Environment):
            def step(self, action: Any = None, **kwargs: Any) -> Any:
                del action, kwargs


def test_apply_action_runs_inside_framework_lifecycle_guards() -> None:
    class CustomAction(Environment):
        def __init__(self) -> None:
            super().__init__()
            self.applied: list[Any] = []

        def apply_action(
            self,
            action: Any,
            *,
            runtime: Runtime,
            response: ChatResponse | None = None,
        ) -> ActionResult:
            del runtime, response
            self.applied.append(action)
            return ActionResult(parsed_actions=[ParsedAction(name="custom")])

    env = CustomAction()
    with pytest.raises(EpisodeError) as exc_info:
        env.step("action")
    assert exc_info.value.state is EpisodeState.IDLE
    assert env.applied == []
    env.reset(_task())
    result = env.step("action")
    assert result.info["turn"] == 1
    assert env.applied == ["action"]
    env.close_episode()
    with pytest.raises(EpisodeError) as exc_info:
        env.step("action")
    assert exc_info.value.state is EpisodeState.CLOSED
    assert env.applied == ["action"]


def test_stop_reasons_and_gym_precedence() -> None:
    terminated_env = AlphaEnv()
    terminated_env.reset(_task(target=1))
    terminated = terminated_env.step(ParsedAction(name="inc", arguments={"by": 1}))
    assert terminated.terminated is True
    assert terminated.info["stop_reason"] == StopReason.TERMINATED.value
    assert terminated_env.episode_state is EpisodeState.STOPPED
    assert terminated_env.messages()
    for operation in (
        lambda: terminated_env.step(ParsedAction(name="inc")),
        terminated_env.finish_turn,
        lambda: terminated_env.reset(_task()),
    ):
        with pytest.raises(EpisodeError) as exc_info:
            operation()
        assert exc_info.value.state is EpisodeState.STOPPED
    assert terminated_env.close_episode().trace.stop_reason == "terminated"

    truncated_env = AlphaEnv(max_turns=1)
    truncated_env.reset(_task(target=2))
    truncated = truncated_env.step(ParsedAction(name="inc", arguments={"by": 1}))
    assert truncated.truncated is True
    assert truncated.info["stop_reason"] == StopReason.TRUNCATED.value
    assert truncated_env.close_episode().trace.stop_reason == "truncated"

    policy_env = AlphaEnv()
    policy_env.reset(_task())
    policy_stop = policy_env.step(_response("final answer"))
    assert policy_stop.terminated is False
    assert policy_stop.truncated is False
    assert policy_stop.info["stop_reason"] == StopReason.POLICY_STOP.value
    decision = policy_env.close_episode().trace.turns()[0]
    assert decision.parsed_action == [
        ParsedAction(name="respond", arguments={"text": "final answer"}, source="model_text")
    ]
    assert isinstance(decision.model_output, ChatResponse)
    assert decision.model_output.text == "final answer"

    failed_env = AlphaEnv()
    failed_env.reset(_task())
    failure = failed_env.finish_turn(stop_reason=StopReason.FAILURE)
    assert failure.info["stop_reason"] == StopReason.FAILURE.value
    assert failed_env.episode_state is EpisodeState.STOPPED
    failed_trace = failed_env.close_episode().trace
    assert failed_trace.stop_reason == "failure"
    assert failed_trace.failed is True


def test_explicit_failure_precedes_max_turn_truncation() -> None:
    env = AlphaEnv(max_turns=1)
    env.reset(_task(target=2))

    result = env.finish_turn(stop_reason=StopReason.FAILURE)
    trace = env.close_episode().trace

    assert result.truncated is True
    assert result.info["stop_reason"] == StopReason.FAILURE.value
    assert trace.truncated is True
    assert trace.stop_reason == StopReason.FAILURE.value
    assert trace.failed is True


def test_text_action_normalization_and_helpers() -> None:
    response = _response("hello")
    direct, direct_ids = normalize_action(response, None)
    fallback, fallback_ids = normalize_action(None, response)
    expected = ParsedAction(name="respond", arguments={"text": "hello"}, source="model_text")
    assert direct == fallback == [expected]
    assert direct_ids == fallback_ids == [None]
    assert is_text_action(expected)
    assert not is_tool_action(expected)
    assert is_tool_action(ParsedAction(name="inc"))


def test_scripted_policy_runs_without_client() -> None:
    env = AlphaEnv()
    policy = ScriptedPolicy(
        [
            ParsedAction(name="inc", arguments={"by": 1}),
            ParsedAction(name="inc", arguments={"by": 1}),
        ]
    )
    assert isinstance(policy, Policy)
    rollout = env.run_episode(_task(), policy, model="scripted")
    assert rollout.trace.terminated is True
    assert rollout.trace.stop_reason == "terminated"
    assert len(rollout.trace.turns()) == 2
    assert rollout.trace.turns()[0].model_context is not None
    with pytest.raises(RuntimeError, match="ScriptedPolicy exhausted"):
        policy.act(rollout.trace.turns()[0].model_context)


def test_text_only_policy_output_is_policy_stop() -> None:
    rollout = AlphaEnv().run_episode(_task(), ScriptedPolicy([_response("done")]))
    assert rollout.trace.stop_reason == "policy_stop"
    assert rollout.trace.terminated is False
    assert rollout.trace.truncated is False
    assert rollout.response is not None
    assert rollout.response.text == "done"


def test_plural_policy_uses_configured_model_when_trace_model_is_alias() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.models: list[str] = []

        def chat(self, **kwargs: Any) -> ChatResponse:
            self.models.append(str(kwargs["model"]))
            return _response("done")

    client = FakeClient()
    policy = PluralPolicy(client, "provider/actual")  # type: ignore[arg-type]
    rollout = AlphaEnv().run_episode(_task(), policy, model="benchmark-alias")

    assert client.models == ["provider/actual"]
    assert rollout.trace.model == "benchmark-alias"
    request = rollout.trace.turns()[0].model_context
    assert request is not None
    assert request.model == "provider/actual"


def test_custom_text_action_records_each_response_without_forced_policy_stop() -> None:
    class ContinuingTextEnv(AlphaEnv):
        def apply_action(
            self,
            action: Any,
            *,
            runtime: Runtime,
            response: ChatResponse | None = None,
        ) -> ActionResult:
            del runtime
            parsed, _ids = normalize_action(action, response)
            self.state.count += 1
            return ActionResult(parsed_actions=parsed)

    rollout = ContinuingTextEnv().run_episode(
        _task(target=2),
        ScriptedPolicy([_response("first"), _response("second")]),
    )

    assistants = [message.content for message in rollout.messages if message.role == "assistant"]
    assert assistants == ["first", "second"]
    assert len(rollout.trace.turns()) == 2
    assert rollout.trace.stop_reason == "terminated"


def test_action_result_fields_are_recorded_and_canonical_info_wins() -> None:
    class RichActionEnv(AlphaEnv):
        def apply_action(
            self,
            action: Any,
            *,
            runtime: Runtime,
            response: ChatResponse | None = None,
        ) -> ActionResult:
            del runtime, response
            self.state.count += 1
            return ActionResult(
                parsed_actions=[ParsedAction(name="scalar", arguments={"value": action})],
                actions=[ActionStep(name="virtual", result={"count": self.state.count})],
                reward_events=[RewardEvent(name="progress", value=1.25)],
                info={
                    "custom": "kept",
                    "turn": 999,
                    "stop_reason": "custom",
                    "tool_errors": ["custom"],
                },
            )

    env = RichActionEnv()
    env.reset(_task(target=3))
    result = env.step(7)

    assert result.reward == 1.25
    assert result.info == {
        "custom": "kept",
        "turn": 1,
        "stop_reason": None,
        "tool_errors": [],
    }
    assert env.messages()[-2].role == "tool"
    decision = env.episode_trace.turns()[0]  # type: ignore[union-attr]
    assert decision.parsed_action == [ParsedAction(name="scalar", arguments={"value": 7})]
    assert decision.reward_events == [RewardEvent(name="progress", value=1.25)]


def test_wrong_apply_action_return_type_fails_and_closes_episode() -> None:
    class WrongResultEnv(AlphaEnv):
        def apply_action(
            self,
            action: Any,
            *,
            runtime: Runtime,
            response: ChatResponse | None = None,
        ) -> Any:
            del action, runtime, response
            return {"parsed_actions": []}

    env = WrongResultEnv()
    env.reset(_task())
    with pytest.raises(TypeError, match=r"apply_action\(\) must return ActionResult"):
        env.step("invalid")

    assert env.episode_state is EpisodeState.CLOSED
    trace = env.episode_trace
    assert trace is not None
    assert trace.failed is True
    assert trace.stop_reason == StopReason.FAILURE.value


def test_default_apply_action_keeps_tool_dispatch_and_trace_behavior() -> None:
    env = AlphaEnv()
    env.reset(_task())

    result = env.step(ParsedAction(name="inc", arguments={"by": 1}))
    trace = env.episode_trace

    assert result.reward == 0.5
    assert env.state.count == 1
    assert any(message.role == "tool" and message.name == "inc" for message in env.messages())
    assert trace is not None
    decision = trace.turns()[0]
    assert decision.parsed_action == [ParsedAction(name="inc", arguments={"by": 1})]
    assert decision.actions[0].name == "inc"
    assert decision.reward_events == [RewardEvent(name="inc", value=0.5)]


def test_fingerprint_covers_max_turns_and_custom_hooks() -> None:
    base = AlphaEnv(max_turns=2)
    assert AlphaEnv(max_turns=3).fingerprint() != base.fingerprint()

    class CustomObserve(AlphaEnv):
        def observe(self) -> AlphaObservation:
            return AlphaObservation(count=self.state.count, metadata={"custom": True})

    class CustomApplyAction(AlphaEnv):
        def apply_action(
            self,
            action: Any,
            *,
            runtime: Runtime,
            response: ChatResponse | None = None,
        ) -> ActionResult:
            return super().apply_action(action, runtime=runtime, response=response)

    class CustomDone(AlphaEnv):
        def done(self) -> bool:
            return super().done()

    class CustomSnapshot(AlphaEnv):
        def snapshot(self) -> dict[str, Any]:
            return super().snapshot()

    fingerprints = {
        base.fingerprint(),
        CustomObserve(max_turns=2).fingerprint(),
        CustomApplyAction(max_turns=2).fingerprint(),
        CustomDone(max_turns=2).fingerprint(),
        CustomSnapshot(max_turns=2).fingerprint(),
    }
    assert len(fingerprints) == 5


def test_fingerprint_detects_same_named_callable_body_changes() -> None:
    first_namespace: dict[str, Any] = {"__name__": "same_module"}
    second_namespace: dict[str, Any] = {"__name__": "same_module"}
    exec("def implementation():\n    return 1\n", first_namespace)
    exec("def implementation():\n    return 2\n", second_namespace)

    first = Environment(name="same", version="1.0.0")
    second = Environment(name="same", version="1.0.0")
    first.action(first_namespace["implementation"], name="same_tool")
    second.action(second_namespace["implementation"], name="same_tool")

    assert first_namespace["implementation"].__qualname__ == "implementation"
    assert second_namespace["implementation"].__qualname__ == "implementation"
    assert first.fingerprint() != second.fingerprint()


def test_fingerprint_covers_callable_object_configuration() -> None:
    @dataclass
    class ThresholdScorer:
        threshold: float

        def __call__(self, rollout: Any) -> float:
            del rollout
            return float(self.threshold >= 0.5)

    first = Environment(name="configured-scorer")
    first.scorer(ThresholdScorer(0.25), name="threshold")
    second = Environment(name="configured-scorer")
    second.scorer(ThresholdScorer(0.75), name="threshold")

    assert first.fingerprint() != second.fingerprint()


def test_fingerprint_covers_private_and_slotted_callable_configuration() -> None:
    class PrivateThresholdScorer:
        def __init__(self, threshold: float) -> None:
            self._threshold = threshold

        def __call__(self, rollout: Any) -> float:
            del rollout
            return float(self._threshold >= 0.5)

    class SlottedThresholdScorer:
        __slots__ = ("threshold",)

        def __init__(self, threshold: float) -> None:
            self.threshold = threshold

        def __call__(self, rollout: Any) -> float:
            del rollout
            return float(self.threshold >= 0.5)

    def fingerprint(scorer: Any) -> str:
        env = Environment(name="configured-scorer")
        env.scorer(scorer, name="threshold")
        return env.fingerprint()

    assert fingerprint(PrivateThresholdScorer(0.25)) != fingerprint(PrivateThresholdScorer(0.75))
    assert fingerprint(SlottedThresholdScorer(0.25)) != fingerprint(SlottedThresholdScorer(0.75))


def test_callable_fingerprint_payload_is_authoritative_configuration() -> None:
    class PayloadScorer:
        def __init__(self, threshold: float, cache_marker: str) -> None:
            self._threshold = threshold
            self._cache_marker = cache_marker

        def fingerprint_payload(self) -> Any:
            return {"threshold": self._threshold}

        def __call__(self, rollout: Any) -> float:
            del rollout
            return float(self._threshold >= 0.5)

    def fingerprint(scorer: PayloadScorer) -> str:
        env = Environment(name="payload-scorer")
        env.scorer(scorer, name="threshold")
        return env.fingerprint()

    assert fingerprint(PayloadScorer(0.25, "first")) == fingerprint(PayloadScorer(0.25, "second"))
    assert fingerprint(PayloadScorer(0.25, "first")) != fingerprint(PayloadScorer(0.75, "first"))


def test_fingerprint_payload_distinguishes_external_configuration() -> None:
    class ConfiguredEnvironment(Environment[Any, Any]):
        def __init__(self, endpoint: str, **kwargs: Any) -> None:
            self.endpoint = endpoint
            super().__init__(**kwargs)

        def fingerprint_payload(self) -> Any:
            return {"endpoint": self.endpoint}

    first = ConfiguredEnvironment("https://first.example", name="configured")
    second = ConfiguredEnvironment("https://second.example", name="configured")

    assert first.fingerprint() != second.fingerprint()


def test_spawn_rebinds_bound_scorer_and_task_provider_to_worker() -> None:
    class BoundEnvironment(Environment[Any, Any]):
        marker = "fresh"

        def score_marker(self, rollout: Any) -> float:
            del rollout
            return 1.0 if self.marker == "worker" else 0.0

        def provide_tasks(self) -> list[TaskData]:
            return [TaskData(task_id="bound", input=self.marker)]

    template = BoundEnvironment(name="bound")
    template.marker = "template"
    template.scorer(template.score_marker)
    template.tasks(template.provide_tasks)

    worker = template.spawn()
    worker.marker = "worker"
    assert next(worker.iter_tasks()).input == "worker"
    worker.reset(TaskData(task_id="one", input="x"))
    rollout = worker.close_episode()
    assert rollout.trace.outcome is not None
    assert rollout.trace.outcome.reward == 1.0


def test_spawn_rejects_nested_environment_captures() -> None:
    tool_env = Environment(name="nested-tool")
    tool_capture = {"nested": [tool_env]}

    @tool_env.action
    def nested_tool() -> str:
        return tool_capture["nested"][0].name

    with pytest.raises(RuntimeError, match="dynamic action.*environment_factory"):
        tool_env.spawn()

    scorer_env = Environment(name="nested-scorer")
    scorer_capture = {"nested": [scorer_env]}

    @scorer_env.scorer
    def nested_scorer(rollout: Any) -> float:
        del rollout
        return float(bool(scorer_capture["nested"][0].name))

    with pytest.raises(RuntimeError, match="scorer.*environment_factory"):
        scorer_env.spawn()

    tasks_env = Environment(name="nested-tasks")
    tasks_capture = {"nested": [tasks_env]}

    @tasks_env.tasks
    def nested_tasks() -> list[TaskData]:
        return [TaskData(task_id="nested", input=tasks_capture["nested"][0].name)]

    with pytest.raises(RuntimeError, match="tasks provider.*environment_factory"):
        tasks_env.spawn()


def test_spawn_rejects_callable_objects_with_private_and_slotted_captures() -> None:
    class PrivateTool:
        def __init__(self, env: Environment[Any, Any]) -> None:
            self._env = env

        def __call__(self) -> str:
            return self._env.name

    tool_env = Environment(name="private-tool")
    tool_env.action(PrivateTool(tool_env), name="captured")
    with pytest.raises(RuntimeError, match="dynamic action.*environment_factory"):
        tool_env.spawn()

    class SlottedScorer:
        __slots__ = ("env",)

        def __init__(self, env: Environment[Any, Any]) -> None:
            self.env = env

        def __call__(self, rollout: Any) -> float:
            del rollout
            return float(bool(self.env.name))

    scorer_env = Environment(name="slotted-scorer")
    scorer_env.scorer(SlottedScorer(scorer_env), name="captured")
    with pytest.raises(RuntimeError, match="scorer.*environment_factory"):
        scorer_env.spawn()

    class TaskProviderBase:  # noqa: B903 - inheritance exercises slots across the MRO
        __slots__ = ("env",)

        def __init__(self, env: Environment[Any, Any]) -> None:
            self.env = env

    class SlottedTaskProvider(TaskProviderBase):
        __slots__ = ()

        def __call__(self) -> list[TaskData]:
            return [TaskData(task_id="captured", input=self.env.name)]

    tasks_env = Environment(name="slotted-tasks")
    tasks_env.tasks(SlottedTaskProvider(tasks_env))
    with pytest.raises(RuntimeError, match="tasks provider.*environment_factory"):
        tasks_env.spawn()


def test_trace_metadata_task_payload_cannot_be_overridden() -> None:
    env = Environment(
        name="reserved-metadata",
        metadata={
            "task": {
                "task_id": "forged",
                "input": "forged",
                "expected": "private",
            }
        },
    )
    task = TaskData(task_id="canonical", input="safe", expected="private")

    env.reset(task)
    trace = env.close_episode().trace

    assert trace.metadata["task"] == {
        "task_id": "canonical",
        "input": "safe",
        "metadata": {},
    }
    assert "expected" not in trace.metadata["task"]


def test_episode_trace_is_available_after_close_as_a_snapshot() -> None:
    env = AlphaEnv()
    env.reset(_task())
    trace_id = env.close_episode().trace.trace_id

    snapshot = env.episode_trace
    assert snapshot is not None
    assert snapshot.trace_id == trace_id
    snapshot.trace_id = "changed"
    assert env.episode_trace is not None
    assert env.episode_trace.trace_id == trace_id


def test_replay_success_mismatches_and_fingerprint_guard() -> None:
    source = AlphaEnv()
    trace = source.run_episode(
        _task(),
        ScriptedPolicy(
            [
                ParsedAction(name="inc", arguments={"by": 1}),
                ParsedAction(name="inc", arguments={"by": 1}),
            ]
        ),
    ).trace

    replayed = replay_actions(AlphaEnv(), trace)
    assert isinstance(replayed, ReplayResult)
    assert replayed.ok
    assert replayed.rollout is not None
    assert replayed.rollout.trace.final_state == trace.final_state

    changed = trace.model_copy(deep=True)
    changed.turns()[0].observation = {"text": "different"}
    mismatched = verify_replay(AlphaEnv(), changed)
    assert not mismatched.matched
    assert any(item.kind == "observation" for item in mismatched.mismatches)

    fingerprint_mismatch = replay_actions(AlphaEnv(max_turns=99), trace)
    assert fingerprint_mismatch.rollout is None
    assert [item.kind for item in fingerprint_mismatch.mismatches] == ["fingerprint"]


def test_replay_checks_snapshots_tools_rewards_and_outcomes() -> None:
    source = AlphaEnv()

    @source.scorer(name="score")
    def source_score(rollout: Any) -> float:
        del rollout
        return 1.0

    trace = source.run_episode(
        _task(target=1),
        ScriptedPolicy([ParsedAction(name="inc", arguments={"by": 1})]),
    ).trace

    class DivergentEnv(AlphaEnv):
        def setup(self, task: TaskData) -> None:
            super().setup(task)
            self.state.count = 5

        @action
        def inc(self, by: int = 1) -> int:
            """Increment differently."""
            self.state.count += by + 1
            return self.state.count

    divergent = DivergentEnv()

    @divergent.scorer(name="score")
    def replay_score(rollout: Any) -> float:
        del rollout
        return 0.0

    replayed = verify_replay(divergent, trace, verify_fingerprint=False)
    kinds = {mismatch.kind for mismatch in replayed.mismatches}
    assert "initial_state" in kinds
    assert "tool_calls" in kinds
    assert "reward_events" not in kinds
    assert "outcome_scores" in kinds
    assert "outcome_reward" in kinds


def test_replay_rejects_redacted_trace() -> None:
    trace = (
        AlphaEnv()
        .run_episode(
            _task(target=1),
            ScriptedPolicy([ParsedAction(name="inc", arguments={"by": 1})]),
        )
        .trace
    )
    redacted = Redactor(drop_content=True).apply(trace)

    with pytest.raises(ValueError, match="redacted content"):
        replay_actions(AlphaEnv(), redacted)


def test_replay_accepts_explicit_hidden_task() -> None:
    task = _task(target=1, expected=1)
    source = AlphaEnv()

    @source.scorer
    def expected_count(rollout: Any) -> float:
        return float(rollout.env.state.count == rollout.task.expected)

    trace = source.run_episode(
        task,
        ScriptedPolicy([ParsedAction(name="inc", arguments={"by": 1})]),
    ).trace
    assert "expected" not in trace.metadata["task"]

    replay_env = AlphaEnv()

    @replay_env.scorer
    def expected_count_replay(rollout: Any) -> float:
        return float(rollout.env.state.count == rollout.task.expected)

    result = verify_replay(
        replay_env,
        trace,
        task=task,
        verify_fingerprint=False,
    )
    assert result.rollout is not None
    assert result.rollout.trace.outcome is not None
    assert result.rollout.trace.outcome.reward == 1.0


def test_replay_requires_a_task() -> None:
    trace = (
        AlphaEnv()
        .run_episode(
            _task(target=1),
            ScriptedPolicy([ParsedAction(name="inc", arguments={"by": 1})]),
        )
        .trace
    )
    trace.metadata.pop("task")
    with pytest.raises(ValueError, match="replay requires"):
        replay_actions(AlphaEnv(), trace)


def test_policy_and_step_failures_close_and_persist_failed_trace() -> None:
    class RecordingWriter:
        def __init__(self) -> None:
            self.traces: list[Any] = []

        def record(self, trace: Any) -> None:
            self.traces.append(trace.model_copy(deep=True))

    class RecordingClient:
        def __init__(self) -> None:
            self.writer = RecordingWriter()

    class FailingPolicy:
        def act(self, request: Any, *, trace_context: Any = None) -> Any:
            del request, trace_context
            raise RuntimeError("policy exploded")

    policy_client = RecordingClient()
    policy_env = AlphaEnv()
    with pytest.raises(RuntimeError, match="policy exploded"):
        policy_env.run_episode(
            _task(),
            FailingPolicy(),
            persist_with=policy_client,  # type: ignore[arg-type]
        )
    assert policy_env.episode_state is EpisodeState.CLOSED
    assert len(policy_client.writer.traces) == 1
    assert policy_client.writer.traces[0].failed is True
    assert policy_client.writer.traces[0].stop_reason == "failure"
    assert "policy exploded" in policy_client.writer.traces[0].outcome.feedback

    class FailingActionEnv(AlphaEnv):
        def apply_action(
            self,
            action: Any,
            *,
            runtime: Runtime,
            response: ChatResponse | None = None,
        ) -> ActionResult:
            del action, runtime, response
            raise ValueError("action exploded")

    step_client = RecordingClient()
    step_env = FailingActionEnv()
    with pytest.raises(ValueError, match="action exploded"):
        step_env.run_episode(
            _task(),
            ScriptedPolicy([ParsedAction(name="anything")]),
            persist_with=step_client,  # type: ignore[arg-type]
        )
    assert step_env.episode_state is EpisodeState.CLOSED
    assert len(step_client.writer.traces) == 1
    assert step_client.writer.traces[0].failed is True


def test_scorer_failure_closes_and_persists_before_reraising() -> None:
    class RecordingWriter:
        def __init__(self) -> None:
            self.traces: list[Any] = []

        def record(self, trace: Any) -> None:
            self.traces.append(trace.model_copy(deep=True))

    class RecordingClient:
        def __init__(self) -> None:
            self.writer = RecordingWriter()

    env = AlphaEnv()

    @env.scorer
    def broken_scorer(rollout: Any) -> float:
        del rollout
        raise RuntimeError("scorer exploded")

    client = RecordingClient()
    with pytest.raises(RuntimeError, match="scorer exploded"):
        env.run_episode(
            _task(),
            ScriptedPolicy([_response("done")]),
            persist_with=client,  # type: ignore[arg-type]
        )

    assert env.episode_state is EpisodeState.CLOSED
    assert len(client.writer.traces) == 1
    trace = client.writer.traces[0]
    assert trace.failed is True
    assert trace.metadata["failure"]["type"] == "RuntimeError"
    assert trace.outcome.feedback == "RuntimeError: scorer exploded"


def test_public_imports() -> None:
    from plural import ActionResult as TopActionResult
    from plural import PluralPolicy as TopPluralPolicy
    from plural import Policy as TopPolicy
    from plural import ScriptedPolicy as TopScriptedPolicy
    from plural import StopReason as TopStopReason
    from plural.environments import ActionResult as EnvironmentActionResult
    from plural.environments import PluralPolicy as EnvironmentPluralPolicy

    assert TopActionResult is EnvironmentActionResult is ActionResult
    assert TopPluralPolicy is EnvironmentPluralPolicy is PluralPolicy
    assert TopPolicy is Policy
    assert TopScriptedPolicy is ScriptedPolicy
    assert TopStopReason is StopReason
