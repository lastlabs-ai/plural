from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, cast

import pytest

from enroute.benchmarks import (
    Benchmark,
    CaseKey,
    ModelStats,
    Report,
    RunManifest,
    TaskSetMetadata,
)
from enroute.environments import Environment, Rollout, TaskData, TaskDataset, tool
from enroute.environments.runtime import LocalRuntime, runtime_fingerprint
from enroute.tracing import JSONLSink, Outcome, ParsedAction, Trace, TraceWriter


@dataclass(frozen=True)
class _CaseSpec:
    reward: float | None = None
    delay: float = 0.0
    scores: dict[str, float] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    failure: type[Exception] | None = None


class _Worker:
    name = "scripted"
    version = "1.2.3"

    def __init__(self, script: dict[tuple[str, str], _CaseSpec]) -> None:
        self._script = script

    def fingerprint(self) -> str:
        return "scripted-fingerprint"

    def rollout(self, task: TaskData, client: object, *, model: str) -> Rollout:
        del client
        spec = self._script[(model, task.task_id)]
        if spec.delay:
            time.sleep(spec.delay)
        if spec.failure is not None:
            raise spec.failure(f"{model}/{task.task_id} failed")
        return Rollout(
            task=task,
            trace=Trace(
                trace_id=f"trace-{model}-{task.task_id}",
                trace_kind="episode",
                episode_trace_id=f"trace-{model}-{task.task_id}",
                stop_reason="terminated",
                task_id=task.task_id,
                model=model,
                outcome=Outcome(
                    reward=spec.reward,
                    scores=(
                        spec.scores
                        if spec.scores is not None
                        else ({"quality": spec.reward} if spec.reward is not None else {})
                    ),
                ),
                metrics=spec.metrics,
                terminated=True,
                truncated=False,
            ),
        )


class _ScriptedEnvironment:
    name = "scripted"
    version = "1.2.3"

    def __init__(
        self,
        script: dict[tuple[str, str], _CaseSpec],
        tasks: list[TaskData] | None = None,
    ) -> None:
        self._script = script
        self._tasks = tasks or []

    def spawn(self) -> _Worker:
        return _Worker(self._script)

    def iter_tasks(self) -> Iterator[TaskData]:
        return iter(self._tasks)

    def fingerprint(self) -> str:
        return "scripted-fingerprint"


class _MutatingWorker:
    name = "mutating"
    version = "1.0.0"

    def __init__(self, observed_lengths: list[int], lock: Lock) -> None:
        self.observed_lengths = observed_lengths
        self.lock = lock

    def rollout(self, task: TaskData, client: object, *, model: str) -> Rollout:
        del client
        task.input["models"].append(model)
        with self.lock:
            self.observed_lengths.append(len(task.input["models"]))
        return Rollout(
            task=task,
            trace=Trace(
                trace_id=f"{model}-{id(task)}",
                outcome=Outcome(reward=1.0),
            ),
        )

    def fingerprint(self) -> str:
        return "mutating-fingerprint"


class _MutatingEnvironment:
    name = "mutating"
    version = "1.0.0"

    def __init__(self) -> None:
        self.observed_lengths: list[int] = []
        self.lock = Lock()

    def spawn(self) -> _MutatingWorker:
        return _MutatingWorker(self.observed_lengths, self.lock)

    def fingerprint(self) -> str:
        return "mutating-fingerprint"


def _benchmark(
    env: _ScriptedEnvironment,
    models: list[str],
    *,
    repeats: int = 1,
    concurrency: int = 4,
) -> Benchmark:
    return Benchmark(
        cast(Any, env),
        models=models,
        client=cast(Any, object()),
        repeats=repeats,
        concurrency=concurrency,
    )


def test_each_concurrent_job_receives_a_deep_task_copy() -> None:
    task = TaskData(task_id="shared", input={"models": []})
    env = _MutatingEnvironment()

    report = _benchmark(cast(Any, env), ["a", "b"], repeats=4, concurrency=8).run([task])

    assert report.models["a"].n == 4
    assert report.models["b"].n == 4
    assert sorted(env.observed_lengths) == [1] * 8
    assert task.input == {"models": []}


