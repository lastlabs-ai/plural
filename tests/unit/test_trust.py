"""Every Trial gets a trust tier, and a sandbox that can't isolate the App host fails closed."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeProvider

from plural.agents import AgentBinding, AgentDefinition
from plural.apps.definition import AppAction, AppDefinition
from plural.common import ErrorCode
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.execution import JobRunner, JobStore
from plural.execution.engine import (
    GATEWAY_KEY_MAX_SECONDS,
    ISOLATION_REQUIRED,
    PACKAGE_INDEX_HOSTS,
    default_allowlist,
    sandbox_lifetime,
)
from plural.jobs import JobSpec, TaskJobSource
from plural.sandbox import NetworkMode, SandboxHandle, SandboxRequirements
from plural.sandbox.conformance import CHECKS, CheckResult, ConformanceReport, save_report
from plural.tasks import TaskDefinition
from plural.trust import TrustFacts, trust_tier
from plural.verifiers import DeterministicVerifier, Episode, VerifierOutput, WeightedVerifier

PINNED = "sha256:" + "a" * 64


def _scored(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1)


def _task(**runtime: Any) -> TaskDefinition:
    game = AppDefinition(
        name="game",
        kind="python",
        python="game.py:Game",
        actions=(AppAction(name="move", description="Make a move."),),
    )
    return TaskDefinition(
        task_id="desk-task",
        instructions="Do the work.",
        environment=EnvironmentDefinition(
            name="desk",
            apps=(game,),
            runtime=EnvironmentRuntime(provider="docker", **runtime),
        ),
        verifiers=(WeightedVerifier(verifier=DeterministicVerifier(name="ok", check=_scored)),),
    )


def _spec(task: TaskDefinition) -> JobSpec:
    return JobSpec(
        source=TaskJobSource(task=task),
        agents=(AgentBinding(agent=AgentDefinition(name="agent", model="test/model")),),
    )


class _Pinned(FakeProvider):
    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        handle = await super().create(requirements)
        return handle.model_copy(update={"image_identity": PINNED})


def _passed(provider: str) -> ConformanceReport:
    return ConformanceReport(
        provider=provider,
        provider_version=provider,
        checked_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        checks=tuple(
            CheckResult(id=key, title=title, passed=True) for key, title in CHECKS.items()
        ),
    )


@pytest.mark.parametrize(
    ("facts", "tier", "reason"),
    [
        ({"provider": "local", "app_isolation": "none"}, "unverified", "local Runtime"),
        ({"provider": "docker", "app_isolation": "none"}, "unverified", "shared an OS user"),
        ({"provider": "docker", "app_isolation": "os_user"}, "standard", "open internet"),
        (
            {
                "provider": "daytona",
                "app_isolation": "os_user",
                "network": "allowlist",
                "image_identity": "python:3.12-slim",
                "conformance": "passed",
                "host_report_signed": True,
            },
            "standard",
            "not pinned",
        ),
        (
            {
                "provider": "daytona",
                "app_isolation": "os_user",
                "network": "allowlist",
                "image_identity": PINNED,
                "image_pinned": True,
                "conformance": "failed",
                "conformance_failures": ("NET-2",),
                "host_report_signed": True,
            },
            "standard",
            "failed conformance: NET-2",
        ),
        (
            {
                "provider": "daytona",
                "app_isolation": "os_user",
                "network": "no-network",
                "image_identity": PINNED,
                "image_pinned": True,
                "conformance": "passed",
                "host_report_signed": False,
            },
            "standard",
            "not signed",
        ),
        (
            {
                "provider": "daytona",
                "app_isolation": "os_user",
                "network": "allowlist",
                "image_identity": "snap",
                "image_pinned": True,
                "conformance": "passed",
                "host_report_signed": True,
            },
            "verified",
            None,
        ),
        (
            {
                "provider": "daytona",
                "network": "allowlist",
                "image_identity": "snap",
                "image_pinned": True,
                "conformance": "passed",
            },
            "unverified",
            "never started",
        ),
        (
            {
                "provider": "daytona",
                "app_isolation": "os_user",
                "network": "allowlist",
                "image_identity": "snap",
                "image_pinned": True,
                "conformance": "passed",
            },
            "standard",
            "did not finish its report",
        ),
    ],
)
def test_the_tier_follows_from_what_the_engine_observed(
    facts: dict[str, Any], tier: str, reason: str | None
) -> None:
    assessment = trust_tier(TrustFacts(**facts))
    assert assessment.tier == tier
    if reason is None:
        assert assessment.reasons == ()
    else:
        assert any(reason in line for line in assessment.reasons), assessment.reasons


async def test_a_sandbox_that_cannot_isolate_the_app_host_fails_closed(tmp_path: Path) -> None:
    provider = FakeProvider("docker", isolates=False)

    result = await JobRunner(
        _spec(_task()), provider=provider, store=JobStore(tmp_path / "j"), environ=dict(os.environ)
    ).run()

    (trial,) = result.trials
    assert trial.status == "failed"
    assert trial.error_code is ErrorCode.ENVIRONMENT_FAILED
    assert trial.error_message == ISOLATION_REQUIRED
    assert "isolation: best_effort" in ISOLATION_REQUIRED
    assert provider.harness_runs == 0
    assert not any(path.startswith(".plural/apps/") for path in provider.uploads)


async def test_best_effort_runs_anyway_and_is_marked_unverified(tmp_path: Path) -> None:
    provider = FakeProvider("docker", isolates=False)

    result = await JobRunner(
        _spec(_task(isolation="best_effort")),
        provider=provider,
        store=JobStore(tmp_path / "j"),
        environ=dict(os.environ),
    ).run()

    (trial,) = result.trials
    assert trial.status == "succeeded", trial.error_message
    assert trial.trust is not None and trial.trust.tier == "unverified"
    assert "the App host shared an OS user with the Agent" in trial.trust.reasons


async def test_an_isolated_trial_says_what_keeps_it_from_verified(tmp_path: Path) -> None:
    provider = FakeProvider("docker")

    result = await JobRunner(
        _spec(_task()), provider=provider, store=JobStore(tmp_path / "j"), environ=dict(os.environ)
    ).run()

    (trial,) = result.trials
    assert trial.status == "succeeded", trial.error_message
    assert trial.trust is not None and trial.trust.tier == "standard"
    assert trial.trust.facts.app_isolation == "os_user"
    assert trial.trust.facts.host_report_signed is True
    reasons = " | ".join(trial.trust.reasons)
    assert "open internet" in reasons
    assert "not pinned" in reasons
    assert "no conformance report for docker" in reasons


async def test_a_recorded_trial_on_a_conforming_provider_is_verified(tmp_path: Path) -> None:
    save_report(_passed("docker"))
    provider = _Pinned("docker")
    minted: list[int] = []

    def gateway_keys(trial_id: str, execution_id: int, ttl: int) -> str:
        minted.append(ttl)
        return "plural_trial-execution-key"

    environ = {
        **os.environ,
        "PLURAL_API_KEY": "plural_the-users-own-key",
        "PLURAL_API_URL": "https://api.example.test",
    }
    result = await JobRunner(
        _spec(_task(allowed_hosts=("data.example.test",))),
        provider=provider,
        store=JobStore(tmp_path / "j"),
        environ=environ,
        gateway_keys=gateway_keys,
    ).run()

    (trial,) = result.trials
    assert trial.status == "succeeded", trial.error_message
    assert trial.trust is not None
    assert (trial.trust.tier, trial.trust.reasons) == ("verified", ())
    (requirements,) = provider.created
    assert requirements.network is NetworkMode.ALLOWLIST
    assert "api.example.test" in requirements.network_allowlist
    assert "data.example.test" in requirements.network_allowlist
    assert set(PACKAGE_INDEX_HOSTS) <= set(requirements.network_allowlist)
    assert minted and minted[0] >= sandbox_lifetime(_task())


async def test_every_sandbox_is_labeled_and_cannot_outlive_its_trial(tmp_path: Path) -> None:
    provider = FakeProvider("docker")
    spec = _spec(_task())

    await JobRunner(
        spec, provider=provider, store=JobStore(tmp_path / "j"), environ=dict(os.environ)
    ).run()

    (requirements,) = provider.created
    trial = spec.plan().trials[0]
    assert requirements.labels["plural.job"] == spec.job_id
    assert requirements.labels["plural.trial"] == trial.trial_id
    assert requirements.labels["plural.execution"] == "0"
    assert requirements.labels["plural.owner"]
    assert requirements.lifetime_seconds == sandbox_lifetime(_task())
    assert requirements.isolation == "required"
    assert requirements.network is NetworkMode.PUBLIC


def test_the_default_allowlist_names_the_gateway_and_the_package_index() -> None:
    hosts = default_allowlist({"PLURAL_API_URL": "https://api.pluralintel.com/v1"}, ("x.test",))
    assert hosts[0] == "api.pluralintel.com"
    assert "x.test" in hosts and set(PACKAGE_INDEX_HOSTS) <= set(hosts)
    assert len(hosts) == len(set(hosts))


def test_a_gateway_key_lives_as_long_as_the_sandbox_up_to_a_week() -> None:
    task = _task()
    environment = task.environment.model_copy(
        update={"limits": task.environment.limits.model_copy(update={"max_seconds": 3 * 86_400})}
    )
    long = task.model_copy(update={"environment": environment})
    assert sandbox_lifetime(long) > 86_400
    assert GATEWAY_KEY_MAX_SECONDS == 7 * 86_400
