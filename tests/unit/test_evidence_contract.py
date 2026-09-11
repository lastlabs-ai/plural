from __future__ import annotations

import pytest
from pydantic import ValidationError

from plural.domain import (
    DeterministicVerifier,
    EnvironmentDefinition,
    EvidenceContract,
    TaskDefinition,
    WeightedVerifier,
)


def _environment() -> EnvironmentDefinition:
    return EnvironmentDefinition(
        name="wordle",
        observation_schema={
            "type": "object",
            "properties": {"board": {"type": "array"}, "remaining": {"type": "integer"}},
        },
        state_schema={
            "type": "object",
            "properties": {
                "secret": {"type": "string", "x-plural-hidden": True},
                "remaining": {"type": "integer"},
            },
        },
    )


def test_task_rejects_missing_observation_path() -> None:
    verifier = DeterministicVerifier(
        name="wrong-world",
        command=("python", "verify.py"),
        evidence=EvidenceContract(observation_paths=("missing",)),
    )
    with pytest.raises(ValidationError, match="observation path"):
        TaskDefinition(
            task_id="one",
            instructions="Play.",
            environment=_environment(),
            verifiers=(WeightedVerifier(verifier=verifier),),
        )


def test_task_rejects_hidden_state_without_flag() -> None:
    verifier = DeterministicVerifier(
        name="peek",
        command=("python", "verify.py"),
        evidence=EvidenceContract(state_paths=("secret",)),
    )
    with pytest.raises(ValidationError, match="include_hidden_state"):
        TaskDefinition(
            task_id="one",
            instructions="Play.",
            environment=_environment(),
            verifiers=(WeightedVerifier(verifier=verifier),),
        )


def test_wordle_shaped_pin_succeeds() -> None:
    verifier = DeterministicVerifier(
        name="wordle-solved",
        command=("python", "verify.py"),
        evidence=EvidenceContract(
            artifacts=("final-observation.json",),
            observation_paths=("board",),
            state_paths=("secret",),
            include_hidden_state=True,
        ),
    )
    task = TaskDefinition(
        task_id="easy-01",
        instructions="Solve.",
        environment=_environment(),
        verifiers=(WeightedVerifier(verifier=verifier),),
    )
    assert task.verifiers[0].verifier.evidence.include_hidden_state
    assert task.verifiers[0].verifier.required_artifacts == ("final-observation.json",)