def test_win_rates_align_by_task_instead_of_completion_order() -> None:
    tasks = [TaskData(task_id="t1", input="one"), TaskData(task_id="t2", input="two")]
    env = _ScriptedEnvironment(
        {
            ("a", "t1"): _CaseSpec(reward=2.0, delay=0.04),
            ("a", "t2"): _CaseSpec(reward=0.0, delay=0.01),
            ("b", "t1"): _CaseSpec(reward=1.0, delay=0.02),
            ("b", "t2"): _CaseSpec(reward=-1.0, delay=0.03),
        }
    )

    report = _benchmark(env, ["a", "b"]).run(tasks)

    assert report.win_rates == {"a": {"b": 1.0}, "b": {"a": 0.0}}
    pair = report.win_rate_pairs[0]
    assert (pair.wins, pair.losses, pair.ties, pair.compared, pair.excluded) == (2, 0, 0, 2, 0)


def test_aligned_failures_are_excluded_and_recorded() -> None:
    tasks = [TaskData(task_id="failed", input="x"), TaskData(task_id="scored", input="y")]
    env = _ScriptedEnvironment(
        {
            ("a", "failed"): _CaseSpec(failure=RuntimeError),
            ("a", "scored"): _CaseSpec(reward=1.0),
            ("b", "failed"): _CaseSpec(reward=0.0),
            ("b", "scored"): _CaseSpec(reward=0.0),
        }
    )

    report = _benchmark(env, ["a", "b"]).run(tasks)

    pair = report.win_rate_pairs[0]
    assert (pair.compared, pair.excluded, pair.wins, pair.win_rate) == (1, 1, 1, 1.0)
    assert report.models["a"].n == 1
    assert report.models["a"].failures == 1
    failed = report.cases[0]
    assert failed.failure_type == "RuntimeError"
    assert failed.failure_message == "a/failed failed"
    assert failed.trace_id is None


def test_episode_metrics_drive_latency_and_cost_aggregation() -> None:
    tasks = [TaskData(task_id="one", input="x"), TaskData(task_id="two", input="y")]
    env = _ScriptedEnvironment(
        {
            ("m", "one"): _CaseSpec(
                reward=1.0,
                metrics={"latency_ms": 10.0, "cost": 1.0, "turns": 2},
            ),
            ("m", "two"): _CaseSpec(
                reward=0.0,
                metrics={"latency_ms": 30.0, "cost": 3.0, "turns": 4},
            ),
        }
    )

    report = _benchmark(env, ["m"]).run(tasks)
    stats = report.models["m"]

    assert stats.mean_latency_ms == 20.0
    assert stats.p50_latency_ms == 20.0
    assert stats.p95_latency_ms == pytest.approx(29.0)
    assert stats.mean_cost == 2.0
    assert stats.total_cost == 4.0
    assert report.cases[0].metrics == {"cost": 1.0, "latency_ms": 10.0, "turns": 2}


def test_case_order_is_job_order_not_completion_order() -> None:
    tasks = [TaskData(task_id="first", input="x"), TaskData(task_id="second", input="y")]
    env = _ScriptedEnvironment(
        {
            ("slow", "first"): _CaseSpec(reward=1.0, delay=0.04),
            ("slow", "second"): _CaseSpec(reward=1.0, delay=0.01),
            ("fast", "first"): _CaseSpec(reward=1.0, delay=0.02),
            ("fast", "second"): _CaseSpec(reward=1.0, delay=0.03),
        }
    )

    report = _benchmark(env, ["slow", "fast"], repeats=2, concurrency=8).run(tasks)

    assert [case.key for case in report.cases] == [
        CaseKey(model=model, task_id=task_id, repeat=repeat)
        for model in ("slow", "fast")
        for task_id in ("first", "second")
        for repeat in range(2)
    ]
    assert list(report.models) == ["slow", "fast"]


def test_benchmark_configuration_validation() -> None:
    env = _ScriptedEnvironment({})

    with pytest.raises(ValueError, match="models must not be empty"):
        _benchmark(env, [])
    with pytest.raises(ValueError, match="models must not contain duplicates"):
        _benchmark(env, ["m", "m"])
    with pytest.raises(ValueError, match="repeats must be at least 1"):
        _benchmark(env, ["m"], repeats=0)
    with pytest.raises(ValueError, match="concurrency must be at least 1"):
        _benchmark(env, ["m"], concurrency=0)


