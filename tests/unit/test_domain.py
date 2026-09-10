from __future__ import annotations

from pydantic import ValidationError

from plural.domain import (
    AgentBinding,
    AgentTemplate,
    BenchmarkDefinition,
    EnvironmentManifest,
    EnvironmentRuntime,
    ExecutionTarget,
    HarnessBinding,
    HarnessCapability,
    HarnessManifest,
    HarnessPackage,
    HarnessPolicy,
    JobSpec,
    NativeAction,
    PackageSource,
    RetryPolicy,
    RuntimeSpec,
    TaskDefinition,
    resolve_harness_stamp,
)
from plural.sandbox.models import NetworkMode


def _harness(name: str = "chat", *, runnable: bool = True) -> HarnessPackage:
    return HarnessPackage(
        manifest=HarnessManifest(
            name=name,
            implementation="runnable" if runnable else "declared",
            command=("python", "harness.py") if runnable else (),
            capabilities=frozenset({HarnessCapability.SHELL, HarnessCapability.WEB_SEARCH}),
        ),
        source=PackageSource(kind="local", uri=".", unsafe_local=True),
    )


def _template(
    *,
    name: str,
    model: str,
    environment: EnvironmentManifest,
    package: HarnessPackage | None = None,
) -> AgentTemplate:
    if package is None:
        return AgentTemplate(name=name, model=model, environment=environment.identity)
    binding = HarnessBinding.from_package(package)
    return AgentTemplate(
        name=name,
        model=model,
        environment=environment.identity,
        harness=binding,
        harness_package=package,
        stamp=resolve_harness_stamp(environment, package),
    )


def _job(*, retries: int = 0, attempts: int = 2) -> JobSpec:
    first = _harness("first")
    second = _harness("second")
    environment = EnvironmentManifest(
        name="word-game",
        tasks=(
            TaskDefinition(task_id="easy", input="one"),
            TaskDefinition(task_id="hard", input="two"),
        ),
        harness_policy=HarnessPolicy(
            allowed_harnesses=(
                HarnessBinding.from_package(first),
                HarnessBinding.from_package(second),
            )
        ),
    )
    benchmark = BenchmarkDefinition(
        name="ordered",
        environment=environment.identity,
        task_ids=("hard", "easy"),
    )
    agents = (
        AgentBinding(template=_template(name="alpha", model="openai/a", environment=environment)),
        AgentBinding(template=_template(name="beta", model="anthropic/b", environment=environment)),
    )
    return JobSpec(
        environment=environment,
        benchmark=benchmark,
        agents=agents,
        n_attempts=attempts,
        retry=RetryPolicy(max_retries=retries),
    )


def test_plan_is_deterministic_and_ordered_agent_task_attempt() -> None:
    first = _job().plan()
    second = _job().plan()

    assert first == second
    assert first.trial_count == 8
    assert [trial.agent_name for trial in first.trials] == ["alpha"] * 4 + ["beta"] * 4
    assert [trial.task_id for trial in first.trials[:4]] == ["hard", "hard", "easy", "easy"]
    assert [trial.attempt for trial in first.trials[:4]] == [1, 2, 1, 2]
    assert len({trial.trial_id for trial in first.trials}) == 8
    assert all(trial.harness is None for trial in first.trials)


def test_retries_do_not_create_attempts_or_change_trial_ids() -> None:
    without_retries = _job(retries=0).plan()
    with_retries = _job(retries=5).plan()

    assert with_retries.trial_count == without_retries.trial_count
    assert [item.trial_id for item in with_retries.trials] == [
        item.trial_id for item in without_retries.trials
    ]
    assert with_retries.spec_hash != without_retries.spec_hash


def test_hashes_and_locks_change_with_semantic_content() -> None:
    baseline = _job().plan()
    changed = _job(attempts=3).plan()

    assert baseline.job_id != changed.job_id
    assert baseline.lock.task_set_hash == changed.lock.task_set_hash
    assert baseline.lock.benchmark_hash == changed.lock.benchmark_hash
    assert baseline.lock.agent_hashes == changed.lock.agent_hashes


