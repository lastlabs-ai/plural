from __future__ import annotations

import random
from typing import Any

import pytest
from pydantic import Field, ValidationError

from plural import (
    Agent,
    App,
    DeterministicVerifier,
    Environment,
    Episode,
    Job,
    Runtime,
    State,
    Task,
    VerifierOutput,
    action,
)
from plural.common import ExecutionTarget
from plural.environments.definition import EnvironmentRuntime
from plural.sandbox import NetworkMode


def solved(episode: Episode) -> VerifierOutput:
    return VerifierOutput(reward=1.0)


def _task() -> Task:
    return Task(
        name="easy-01",
        instructions="Solve.",
        environment=Environment(name="wordle", runtime=Runtime.docker()),
        verifiers=[DeterministicVerifier(name="solved", check=solved)],
    )


def test_environment_requires_runtime() -> None:
    with pytest.raises(ValueError, match="Cannot create Environment 'environment'") as exc:
        Environment()
    message = str(exc.value)
    assert "runtime is required" in message
    assert "Runtime.docker()" in message
    assert "Runtime.local()" in message


def test_runtime_presets() -> None:
    docker = Runtime.docker()
    assert docker.provider == "docker"
    assert docker.image == "python:3.12-slim"
    assert docker.network is NetworkMode.PUBLIC
    local = Runtime.local()
    assert local.provider == "local"
    assert local.allow_unsafe_local is True
    daytona = Runtime.daytona()
    assert daytona.provider == "daytona"
    assert daytona.image == "python:3.12-slim"


def test_runtime_allowlist_requires_hosts() -> None:
    with pytest.raises(ValidationError, match="Cannot create Runtime") as exc:
        EnvironmentRuntime(network="allowlist")
    assert "allowed_hosts" in str(exc.value)


def test_runtime_local_requires_trust() -> None:
    with pytest.raises(ValidationError, match="Cannot create Runtime") as exc:
        EnvironmentRuntime(provider="local", targets=frozenset({ExecutionTarget.LOCAL}))
    assert "Runtime.local()" in str(exc.value)


def test_job_rejects_client_and_api_key() -> None:
    with pytest.raises(ValueError, match="Cannot create Job") as exc:
        Job(
            _task(),
            agents=[Agent(model="openai/gpt-5.6-luna")],
            client=object(),
            api_key="sk-test",
        )
    assert "not both" in str(exc.value)


def test_job_live_run_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    job = Job(_task(), agents=[Agent(model="openai/gpt-5.6-luna")])
    with pytest.raises(ValueError, match="Cannot run Job") as exc:
        job._credential_environ()
    message = str(exc.value)
    assert "client=Client()" in message
    assert "api_key=" in message
    assert "plural auth login" in message


def test_job_api_key_selects_the_plural_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("PLURAL_GATEWAY_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    job = Job(_task(), agents=[Agent(model="openai/gpt-5.6-luna")], api_key="pk-test")
    environ = job._credential_environ()
    assert environ["PLURAL_API_KEY"] == "pk-test"
    assert environ["PLURAL_GATEWAY_URL"]
    assert "OPENAI_API_KEY" not in environ


def test_job_client_injects_plural_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = type("Client", (), {"api_key": "pk-test", "base_url": "https://gateway.test"})()
    job = Job(_task(), agents=[Agent(model="openai/gpt-5.6-luna")], client=client)
    environ = job._credential_environ()
    assert environ["PLURAL_API_KEY"] == "pk-test"


def test_wordle_pins_or_randomizes_secret() -> None:
    words = ("crane", "slate", "audio")

    class Game(State):
        secret: str = Field(default="", json_schema_extra={"x-plural-initial": True})
        seed: int | None = None

    class Wordle(App[Game]):
        name = "wordle"

        def reset(self, initial_state: dict[str, Any]) -> str:
            super().reset(initial_state)
            if not self.state.secret:
                self.state.secret = random.Random(self.state.seed).choice(words)
            return "Guess the word."

        @action
        def guess(self, word: str) -> str:
            return word

    pinned = Environment(name="wordle", apps=[Wordle()], runtime=Runtime.local())
    pinned.reset(initial_state={"secret": "crane"})
    assert pinned.apps[0].state.secret == "crane"

    seeded = Environment(name="wordle", apps=[Wordle()], runtime=Runtime.local())
    seeded.reset(seed=7)
    assert seeded.apps[0].state.secret == random.Random(7).choice(words)