def test_task_validation() -> None:
    env = _ScriptedEnvironment({})
    benchmark = _benchmark(env, ["m"])

    with pytest.raises(ValueError, match="tasks must not be empty"):
        benchmark.run([])
    with pytest.raises(ValueError, match="task_id values must be unique"):
        benchmark.run(
            [
                TaskData(task_id="duplicate", input="x"),
                TaskData(task_id="duplicate", input="y"),
            ]
        )


def test_one_model_and_default_tasks_behavior() -> None:
    tasks = [TaskData(task_id="only", input="x")]
    env = _ScriptedEnvironment({("solo", "only"): _CaseSpec(reward=0.5)}, tasks)

    report = _benchmark(env, ["solo"], repeats=2).run()

    assert report.win_rates == {"solo": {}}
    assert report.win_rate_pairs == []
    assert report.models["solo"].n == 2
    assert [case.key.repeat for case in report.cases] == [0, 1]
    assert report.manifest is not None
    assert report.manifest.task_set is not None
    assert report.manifest.task_set.source == "environment"
    assert report.manifest.task_set.content_hash


def test_explicit_tasks_record_source_identity_and_hash() -> None:
    task = TaskData(task_id="only", input={"nested": ["x"]}, expected="private")
    env = _ScriptedEnvironment({("m", "only"): _CaseSpec(reward=1.0)})

    report = _benchmark(env, ["m"]).run([task])

    assert report.manifest is not None
    assert report.manifest.task_set is not None
    assert report.manifest.task_set.source == "explicit"
    assert report.manifest.task_set.name == "explicit"
    assert report.manifest.task_set.content_hash
    assert report.cases[0].metrics == {}


def test_task_dataset_input_and_manifest_completeness() -> None:
    tasks = [TaskData(task_id="first", input="x"), TaskData(task_id="second", input="y")]
    dataset = TaskDataset(name="alpha-suite", version="2026.08", tasks=tasks)
    env = _ScriptedEnvironment(
        {
            ("b", "first"): _CaseSpec(reward=1.0),
            ("b", "second"): _CaseSpec(reward=0.0),
            ("a", "first"): _CaseSpec(reward=0.0),
            ("a", "second"): _CaseSpec(reward=1.0),
        }
    )

    report = _benchmark(env, ["b", "a"], concurrency=2).run(dataset=dataset)

    assert report.manifest.environment == "scripted"
    assert report.manifest.environment_version == "1.2.3"
    assert report.manifest.environment_fingerprint == "scripted-fingerprint"
    assert report.manifest.targets == ["b", "a"]
    assert report.manifest.task_ids == ["first", "second"]
    assert report.manifest.repeats == 1
    assert report.manifest.concurrency == 2
    assert report.manifest.package_version
    assert report.manifest.status == "completed"
    assert report.manifest.started_at <= report.manifest.completed_at
    assert report.manifest.task_dataset is not None
    assert report.manifest.task_set is not None
    assert report.manifest.task_set.source == "task_dataset"
    assert report.manifest.task_set.content_hash == dataset.content_hash
    assert report.manifest.task_dataset.model_dump() == {
        "name": "alpha-suite",
        "version": "2026.08",
        "content_hash": dataset.content_hash,
    }
    assert report.metadata["task_dataset"] == report.manifest.task_dataset.model_dump()
    assert report.to_json() == report.to_json()


def test_benchmark_rejects_stale_task_dataset_hash() -> None:
    task = TaskData(task_id="one", input={"value": 1})
    dataset = TaskDataset(name="suite", tasks=[task])
    task.input["value"] = 2

    with pytest.raises(ValueError, match="content_hash is stale"):
        _benchmark(_ScriptedEnvironment({}), ["m"]).run(dataset=dataset)


def test_tasks_and_task_dataset_are_mutually_exclusive() -> None:
    task = TaskData(task_id="one", input="x")
    benchmark = _benchmark(_ScriptedEnvironment({}), ["m"])

    with pytest.raises(ValueError, match="mutually exclusive"):
        benchmark.run([task], dataset=TaskDataset(name="suite", tasks=[task]))


