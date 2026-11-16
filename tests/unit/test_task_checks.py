"""Task checks, reference policies, long episodes, and score summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plural.common import HarnessProtocol
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.execution.engine import _harness_timeout
from plural.harness.retrieval import package_files, reference_files, source_digest
from plural.integrity.checks import ProbeResult, TaskCheck, judge_probe
from plural.integrity.leaks import LeakFinding
from plural.jobs import TrialResult, VerifierResult
from plural.stats import score_summary
from plural.tasks import TaskDefinition


def _trial(score: float | None, status: str = "succeeded", **scores: float) -> TrialResult:
    results = (
        VerifierResult.model_construct(
            verifier="quote-check", score=score or 0.0, scores=scores, feedback=""
        ),
    )
    return TrialResult.model_construct(
        status=status,
        score=score,
        verifier_results=results if scores else (),
        receipt=None,
        error_message="sandbox gone" if status != "succeeded" else None,
    )


def test_the_reference_must_reach_the_threshold() -> None:
    assert judge_probe("reference", _trial(1.0), 1.0).status == "passed"
    failed = judge_probe("reference", _trial(0.5, price_correct=0.0, decision_correct=1.0), 1.0)
    assert failed.status == "failed"
    assert failed.failed_checks == ("price_correct",)


def test_doing_nothing_must_fail() -> None:
    assert judge_probe("noop", _trial(0.0), 1.0).status == "passed"
    assert judge_probe("echo", _trial(1.0), 1.0).status == "failed"
    assert judge_probe("noop", _trial(None, status="failed"), 1.0).status == "error"


def test_a_random_pass_is_a_warning_and_an_info_leak_is_not_a_problem() -> None:
    check = TaskCheck(
        task="t",
        version="1.0.0",
        content_hash="sha256:0",
        checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        probes=(
            ProbeResult(probe="reference", status="passed"),
            ProbeResult(probe="random", status="failed", detail="random passes"),
        ),
        leaks=(LeakFinding(kind="not_scanned", path="a.png", message="image", severity="info"),),
    )
    assert check.problems == ()
    assert check.warnings == ("random passes",)
    assert check.passed


def test_a_reference_policy_is_neither_shipped_nor_hashed(tmp_path: Path) -> None:
    (tmp_path / "environment.yaml").write_text("name: desk\nreference: reference.py:solve\n")
    (tmp_path / "environment.py").write_text("class Desk: ...\n")
    (tmp_path / "reference.py").write_text("def solve(task): return 1\n")
    assert reference_files(tmp_path) == {"reference.py"}
    assert [name for name, _ in package_files(tmp_path)] == ["environment.py", "environment.yaml"]

    before = source_digest(tmp_path)
    (tmp_path / "reference.py").write_text("def solve(task): return 2\n")
    assert source_digest(tmp_path) == before


def _task(max_seconds: float, timeout_seconds: int = 600) -> TaskDefinition:
    return TaskDefinition.model_construct(
        task_id="long",
        instructions="Work for a while.",
        environment=EnvironmentDefinition(
            name="desk",
            runtime=EnvironmentRuntime(provider="docker", timeout_seconds=timeout_seconds),
            limits={"max_seconds": max_seconds},
        ),
    )


def test_a_harness_runs_as_long_as_the_episode_allows() -> None:
    other = HarnessProtocol(name="h", revision="1.0.0", command=("codex", "exec"))
    native = HarnessProtocol(
        name="n", revision="1.0.0", command=("python", "native_runner.py", "native.actions.v1")
    )
    two_days = 2 * 86_400
    assert _harness_timeout(_task(two_days, timeout_seconds=600), other, {}) == two_days
    assert _harness_timeout(_task(two_days), native, {}) > two_days


def test_a_score_summary_reads_as_one_line() -> None:
    attempts: dict[str, Any] = {"a": [1.0, 1.0], "b": [1.0, 0.0], "c": [None, None]}
    summary = score_summary(attempts, seed=3)
    assert summary.tasks == 2
    assert summary.pass_hat_k == 0.5
    assert summary.summary.startswith("score 0.75 (95% ")
    assert summary.summary.endswith("pass^2 50%, over 2 Tasks")
