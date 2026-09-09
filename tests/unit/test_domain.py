from __future__ import annotations

from pydantic import ValidationError

from plural.domain import (
    AgentSpec,
    BenchmarkDefinition,
    EnvironmentManifest,
    HarnessBinding,
    HarnessManifest,
    HarnessPackage,
    JobSpec,
    PackageSource,
    RetryPolicy,
    TaskDefinition,
)


def _harness(name: str = "chat") -> HarnessPackage:
    return HarnessPackage(
        manifest=HarnessManifest(name=name, command=("python", "harness.py")),
        source=PackageSource(kind="local", uri=".", unsafe_local=True),
    )


def _job(*, retries: int = 0, attempts: int = 2) -> JobSpec:
    first = HarnessBinding.from_package(_harness("first"))
    second = HarnessBinding.from_package(_harness("second"))
    environment = EnvironmentManifest(
        name="word-game",
        tasks=(
            TaskDefinition(task_id="easy", input="one"),
            TaskDefinition(task_id="hard", input="two"),
        ),
        allowed_harnesses=(first, second),
    )
    benchmark = BenchmarkDefinition(
        name="ordered",
        environment=environment.identity,
        task_ids=("hard", "easy"),
    )
    agents = (
        AgentSpec(
            name="alpha",
            model="openai/a",
            environment=environment.identity,
            harness=first,
        ),
        AgentSpec(
            name="beta",
            model="anthropic/b",
            environment=environment.identity,
            harness=second,
        ),
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


def test_one_agent_has_exactly_one_harness_binding() -> None:
    schema = AgentSpec.model_json_schema()
    assert "harness" in schema["required"]
    assert "harnesses" not in schema["properties"]