class _SingleUsePolicy:
    def __init__(self) -> None:
        self.calls = 0

    def act(self, request: Any, *, trace_context: Any = None) -> ParsedAction:
        del request, trace_context
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("policy instance was reused")
        return ParsedAction(name="respond", arguments={})


class _RequiredConstructorEnvironment(Environment[Any, Any]):
    def __init__(self, required: str, **kwargs: Any) -> None:
        self.required = required
        super().__init__(**kwargs)


class _ToolEnvironment(Environment[Any, Any]):
    @tool
    def ping(self) -> str:
        return "local"


class _ToolThenStopPolicy:
    def __init__(self) -> None:
        self.calls = 0

    def act(self, request: Any, *, trace_context: Any = None) -> ParsedAction:
        del request, trace_context
        self.calls += 1
        return ParsedAction(
            name="ping" if self.calls == 1 else "respond",
            arguments={},
        )


class _RecordingRuntime:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        del arguments
        self.calls.append(name)
        return "custom"


class _FalseyRuntime(_RecordingRuntime):
    def __bool__(self) -> bool:
        return False


class _IdentifiedRuntime(_RecordingRuntime):
    def __init__(self, calls: list[str], identity: str) -> None:
        super().__init__(calls)
        self.identity = identity

    def fingerprint(self) -> str:
        return self.identity


class _FactoryIdentityEnvironment(Environment[Any, Any]):
    def __init__(self, configuration: str, **kwargs: Any) -> None:
        self.configuration = configuration
        super().__init__(**kwargs)

    def fingerprint_payload(self) -> Any:
        return {"configuration": self.configuration}


class _ModelFactoryEnvironment(Environment[Any, Any]):
    def __init__(self, instances: list[int], **kwargs: Any) -> None:
        self.instances = instances
        super().__init__(**kwargs)

    def rollout(
        self,
        task: TaskData,
        client: Any,
        *,
        model: str,
        runtime: Any = None,
    ) -> Rollout:
        del client, runtime
        self.instances.append(id(self))
        return Rollout(
            task=task,
            trace=Trace(trace_id=f"{model}-{id(self)}", outcome=Outcome(reward=1.0)),
            env=self,
        )


def test_generic_policy_factories_need_no_client_and_are_fresh_per_case() -> None:
    env = Environment(name="policy-env", version="3.0.0", max_turns=2)

    @env.scorer
    def always_pass(rollout: Rollout) -> float:
        del rollout
        return 1.0

    created: list[_SingleUsePolicy] = []

    def factory() -> _SingleUsePolicy:
        policy = _SingleUsePolicy()
        created.append(policy)
        return policy

    dataset = TaskDataset(
        name="policy-tasks",
        tasks=[TaskData(task_id="one", input="x"), TaskData(task_id="two", input="y")],
    )
    benchmark = Benchmark.from_policies(
        env,
        {"custom-agent": factory},
        repeats=2,
        concurrency=4,
    )

    report = benchmark.run(dataset=dataset)

    assert benchmark.client is None
    assert len(created) == 4
    assert all(policy.calls == 1 for policy in created)
    assert report.models["custom-agent"].n == 4
    assert report.manifest.targets == ["custom-agent"]
    assert [case.key.model for case in report.cases] == ["custom-agent"] * 4
    assert all(case.trace_kind == "episode" for case in report.cases)
    assert all(case.trace_id == case.episode_trace_id for case in report.cases)
    assert all(case.stop_reason == "policy_stop" for case in report.cases)


def test_environment_factory_supports_required_constructor_and_dynamic_tools() -> None:
    dynamic_template = Environment(name="dynamic")

    @dynamic_template.tool
    def captured_tool() -> str:
        return dynamic_template.name

    with pytest.raises(RuntimeError, match="dynamic tool.*environment_factory"):
        dynamic_template.spawn()

    template = _RequiredConstructorEnvironment("template", name="required")

    @template.tool
    def unsafe_tool() -> str:
        return template.required

    with pytest.raises(RuntimeError, match=r"override spawn\(\)|environment_factory"):
        template.spawn()

    def environment_factory() -> _RequiredConstructorEnvironment:
        env = _RequiredConstructorEnvironment("fresh", name="required")

        @env.tool
        def safe_tool() -> str:
            return env.required

        return env

    report = Benchmark.from_policies(
        template,
        {"agent": _SingleUsePolicy},
        environment_factory=environment_factory,
    ).run([TaskData(task_id="one", input="x")])

    assert report.models["agent"].n == 1


