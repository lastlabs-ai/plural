"""A deterministic Verifier that requires evidence is refused locally without it."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeProvider
from test_trust import _spec, _task

from plural.common import ErrorCode
from plural.execution import JobRunner, JobStore
from plural.verifiers import (
    DeterministicVerifier,
    Episode,
    EvidenceMissing,
    VerifierOutput,
    WeightedVerifier,
)


def _bare(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1.0)


def test_a_result_without_evidence_is_refused() -> None:
    verifier = DeterministicVerifier(name="bare", check=_bare)
    with pytest.raises(EvidenceMissing, match="returned no evidence"):
        verifier.invoke(Episode())
    allowed = DeterministicVerifier(name="bare", check=_bare, evidence_required=False)
    assert allowed.invoke(Episode()).score == 1.0


async def test_a_trial_whose_verifier_gives_no_evidence_fails_as_evidence_missing(
    tmp_path: Path,
) -> None:
    task = _task().model_copy(
        update={
            "verifiers": (
                WeightedVerifier(verifier=DeterministicVerifier(name="bare", check=_bare)),
            )
        }
    )
    result = await JobRunner(
        _spec(task), provider=FakeProvider("docker"), store=JobStore(tmp_path / "j")
    ).run()

    (trial,) = result.trials
    assert trial.status == "failed"
    assert trial.error_code is ErrorCode.EVIDENCE_MISSING
    assert "returned no evidence" in (trial.error_message or "")
