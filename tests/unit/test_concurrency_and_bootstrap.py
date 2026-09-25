"""Concurrency sizing, live Job progress, and Plural inside non-local sandboxes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from fakes import FakeProvider

from plural.agents import AgentBinding, AgentDefinition
from plural.common import ExecutionTarget
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.execution import JobRunner, JobStore
from plural.execution.bootstrap import (
    SEARCH_PATH,
    PluralBootstrapError,
    PluralDistribution,
    install_plural,
    needs_plural,
    prepare_requirements,
    resolve_distribution,
)
from plural.execution.capacity import recommend_concurrency
from plural.execution.engine import job_progress
from plural.jobs import BenchmarkJobSource, JobSpec
from plural.sandbox.models import (
    ExecRequest,
    ExecResult,
    NetworkMode,
    ResourceRequirements,
    SandboxHandle,
    SandboxRequirements,
)
from plural.tasks import BenchmarkDefinition, TaskDefinition
from plural.verifiers import DeterministicVerifier, VerifierRuntime, WeightedVerifier


def _task(
    name: str,
    provider: str = "docker",
    *,
    reset: tuple[str, ...] = (),
    resources: ResourceRequirements | None = None,
) -> TaskDefinition:
    target = {
        "local": ExecutionTarget.LOCAL,
        "docker": ExecutionTarget.DOCKER,
    }.get(provider, ExecutionTarget.REMOTE)
    local = {"allow_unsafe_local": True, "network": "public"} if provider == "local" else {}
    return TaskDefinition(
        task_id=name,
        instructions=f"Solve {name}",
        environment=EnvironmentDefinition(
            name=f"env-{name}",
            runtime=EnvironmentRuntime(
                provider=provider,
                targets=frozenset({target}),
                resources=resources or ResourceRequirements(),
                **local,
            ),
            reset_command=reset,
        ),
        verifiers=(
            WeightedVerifier(
                verifier=DeterministicVerifier(
                    name="exact",
                    command=("python", "verify.py"),
                    runtime=VerifierRuntime(provider=provider),
                )
            ),
        ),
    )


def _spec(
    tasks: Sequence[TaskDefinition], *, auth_mode: str = "environment", **kwargs: int
) -> JobSpec:
    agent = AgentDefinition(name="agent", model="test/model", auth_mode=auth_mode)
    return JobSpec(
        source=BenchmarkJobSource(benchmark=BenchmarkDefinition(name="suite", tasks=tuple(tasks))),
        agents=(AgentBinding(agent=agent),),
        **kwargs,
    )


def test_auto_runs_every_trial_at_once_when_the_machine_and_model_allow() -> None:
    spec = _spec([_task(f"case-{index}", "local") for index in range(7)])

    advice = recommend_concurrency(
        spec, trial_count=7, environ={"PLURAL_API_KEY": "k"}, cpu_count=8, memory_mb=16_384
    )

    assert advice.trials == 7
    assert advice.reason == "every Trial at once"


def test_auto_is_bounded_by_docker_memory_per_container() -> None:
    spec = _spec(
        [_task("big", resources=ResourceRequirements(cpu=1, memory_mb=2048))],
    )

    advice = recommend_concurrency(spec, trial_count=100, environ={}, cpu_count=14, memory_mb=8192)

    # Half of 8 GB for 2 GB containers.
    assert advice.trials == 2
    assert advice.reason == "docker memory on this machine"


def test_auto_runs_one_trial_at_a_time_against_a_model_served_on_this_machine() -> None:
    spec = _spec([_task(f"case-{index}", "local") for index in range(5)])
    environ = {"OPENAI_BASE_URL": "http://127.0.0.1:11434/v1"}

    advice = recommend_concurrency(spec, trial_count=5, environ=environ, cpu_count=8)

    assert advice.trials == 1
    assert "PLURAL_MODEL_CONCURRENCY" in advice.reason
    raised = recommend_concurrency(
        spec, trial_count=5, environ={**environ, "PLURAL_MODEL_CONCURRENCY": "4"}, cpu_count=8
    )
    assert raised.trials == 4


def test_auto_uses_the_remote_sandbox_quota_and_ignores_this_machine_when_hosted() -> None:
    spec = _spec([_task(f"case-{index}", "daytona") for index in range(40)])

    remote = recommend_concurrency(spec, trial_count=40, environ={}, cpu_count=1, memory_mb=512)
    quota = recommend_concurrency(
        spec, trial_count=40, environ={"PLURAL_MAX_SANDBOXES": "25"}, cpu_count=1
    )
    hosted = recommend_concurrency(
        _spec([_task("one", "local")]), trial_count=40, environ={}, cpu_count=1, hosted=True
    )

    assert remote.trials == 10
    assert quota.trials == 25
    assert hosted.trials == 40


def test_a_credential_free_agent_is_not_limited_by_a_local_model_url() -> None:
    spec = _spec([_task("one", "local"), _task("two", "local")], auth_mode="none")

    advice = recommend_concurrency(
        spec, trial_count=2, environ={"OPENAI_BASE_URL": "http://localhost:8000"}, cpu_count=4
    )

    assert advice.trials == 2


async def test_job_progress_reports_partial_results_while_trials_run(tmp_path: Path) -> None:
    provider = FakeProvider("docker", delay=0.01)
    spec = _spec(
        [_task(f"case-{index}") for index in range(4)], concurrency=4, per_runtime_concurrency=4
    )
    store = JobStore(tmp_path / "jobs")
    await JobRunner(spec, provider=provider, store=store).run()
    assert provider.max_active >= 2
    # Rewind to mid-run: the Job result and one Trial result are not written yet.
    (store.job_path(spec.job_id) / "result.json").unlink()
    trials = sorted((store.job_path(spec.job_id) / "trials").iterdir())
    (trials[2] / "result.json").unlink()

    progress = job_progress(store, spec.job_id)

    assert (progress.planned, progress.finished, progress.running) == (4, 3, 1)
    assert progress.succeeded == 3
    assert trials[2].name not in {item.receipt.trial_id for item in progress.trials}
    assert progress.aggregates[0].count == 3
    assert progress.aggregates[0].coverage == pytest.approx(0.75)


def test_only_sandboxes_that_run_plural_code_need_it() -> None:
    plain = _task("plain")
    runner = _task(
        "runner", reset=("python", "-m", "plural.environments.runner", "env.py:Env", "reset")
    )

    assert not needs_plural(plain)
    assert needs_plural(runner)
    assert needs_plural(plain, None, ("python", "-m", "plural.verifiers.check"))


def test_runtime_version_selects_this_code_or_a_release() -> None:
    import plural

    current = resolve_distribution(None)
    pinned = resolve_distribution("v0.16.0")

    assert current.version == plural.__version__
    assert current.source is not None
    assert not any("plural" in item.split(";")[0] for item in current.requirements)
    names = {name for name, _data in current.files()}
    assert "plural/__init__.py" in names
    assert f"plural-{plural.__version__}.dist-info/METADATA" in names
    assert pinned == PluralDistribution(version="0.16.0", requirements=("plural==0.16.0",))
    assert pinned.files() == []


class _Sandbox(FakeProvider):
    """Answers the probe with whatever version was installed so far."""

    def __init__(self, *, preinstalled: str | None = None, install_exit: int = 0) -> None:
        super().__init__("daytona")
        self.version = preinstalled
        self.install_exit = install_exit
        self.commands: list[ExecRequest] = []

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        self.commands.append(request)
        if request.command[-1].strip().endswith("print(json.dumps(info))"):
            info = {"version": self.version} if self.version else {"error": "ModuleNotFound"}
            return ExecResult(exit_code=0, stdout=json.dumps(info).encode(), duration_seconds=0)
        if self.install_exit == 0:
            self.version = "9.9.9"
        return ExecResult(exit_code=self.install_exit, stderr=b"no pip", duration_seconds=0)


async def _handle(provider: _Sandbox) -> SandboxHandle:
    return await provider.create(SandboxRequirements())


async def test_install_uploads_this_code_and_its_dependencies_once(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("__version__ = '9.9.9'\n")
    provider = _Sandbox()
    handle = await _handle(provider)
    distribution = PluralDistribution(
        version="9.9.9", requirements=("pydantic>=2",), source=tmp_path
    )

    env = await install_plural(provider, handle, distribution, network=NetworkMode.PUBLIC)

    assert env == {"PYTHONPATH": SEARCH_PATH}
    assert ".plural-runtime/plural.zip" in provider.files[handle.sandbox_id]
    install = provider.commands[1]
    assert install.command[-1] == "pydantic>=2"
    assert install.command[-2] == "/workspace/.plural-runtime/plural.zip"


async def test_an_image_with_the_same_version_is_used_as_it_is() -> None:
    provider = _Sandbox(preinstalled="0.16.0")
    handle = await _handle(provider)
    distribution = resolve_distribution("0.16.0")

    await install_plural(provider, handle, distribution, network=NetworkMode.NONE)

    assert len(provider.commands) == 1
    assert provider.files[handle.sandbox_id] == {}


async def test_install_failures_explain_what_to_change() -> None:
    offline = _Sandbox()
    with pytest.raises(PluralBootstrapError, match="no network"):
        await install_plural(
            offline,
            await _handle(offline),
            resolve_distribution("0.16.0"),
            network=NetworkMode.NONE,
        )
    broken = _Sandbox(install_exit=1)
    with pytest.raises(PluralBootstrapError, match="no pip"):
        await install_plural(
            broken,
            await _handle(broken),
            resolve_distribution("0.16.0"),
            network=NetworkMode.PUBLIC,
        )


async def test_docker_gets_an_image_built_once_with_plural_layered_on() -> None:
    seen: dict[str, str] = {}

    class _Docker(FakeProvider):
        async def extend_image(
            self, requirements: SandboxRequirements, context: Path, key: str
        ) -> SandboxRequirements:
            seen["dockerfile"] = (context / "Dockerfile").read_text()
            seen["requirements"] = (context / "requirements.txt").read_text()
            seen["init"] = str((context / "site" / "plural" / "__init__.py").is_file())
            seen["key"] = key
            return requirements.model_copy(update={"image": "plural-runtime:test"})

    distribution = resolve_distribution(None)
    requirements = await prepare_requirements(
        _Docker("docker"), SandboxRequirements(image="python:3.12-slim"), distribution
    )

    assert requirements.image == "plural-runtime:test"
    assert "FROM ${BASE}" in seen["dockerfile"]
    assert "ENV PYTHONPATH=/opt/plural-runtime/site" in seen["dockerfile"]
    assert "pydantic" in seen["requirements"]
    assert seen["init"] == "True"
    assert seen["key"] == distribution.key
    unchanged = SandboxRequirements(image="python:3.12-slim")
    assert await prepare_requirements(_Sandbox(), unchanged, distribution) is unchanged


def test_docker_points_loopback_urls_at_the_host() -> None:
    from plural.sandbox.docker import _host_url

    assert _host_url("http://localhost:8005/v1") == "http://host.docker.internal:8005/v1"
    assert _host_url("http://127.0.0.1/v1") == "http://host.docker.internal/v1"
    assert _host_url("https://api.pluralintel.com/v1") == "https://api.pluralintel.com/v1"
    assert _host_url("localhost") == "localhost"