def test_factory_worker_identity_replaces_template_provenance() -> None:
    template = _FactoryIdentityEnvironment(
        "template",
        name="template",
        version="0.0.1",
    )

    report = Benchmark.from_policies(
        template,
        {"agent": _SingleUsePolicy},
        environment_factory=lambda: _FactoryIdentityEnvironment(
            "worker",
            name="actual",
            version="2.0.0",
        ),
    ).run([TaskData(task_id="one", input="x")])

    actual = _FactoryIdentityEnvironment("worker", name="actual", version="2.0.0")
    assert report.environment == "actual"
    assert report.environment_version == "2.0.0"
    assert report.manifest.environment == "actual"
    assert report.manifest.environment_version == "2.0.0"
    assert report.manifest.environment_fingerprint == actual.fingerprint()
    assert report.manifest.environment_fingerprint != template.fingerprint()


def test_factory_workers_must_have_consistent_environment_identity() -> None:
    lock = Lock()
    created = 0

    def factory() -> _FactoryIdentityEnvironment:
        nonlocal created
        with lock:
            created += 1
            number = created
        return _FactoryIdentityEnvironment(
            f"worker-{number}",
            name=f"worker-{number}",
            version="1.0.0",
        )

    benchmark = Benchmark.from_policies(
        _FactoryIdentityEnvironment("template", name="template"),
        {"agent": _SingleUsePolicy},
        repeats=2,
        environment_factory=factory,
    )

    with pytest.raises(ValueError, match="inconsistent environment identities"):
        benchmark.run([TaskData(task_id="one", input="x")])


def test_factory_identity_falls_back_to_template_when_no_worker_is_produced() -> None:
    template = _FactoryIdentityEnvironment("template", name="template", version="1.0.0")

    def factory() -> _FactoryIdentityEnvironment:
        raise RuntimeError("factory unavailable")

    report = Benchmark.from_policies(
        template,
        {"agent": _SingleUsePolicy},
        environment_factory=factory,
    ).run([TaskData(task_id="one", input="x")])

    assert report.environment == "template"
    assert report.manifest.environment_fingerprint == template.fingerprint()
    assert report.cases[0].failure_type == "RuntimeError"


def test_runtime_factory_produces_a_fresh_custom_runtime_per_job() -> None:
    calls: list[str] = []
    runtimes: list[_RecordingRuntime] = []

    def runtime_factory() -> _RecordingRuntime:
        runtime = _RecordingRuntime(calls)
        runtimes.append(runtime)
        return runtime

    report = Benchmark.from_policies(
        _ToolEnvironment(name="tools", max_turns=2),
        {"agent": _ToolThenStopPolicy},
        repeats=2,
        environment_factory=lambda: _ToolEnvironment(name="tools", max_turns=2),
        runtime_factory=runtime_factory,
    ).run([TaskData(task_id="one", input="x")])

    assert report.models["agent"].n == 2
    assert len(runtimes) == 2
    assert calls == ["ping", "ping"]


def test_runtime_fingerprints_cover_local_tools_and_generic_runtime_behavior() -> None:
    def first_tool() -> str:
        return "first"

    def second_tool() -> str:
        return "second"

    assert runtime_fingerprint(LocalRuntime({"tool": first_tool})) != runtime_fingerprint(
        LocalRuntime({"tool": second_tool})
    )

    class ConfiguredRuntime:
        def __init__(self, mode: str) -> None:
            self._mode = mode

        def call(self, name: str, arguments: dict[str, Any]) -> Any:
            return name, arguments, self._mode

    assert runtime_fingerprint(ConfiguredRuntime("first")) != runtime_fingerprint(
        ConfiguredRuntime("second")
    )


