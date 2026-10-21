from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from plural import (
    App,
    DeterministicVerifier,
    Environment,
    Episode,
    Runtime,
    State,
    Task,
    VerifierOutput,
    action,
    initial,
)
from plural.apps.definition import AppAction, AppDefinition
from plural.environments.definition import EnvironmentDefinition, EnvironmentRuntime
from plural.execution.policy import verifier_score_sandbox
from plural.tasks import validate_task_state
from plural.verifiers import AppSnapshot, VerifierRuntime


def solved(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=float(bool(episode.observation.get("solved"))))


def _environment(state_schema: dict[str, Any], *, name: str = "wordle") -> EnvironmentDefinition:
    return EnvironmentDefinition(
        name=name,
        apps=(
            AppDefinition(
                name=name.replace("-", "_"),
                kind="python",
                python="game.py:Game",
                actions=(AppAction(name="guess", description="Guess."),),
                state_schema=state_schema,
            ),
        ),
        runtime=Runtime.docker(),
    )


def test_task_bind_accepts_an_app_environment_without_package_call() -> None:
    class Wordle(App):
        name = "wordle"

        @action
        def guess(self, word: str) -> dict[str, str]:
            return {"word": word}

    environment = Environment(apps=[Wordle()], runtime=Runtime.docker())
    task = Task(
        name="easy-01",
        instructions="Play.",
        environment=environment,
        verifiers=[DeterministicVerifier(name="solved", check=solved)],
    )
    definition = environment.definition()
    assert environment.source is not None
    assert definition.apps[0].python is not None
    assert definition.apps[0].python.endswith(".Wordle")
    assert [item.name for item in definition.actions] == ["guess"]
    assert task.environment is environment


def test_episode_state_reads_one_app_directly_and_several_by_name() -> None:
    one = Episode.from_apps({"game": {"control": "owned", "initial": {}, "final": {"step": 2}}})
    assert one.state == {"step": 2}
    assert one.apps["game"].final == {"step": 2}
    several = Episode.from_apps(
        {
            "game": {"control": "owned", "initial": {}, "final": {"step": 2}},
            "crm": {"control": "live", "initial": None, "final": None},
        }
    )
    assert several.state == {"game": {"step": 2}, "crm": None}


def test_app_queries_are_read_only() -> None:
    snapshot = AppSnapshot(control="owned")
    with pytest.raises(RuntimeError, match="only available to function Verifiers"):
        snapshot.query("get_record", id="1")


def test_default_verifier_runtime_uses_the_task_environment() -> None:
    environment = EnvironmentDefinition(
        name="wordle",
        runtime=EnvironmentRuntime(provider="daytona", image="wordle:latest"),
    )
    provider, requirements = verifier_score_sandbox(environment, VerifierRuntime())
    assert provider == "daytona"
    assert requirements.image == "wordle:latest"
    provider, requirements = verifier_score_sandbox(
        environment,
        VerifierRuntime(provider="docker", image="checker:latest"),
    )
    assert provider == "docker"
    assert requirements.image == "checker:latest"


def test_verifier_rejects_non_callable_final() -> None:
    with pytest.raises(ValidationError, match="Cannot create DeterministicVerifier") as exc:
        DeterministicVerifier(name="solved", check=123)
    message = str(exc.value)
    assert "function that accepts the finished Episode" in message
    assert "Got int" in message


def test_initial_constraints_live_on_the_schema_not_the_default() -> None:
    class Game(State):
        secret: str = initial(
            "",
            min_length=5,
            max_length=5,
            pattern=r"^[a-z]{5}$",
        )

    assert Game().secret == ""
    secret = Game.model_json_schema()["properties"]["secret"]
    assert secret["x-plural-initial"] is True
    assert secret["minLength"] == 5
    assert secret["maxLength"] == 5
    assert secret["pattern"] == "^[a-z]{5}$"
    environment = _environment({"type": "object", "properties": {"secret": secret}})
    assert validate_task_state(
        task_id="easy-01", environment=environment, state={"secret": "crane"}
    ) == {"wordle": {"secret": "crane"}}
    with pytest.raises(ValueError, match="exactly 5 lowercase letters"):
        validate_task_state(task_id="easy-01", environment=environment, state={"secret": "no"})


def test_task_state_rejects_fields_the_app_owns() -> None:
    environment = _environment(
        {
            "type": "object",
            "properties": {
                "secret": {"type": "string", "x-plural-initial": True},
                "solved": {"type": "boolean"},
            },
        }
    )
    accepted = validate_task_state(
        task_id="easy-01", environment=environment, state={"wordle": {"secret": "crane"}}
    )
    assert accepted == {"wordle": {"secret": "crane"}}
    with pytest.raises(ValueError, match="cannot set 'solved'"):
        validate_task_state(task_id="easy-01", environment=environment, state={"solved": True})


def test_task_bind_rejects_unknown_initial_state() -> None:
    environment = _environment(
        {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "expected": {"type": "string"},
            },
        },
        name="support-queue",
    )
    with pytest.raises(ValidationError, match="Cannot create Task 'ticket-1'") as exc:
        Task(
            name="ticket-1",
            instructions="Triage.",
            environment=environment,
            verifiers=[DeterministicVerifier(name="solved", check=solved)],
            initial_state={"answer": "billing"},
        )
    assert "does not define: 'answer'" in str(exc.value)


def test_task_refuses_two_verifiers_with_one_name() -> None:
    with pytest.raises(ValidationError, match="More than one Verifier is named 'solved'"):
        Task(
            name="easy-01",
            instructions="Solve.",
            environment=Environment(name="wordle", runtime=Runtime.docker()),
            verifiers=[
                DeterministicVerifier(name="solved", check=solved),
                DeterministicVerifier(name="solved", check=solved),
            ],
        )


def test_function_verifier_binds_to_an_environment_without_apps() -> None:
    task = Task(
        name="easy-01",
        instructions="Solve.",
        environment=Environment(name="wordle", runtime=Runtime.docker()),
        verifiers=[DeterministicVerifier(name="solved", check=solved)],
    )
    assert task.verifiers[0].name == "solved"
    assert task.verifiers[0].check_fn is solved
