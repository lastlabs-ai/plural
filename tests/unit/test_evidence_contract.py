from __future__ import annotations

import pytest
from pydantic import ValidationError

from plural import (
    DeterministicVerifier,
    Environment,
    Episode,
    Runtime,
    Task,
    VerifierOutput,
    action,
)
from plural.environments.definition import EnvironmentDefinition


def solved(episode: Episode) -> VerifierOutput:
    return VerifierOutput(reward=float(bool(episode.observation.get("solved"))))


def test_task_bind_accepts_action_environment_without_package_call() -> None:
    class Wordle(Environment):
        name = "wordle"

        @action
        def guess(self, word: str) -> dict[str, str]:
            return {"word": word}

    environment = Wordle(runtime=Runtime.docker())
    task = Task(
        name="easy-01",
        instructions="Play.",
        environment=environment,
        verifiers=[DeterministicVerifier(name="solved", check=solved)],
    )
    definition = environment.definition()
    assert environment.source is not None
    assert definition.reset_command[:3] == ("python", "-m", "plural.environments.runner")
    assert definition.actions[0].command[-1] == "guess"
    assert task.environment is environment


def test_verifier_rejects_non_callable_check() -> None:
    with pytest.raises(ValidationError, match="Cannot create DeterministicVerifier") as exc:
        DeterministicVerifier(name="solved", check=123)
    message = str(exc.value)
    assert "function that accepts an Episode" in message
    assert "Got int" in message


def test_task_bind_rejects_unknown_initial_state() -> None:
    environment = EnvironmentDefinition(
        name="support-queue",
        state_schema={
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "expected": {"type": "string"},
            },
        },
        runtime=Runtime.docker(),
    )
    with pytest.raises(ValidationError, match="Cannot create Task 'ticket-1'") as exc:
        Task(
            name="ticket-1",
            instructions="Triage.",
            environment=environment,
            verifiers=[DeterministicVerifier(name="solved", check=solved)],
            initial_state={"answer": "billing"},
        )
    message = str(exc.value)
    assert "does not define: 'answer'" in message
    assert "support-queue State fields:" in message


def test_function_verifier_binds_to_packageless_environment() -> None:
    task = Task(
        name="easy-01",
        instructions="Solve.",
        environment=Environment(name="wordle", runtime=Runtime.docker()),
        verifiers=[DeterministicVerifier(name="solved", check=solved)],
    )
    assert task.verifiers[0].name == "solved"
    assert callable(task.verifiers[0].check)