def test_cases_record_heterogeneous_runtime_provenance_on_success_and_failure() -> None:
    created_runtimes = 0
    created_policies = 0

    def runtime_factory() -> _IdentifiedRuntime:
        nonlocal created_runtimes
        created_runtimes += 1
        identity = "runtime-success" if created_runtimes == 1 else "runtime-failure"
        return _IdentifiedRuntime([], identity)

    class FailingPolicy:
        def act(self, request: Any, *, trace_context: Any = None) -> ParsedAction:
            del request, trace_context
            raise RuntimeError("policy failed")

    def policy_factory() -> _SingleUsePolicy | FailingPolicy:
        nonlocal created_policies
        created_policies += 1
        return _SingleUsePolicy() if created_policies == 1 else FailingPolicy()

    report = Benchmark.from_policies(
        _ToolEnvironment(name="tools", max_turns=2),
        {"agent": policy_factory},
        repeats=2,
        concurrency=1,
        runtime_factory=runtime_factory,
    ).run([TaskData(task_id="one", input="x")])

    assert report.cases[0].failure_type is None
    assert report.cases[0].runtime_fingerprint == "runtime-success"
    assert report.cases[1].failure_type == "RuntimeError"
    assert report.cases[1].runtime_fingerprint == "runtime-failure"
    assert report.manifest.runtime_fingerprints == ["runtime-failure", "runtime-success"]


def test_default_local_runtime_is_attributable_per_case() -> None:
    report = Benchmark.from_policies(
        _ToolEnvironment(name="tools", max_turns=2),
        {"agent": _ToolThenStopPolicy},
    ).run([TaskData(task_id="one", input="x")])

    expected = runtime_fingerprint(LocalRuntime(_ToolEnvironment().tool_functions))
    assert report.cases[0].runtime_fingerprint == expected
    assert report.manifest.runtime_fingerprints == [expected]
    assert expected != "local"


def test_manifest_captures_sorted_unique_runtime_identities() -> None:
    calls: list[str] = []
    lock = Lock()
    created = 0

    def runtime_factory() -> _IdentifiedRuntime:
        nonlocal created
        with lock:
            created += 1
            identity = f"runtime-{created}"
        return _IdentifiedRuntime(calls, identity)

    report = Benchmark.from_policies(
        _ToolEnvironment(name="tools", max_turns=2),
        {"agent": _ToolThenStopPolicy},
        repeats=2,
        runtime_factory=runtime_factory,
    ).run([TaskData(task_id="one", input="x")])

    assert report.manifest.runtime_fingerprints == ["runtime-1", "runtime-2"]


def test_falsey_runtime_is_not_replaced_by_local_runtime() -> None:
    calls: list[str] = []

    report = Benchmark.from_policies(
        _ToolEnvironment(name="tools", max_turns=2),
        {"agent": _ToolThenStopPolicy},
        runtime_factory=lambda: _FalseyRuntime(calls),
    ).run([TaskData(task_id="one", input="x")])

    assert report.models["agent"].n == 1
    assert calls == ["ping"]


def test_model_benchmark_constructor_uses_fresh_environment_and_runtime_factories() -> None:
    instances: list[int] = []
    runtimes: list[_RecordingRuntime] = []
    template = _ModelFactoryEnvironment(instances, name="model-factory")

    def runtime_factory() -> _RecordingRuntime:
        runtime = _RecordingRuntime([])
        runtimes.append(runtime)
        return runtime

    report = Benchmark(
        template,
        ["model"],
        client=cast(Any, object()),
        repeats=3,
        environment_factory=lambda: _ModelFactoryEnvironment(instances, name="model-factory"),
        runtime_factory=runtime_factory,
    ).run([TaskData(task_id="one", input="x")])

    assert report.models["model"].n == 3
    assert len(set(instances)) == 3
    assert len(runtimes) == 3


