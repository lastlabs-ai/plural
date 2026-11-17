"""Deterministic detectors flag what a Trial's record shows, without a model."""

from __future__ import annotations

import json
from typing import Any

import pytest

from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.integrity.detectors import (
    TrialEvidence,
    canary_sightings,
    detect,
    egress_denials,
    grader_file_touches,
    suspicious_success,
    verifier_files,
)
from plural.jobs import VerifierResult
from plural.sandbox import DownloadedFile
from plural.tasks import TaskDefinition
from plural.verifiers import DeterministicVerifier, WeightedVerifier

CANARY = "plural-canary-5f1e0c3a9b7d4e21"


def _task(expected: Any = None) -> TaskDefinition:
    verifier = DeterministicVerifier(name="quote", check={"python": "verify.py:check"})
    return TaskDefinition(
        task_id="quote-001",
        instructions="Quote 20 tons.",
        environment=EnvironmentDefinition(name="quoting", runtime=EnvironmentRuntime.local()),
        verifiers=(WeightedVerifier(verifier=verifier),),
        expected=expected,
    )


def _steps(*arguments: dict[str, Any]) -> DownloadedFile:
    lines = [
        json.dumps({"action": "read_file", "arguments": item, "step": index})
        for index, item in enumerate(arguments, start=1)
    ]
    return DownloadedFile(path="steps.jsonl", data=("\n".join(lines) + "\n").encode())


def _passed() -> tuple[VerifierResult, ...]:
    return (
        VerifierResult(
            verifier_name="quote",
            verifier_digest="sha256:" + "0" * 64,
            kind="deterministic",
            status="succeeded",
            score=1.0,
        ),
    )


def test_a_clean_trial_has_no_findings() -> None:
    evidence = TrialEvidence(
        task=_task({"total": 1200}),
        artifacts=(_steps({"path": "catalog.csv"}),),
        logs=b"read the catalog\n",
        verifier_results=_passed(),
        answer={"total": 1200},
        canary=CANARY,
    )
    assert detect(evidence) == ()


def test_naming_a_grader_file_is_critical_and_points_at_the_step() -> None:
    evidence = TrialEvidence(
        task=_task(),
        artifacts=(_steps({"path": "catalog.csv"}, {"path": "../verify.py"}),),
    )
    (finding,) = grader_file_touches(evidence)
    assert (finding.code, finding.severity, finding.steps) == (
        "grader_file_touch",
        "critical",
        (2,),
    )
    assert "verify.py" in finding.message
    assert verifier_files(_task()) == ("verify.py",)


def test_the_jobs_own_files_never_count_as_the_agent_naming_them() -> None:
    ledger = DownloadedFile(path="rewards.jsonl", data=b'{"source": "step", "value": 1}\n')
    evidence = TrialEvidence(task=_task(), artifacts=(ledger, _steps({"path": "a.csv"})))
    assert detect(evidence) == ()


def test_a_denied_read_of_the_hosts_folder_is_forbidden_read() -> None:
    logs = b"cat: /workspace/.plural/apps/bootstrap.json: Permission denied\n"
    codes = [item.code for item in detect(TrialEvidence(task=_task(), logs=logs))]
    assert codes == ["forbidden_read", "grader_file_touch"]


def test_the_canary_in_an_answer_or_action_is_critical() -> None:
    in_answer = TrialEvidence(task=_task(), canary=CANARY, answer={"note": CANARY})
    in_action = TrialEvidence(task=_task(), canary=CANARY, artifacts=(_steps({"q": CANARY}),))
    assert [item.code for item in canary_sightings(in_answer)] == ["canary_seen"]
    assert canary_sightings(in_action)[0].steps == (1,)
    assert canary_sightings(TrialEvidence(task=_task(), answer={"note": CANARY})) == ()


@pytest.mark.parametrize(
    ("answer", "apps", "flagged"),
    [
        ({"total": 999}, {"crm": {"initial": {"n": 0}, "final": {"n": 0}}}, True),
        ({"total": 1200}, {"crm": {"initial": {"n": 0}, "final": {"n": 0}}}, False),
        ({"total": 999}, {"crm": {"initial": {"n": 0}, "final": {"n": 1}}}, False),
    ],
)
def test_a_pass_with_no_work_and_the_wrong_answer_is_suspicious(
    answer: dict[str, int], apps: dict[str, Any], flagged: bool
) -> None:
    evidence = TrialEvidence(
        task=_task({"total": 1200}),
        artifacts=(DownloadedFile(path="apps.json", data=json.dumps(apps).encode()),),
        verifier_results=_passed(),
        answer=answer,
    )
    found = suspicious_success(evidence)
    assert bool(found) is flagged
    if flagged:
        assert found[0].severity == "warning"


@pytest.mark.parametrize(("changed", "flagged"), [(True, False), (False, True), (None, True)])
def test_a_pass_that_changed_the_workspace_did_work(changed: bool | None, flagged: bool) -> None:
    workspace = {"available": True} if changed is None else {"changed": changed}
    evidence = TrialEvidence(
        task=_task({"total": 1200}),
        artifacts=(
            DownloadedFile(path="apps.json", data=b"{}"),
            DownloadedFile(path="workspace.json", data=json.dumps(workspace).encode()),
        ),
        verifier_results=_passed(),
        answer="Done.",
    )
    assert bool(suspicious_success(evidence)) is flagged


def test_blocked_connections_are_reported_once_each() -> None:
    (finding,) = egress_denials(["pastebin.com", "pastebin.com", "1.2.3.4"])
    assert finding.code == "egress_denied"
    assert "2 destination(s)" in finding.message
    assert egress_denials([]) == ()