def test_nonlocal_harness_requires_digest_and_local_unsigned_requires_trust() -> None:
    for source in (
        {"kind": "oci", "uri": "registry.example/harness:latest"},
        {"kind": "local", "uri": "."},
    ):
        try:
            PackageSource.model_validate(source)
        except ValidationError:
            pass
        else:  # pragma: no cover
            raise AssertionError("unlocked source was accepted")
    try:
        PackageSource(kind="local", uri=".", trusted=True)
    except ValidationError as exc:
        assert "unsafe_local=true" in str(exc)
    else:
        raise AssertionError("trusted=true bypassed unsigned local source checks")


def test_agent_and_benchmark_must_match_environment() -> None:
    job = _job()
    bad_environment = job.environment.model_copy(update={"name": "other"})
    try:
        JobSpec(
            environment=bad_environment,
            benchmark=job.benchmark,
            agents=job.agents,
        )
    except ValidationError as exc:
        assert "environment identity" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("incompatible environment was accepted")


def test_agent_template_harness_is_optional() -> None:
    schema = AgentTemplate.model_json_schema()
    assert "harness" not in schema.get("required", [])
    assert schema["properties"]["harness"]["anyOf"]


def test_native_action_command_kind_requires_argv() -> None:
    try:
        NativeAction(name="ping", description="Ping", kind="command")
    except ValidationError as exc:
        assert "non-empty command" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("command action without argv was accepted")


def test_resolve_harness_stamp_derives_network_denials() -> None:
    package = _harness("web")
    isolated = EnvironmentManifest(
        name="isolated",
        tasks=(TaskDefinition(task_id="t", input="x"),),
    )
    stamp = resolve_harness_stamp(isolated, package)
    assert HarnessCapability.SHELL in stamp.granted
    assert HarnessCapability.WEB_SEARCH in stamp.denied
    assert stamp.denial_reasons[HarnessCapability.WEB_SEARCH.value] == "environment network=none"

    open_env = EnvironmentManifest(
        name="open",
        tasks=(TaskDefinition(task_id="t", input="x"),),
        runtime=EnvironmentRuntime(network=NetworkMode.FULL),
    )
    open_stamp = resolve_harness_stamp(open_env, package)
    assert HarnessCapability.WEB_SEARCH in open_stamp.granted


def test_declared_harness_cannot_be_planned() -> None:
    package = _harness("declared", runnable=False)
    environment = EnvironmentManifest(
        name="word-game",
        tasks=(TaskDefinition(task_id="easy", input="one"),),
        harness_policy=HarnessPolicy(allowed_harnesses=(HarnessBinding.from_package(package),)),
    )
    try:
        JobSpec(
            environment=environment,
            benchmark=BenchmarkDefinition(
                name="b",
                environment=environment.identity,
                task_ids=("easy",),
            ),
            agents=(
                AgentBinding(
                    template=_template(
                        name="alpha",
                        model="openai/a",
                        environment=environment,
                        package=package,
                    )
                ),
            ),
        )
    except ValidationError as exc:
        assert "declared but not runnable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("declared harness was accepted for a job")


def test_local_target_is_excluded_when_network_is_isolated() -> None:
    environment = EnvironmentManifest(
        name="isolated",
        tasks=(TaskDefinition(task_id="t", input="x"),),
    )
    assert ExecutionTarget.LOCAL not in environment.runtime.available_targets()
    try:
        JobSpec(
            environment=environment,
            benchmark=BenchmarkDefinition(
                name="b", environment=environment.identity, task_ids=("t",)
            ),
            agents=(
                AgentBinding(
                    template=AgentTemplate(name="a", model="m", environment=environment.identity)
                ),
            ),
            runtime=RuntimeSpec(provider="local", unsafe_local=True),
        )
    except ValidationError as exc:
        assert "cannot enforce network=none" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("local target was accepted for an isolated environment")


def test_job_spec_json_roundtrip_keeps_environment_identity() -> None:
    environment = EnvironmentManifest(
        name="world",
        tasks=(TaskDefinition(task_id="t1", input="go"),),
        runtime=EnvironmentRuntime(network=NetworkMode.FULL),
    )
    spec = JobSpec(
        environment=environment,
        benchmark=BenchmarkDefinition(
            name="bench",
            environment=environment.identity,
            task_ids=("t1",),
        ),
        agents=(
            AgentBinding(
                template=AgentTemplate(name="a", model="m", environment=environment.identity)
            ),
        ),
        runtime=RuntimeSpec(provider="docker"),
    )
    restored = JobSpec.model_validate_json(spec.model_dump_json())
    assert restored.environment.identity == spec.environment.identity
    assert restored.benchmark.environment == restored.environment.identity