def test_factory_configuration_and_produced_types_are_validated() -> None:
    env = Environment(name="factory-validation")
    with pytest.raises(TypeError, match="environment_factory must be callable"):
        Benchmark.from_policies(env, {"agent": _SingleUsePolicy}, environment_factory=cast(Any, 1))
    with pytest.raises(TypeError, match="runtime_factory must be callable"):
        Benchmark.from_policies(env, {"agent": _SingleUsePolicy}, runtime_factory=cast(Any, 1))

    bad_environment = Benchmark.from_policies(
        env,
        {"agent": _SingleUsePolicy},
        environment_factory=cast(Any, lambda: object()),
    ).run([TaskData(task_id="one", input="x")])
    assert bad_environment.cases[0].failure_type == "TypeError"
    assert "did not return an Environment" in (bad_environment.cases[0].failure_message or "")

    bad_runtime = Benchmark.from_policies(
        env,
        {"agent": _SingleUsePolicy},
        runtime_factory=cast(Any, lambda: object()),
    ).run([TaskData(task_id="one", input="x")])
    assert bad_runtime.cases[0].failure_type == "TypeError"
    assert "did not return a Runtime" in (bad_runtime.cases[0].failure_message or "")


def test_generic_policy_successes_are_persisted_with_caller_writer(tmp_path: Path) -> None:
    path = tmp_path / "policy-traces.jsonl"
    sink = JSONLSink(path)
    writer = TraceWriter(sink)
    benchmark = Benchmark.from_policies(
        Environment(name="persisted"),
        {"agent": _SingleUsePolicy},
        trace_writer=writer,
    )

    report = benchmark.run([TaskData(task_id="one", input="x")])
    writer.flush()

    traces = sink.read_all()
    assert len(traces) == 1
    assert traces[0].trace_id == report.cases[0].trace_id
    assert writer._closed is False
    writer.close()


def test_failed_policy_trace_is_persisted_once_and_linked_to_case(tmp_path: Path) -> None:
    class FailingPolicy:
        def act(self, request: Any, *, trace_context: Any = None) -> ParsedAction:
            del request, trace_context
            raise RuntimeError("policy failed after reset")

    path = tmp_path / "failed-policy-traces.jsonl"
    sink = JSONLSink(path)
    writer = TraceWriter(sink)
    report = Benchmark.from_policies(
        Environment(name="failed-policy"),
        {"agent": FailingPolicy},
        trace_writer=writer,
    ).run([TaskData(task_id="one", input="x")])
    writer.flush()

    traces = sink.read_all()
    case = report.cases[0]
    assert len(traces) == 1
    assert traces[0].failed is True
    assert traces[0].trace_id == case.trace_id
    assert case.trace_kind == "episode"
    assert case.episode_trace_id == case.trace_id
    assert case.stop_reason == "failure"
    assert case.failure_type == "RuntimeError"
    assert case.failure_message == "policy failed after reset"
    writer.close()


def test_policy_configuration_validation() -> None:
    env = Environment(name="policy-env")

    with pytest.raises(ValueError, match="policies must not be empty"):
        Benchmark.from_policies(env, {})
    with pytest.raises(ValueError, match="target names"):
        Benchmark.from_policies(env, {" ": _SingleUsePolicy})
    with pytest.raises(TypeError, match="must be callable"):
        Benchmark.from_policies(env, cast(Any, {"agent": object()}))


def test_reward_uncertainty_requires_two_scorable_cases() -> None:
    tasks = [TaskData(task_id="low", input="x"), TaskData(task_id="high", input="y")]
    env = _ScriptedEnvironment(
        {
            ("m", "low"): _CaseSpec(reward=1.0),
            ("m", "high"): _CaseSpec(reward=3.0),
        }
    )

    stats = _benchmark(env, ["m"]).run(tasks).models["m"]

    assert stats.mean_reward == 2.0
    assert stats.reward_stddev == pytest.approx(2**0.5)
    assert stats.reward_ci95_lower == pytest.approx(0.04)
    assert stats.reward_ci95_upper == pytest.approx(3.96)

    one = _benchmark(
        _ScriptedEnvironment({("m", "only"): _CaseSpec(reward=1.0)}),
        ["m"],
    ).run([TaskData(task_id="only", input="x")])
    assert one.models["m"].reward_stddev is None
    assert one.models["m"].reward_ci95_lower is None
    assert one.models["m"].reward_ci95_upper is None


