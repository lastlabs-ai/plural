"""The conformance suite reports every check, caches by provider version, and finds orphans."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from fakes import FakeProvider

from plural.sandbox import SandboxHandle, SandboxRequirements
from plural.sandbox.conformance import (
    CHECKS,
    CheckResult,
    ConformanceReport,
    conformance_status,
    load_report,
    report_path,
    run_conformance,
    save_report,
)
from plural.sandbox.models import SandboxSummary
from plural.sandbox.sweep import (
    JOB_LABEL,
    OWNER_LABEL,
    live_jobs,
    owner_label,
    sweep,
    trial_labels,
)


class _Broken(FakeProvider):
    async def create(self, requirements: SandboxRequirements) -> SandboxHandle:
        raise RuntimeError("quota exceeded")


class _Listed(FakeProvider):
    def __init__(self, items: list[SandboxSummary]) -> None:
        super().__init__("daytona")
        self.items = items
        self.removed: list[str] = []

    async def list_sandboxes(self, labels: Mapping[str, str]) -> tuple[SandboxSummary, ...]:
        return tuple(
            item
            for item in self.items
            if all(item.labels.get(key) == value for key, value in labels.items())
        )

    async def delete_sandbox(self, sandbox_id: str) -> None:
        if sandbox_id == "stuck":
            raise RuntimeError("busy")
        self.removed.append(sandbox_id)


def _summary(sandbox_id: str, owner: str, job: str) -> SandboxSummary:
    return SandboxSummary(
        sandbox_id=sandbox_id,
        provider="daytona",
        labels={OWNER_LABEL: owner, JOB_LABEL: job},
        state="started",
    )


async def test_a_provider_that_cannot_start_a_sandbox_fails_every_check() -> None:
    seen: list[CheckResult] = []
    report = await run_conformance(_Broken("broken"), progress=seen.append)
    assert [item.id for item in report.checks] == list(CHECKS)
    assert not report.passed
    assert report.failures == tuple(CHECKS)
    assert report.summary == "0/14"
    assert {item.id for item in seen} == set(CHECKS)
    assert "quota exceeded" in report.checks[0].detail


async def test_reports_are_cached_per_provider_version_and_read_back(tmp_path: Path) -> None:
    provider = FakeProvider("docker")
    assert await conformance_status(provider) == ("missing", ())
    checks = [
        CheckResult(id=key, title=title, passed=key != "NET-2") for key, title in CHECKS.items()
    ]
    report = ConformanceReport(
        provider="docker",
        provider_version="docker",
        checked_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        checks=tuple(checks),
    )
    path = save_report(report)
    assert path == report_path("docker", "docker")
    assert path.name == "docker--docker--1.0.json"
    assert load_report("docker", "docker") == report
    assert await conformance_status(provider) == ("failed", ("NET-2",))
    assert load_report("docker", "docker-30") is None


async def test_a_sweep_removes_only_your_sandboxes_whose_job_is_not_running() -> None:
    provider = _Listed(
        [
            _summary("old", "me", "job-done"),
            _summary("stuck", "me", "job-done"),
            _summary("running", "me", "job-live"),
            _summary("theirs", "someone-else", "job-done"),
        ]
    )
    listed = await sweep(provider, owner="me", live=frozenset({"job-live"}))
    assert [item.sandbox_id for item in listed.orphans] == ["old", "stuck"]
    assert [item.sandbox_id for item in listed.live] == ["running"]
    assert listed.deleted == () and provider.removed == []

    swept = await sweep(provider, owner="me", live=frozenset({"job-live"}), delete=True)
    assert swept.deleted == ("old",)
    assert swept.failed == {"stuck": "busy"}


def test_a_job_is_live_while_it_has_no_result_and_wrote_recently(tmp_path: Path) -> None:
    for name in ("running", "finished", "abandoned"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "job.json").write_text("{}")
    (tmp_path / "finished" / "result.json").write_text("{}")
    old = time.time() - 3_600
    os.utime(tmp_path / "abandoned" / "job.json", (old, old))
    assert live_jobs([tmp_path, tmp_path / "missing"]) == frozenset({"running"})


def test_sandbox_labels_name_the_owner_job_trial_and_execution() -> None:
    labels = trial_labels(
        job="job_1", trial="trl_2", execution="0", environ={"PLURAL_SANDBOX_OWNER": "CI Bot!"}
    )
    assert labels == {
        "plural.owner": "CI-Bot",
        "plural.job": "job_1",
        "plural.trial": "trl_2",
        "plural.execution": "0",
    }
    assert owner_label({"USER": "taylor"})
