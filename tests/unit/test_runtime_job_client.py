from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from plural import (
    Agent,
    DeterministicVerifier,
    Environment,
    Episode,
    Job,
    Observation,
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


def test_job_byo_key_injects_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    job = Job(_task(), agents=[Agent(model="openai/gpt-5.6-luna")], api_key="sk-test")
    environ = job._credential_environ()
    assert environ["OPENAI_API_KEY"] == "sk-test"


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
        secret: str = ""

    class Board(Observation):
        solved: bool = False

    class Wordle(Environment[Board, Game]):
        name = "wordle"

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            secret = (options or {}).get("secret") or self.state.secret
            if not secret:
                secret = random.Random(self.state.seed).choice(words)
            self.state = Game(secret=secret, seed=self.state.seed)
            return self.observation, {}

        @action
        def guess(self, word: str) -> Board:
            return self.observation

    pinned = Wordle(runtime=Runtime.local(), state=Game(secret="crane"))
    pinned.reset()
    assert pinned.state.secret == "crane"

    seeded = Wordle(runtime=Runtime.local())
    seeded.reset(seed=7)
    assert seeded.state.secret == random.Random(7).choice(words)