def test_nonfinite_rollout_values_become_sanitized_failures() -> None:
    tasks = [
        TaskData(task_id="reward", input="x"),
        TaskData(task_id="score", input="z"),
        TaskData(task_id="metric", input="y"),
    ]
    env = _ScriptedEnvironment(
        {
            ("m", "reward"): _CaseSpec(reward=float("nan")),
            ("m", "score"): _CaseSpec(reward=1.0, scores={"quality": float("-inf")}),
            ("m", "metric"): _CaseSpec(reward=1.0, metrics={"nested": {"cost": float("inf")}}),
        }
    )

    report = _benchmark(env, ["m"]).run(tasks)

    assert report.models["m"].n == 0
    assert report.models["m"].failures == 3
    assert report.models["m"].failure_reasons == {"NonFiniteResult": 3}
    assert all(case.failure_type == "NonFiniteResult" for case in report.cases)
    assert all(case.trace_id is not None for case in report.cases)
    assert all(case.reward is None and case.metrics == {} for case in report.cases)
    assert "NaN" not in report.to_json()
    assert "Infinity" not in report.to_json()


def test_nonfinite_cases_are_excluded_from_model_comparisons() -> None:
    task = TaskData(task_id="one", input="x")
    env = _ScriptedEnvironment(
        {
            ("bad", "one"): _CaseSpec(reward=float("inf")),
            ("good", "one"): _CaseSpec(reward=1.0),
        }
    )

    report = _benchmark(env, ["bad", "good"]).run([task])

    assert report.win_rate_pairs[0].excluded == 1
    assert report.win_rate_pairs[0].compared == 0
    assert report.win_rates == {"bad": {}, "good": {}}


def test_report_json_rejects_manually_injected_nonfinite_values() -> None:
    report = Report(
        environment="env",
        models={"m": ModelStats(model="m", mean_reward=float("nan"))},
    )

    with pytest.raises(ValueError, match="Out of range float values"):
        report.to_json()


def test_benchmark_workers_do_not_swallow_base_exceptions() -> None:
    env = _ScriptedEnvironment({("m", "one"): _CaseSpec(failure=cast(Any, KeyboardInterrupt))})

    with pytest.raises(KeyboardInterrupt):
        _benchmark(env, ["m"]).run([TaskData(task_id="one", input="x")])


def test_compare_supports_reward_regression_tolerance() -> None:
    baseline = Report(
        environment="env",
        models={"m": ModelStats(model="m", mean_reward=1.0)},
    )
    current = Report(
        environment="env",
        models={"m": ModelStats(model="m", mean_reward=0.8)},
    )

    assert current.compare(baseline)["regressions"] == ["m"]
    assert current.compare(baseline, tolerance=0.2)["regressions"] == []
    assert current.compare(baseline, tolerance=0.19)["regressions"] == ["m"]
    with pytest.raises(ValueError, match="non-negative"):
        current.compare(baseline, tolerance=-0.1)


def test_report_without_manifest_preserves_legacy_provenance() -> None:
    report = Report(environment="demo", environment_version="2.0.0")

    assert report.manifest is None
    loaded = Report.model_validate({"environment": "legacy", "models": {}})
    assert loaded.manifest is None
    assert loaded.compare(report)["regressions"] == []


def test_compare_rejects_incompatible_manifest_provenance_by_default() -> None:
    baseline = Report(
        environment="env",
        models={"m": ModelStats(model="m", mean_reward=1.0)},
        manifest=RunManifest(
            environment_fingerprint="fingerprint-a",
            runtime_fingerprints=["runtime-a"],
            task_ids=["one"],
            repeats=1,
            task_set=TaskSetMetadata(
                name="tasks",
                version="1",
                source="explicit",
                content_hash="hash-a",
            ),
        ),
    )
    current = Report(
        environment="env",
        models={"m": ModelStats(model="m", mean_reward=0.5)},
        manifest=RunManifest(
            environment_fingerprint="fingerprint-b",
            runtime_fingerprints=["runtime-b"],
            task_ids=["two"],
            repeats=2,
            task_set=TaskSetMetadata(
                name="tasks",
                version="1",
                source="explicit",
                content_hash="hash-b",
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "environment fingerprint.*runtime fingerprints.*task set content hash"
            ".*task IDs.*repeats"
        ),
    ):
        current.compare(baseline)
    assert current.compare(baseline, allow_incompatible=True)["regressions"] == ["m"]
