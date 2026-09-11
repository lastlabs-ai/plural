from __future__ import annotations

from plural import (
    Environment,
    EnvironmentResource,
    EnvironmentRuntime,
    Observation,
    SecretReference,
    State,
    action,
    hidden,
    rewarder,
)


class CounterState(State):
    count: int = 0
    answer: str = hidden("secret")


class CounterObservation(Observation):
    count: int = 0


class CounterEnvironment(Environment[CounterObservation, CounterState]):
    name = "counter"
    revision = "1.2.0"
    overview = "A stateful counter."
    readme = "# Counter"

    @action
    def increment(self, amount: int) -> dict[str, int]:
        """Increment the counter."""
        self.state.count += amount
        self.observation.count = self.state.count
        return {"count": self.state.count}

    @rewarder(weight=2)
    def progress(self, previous_state, current_state, action, result) -> float:
        """Reward increasing state."""
        del action, result
        return float(current_state["count"] > previous_state["count"])


def test_environment_compiles_exact_manifest() -> None:
    environment = CounterEnvironment(
        runtime=EnvironmentRuntime(provider="docker"),
        resources=(EnvironmentResource(kind="data", name="orders"),),
        secrets=(SecretReference(name="DATABASE_URL"),),
        metadata={"owner": "evals"},
    )
    manifest = environment.definition()
    assert manifest.name == "counter"
    assert manifest.revision == "1.2.0"
    assert manifest.overview == "A stateful counter."
    assert manifest.readme == "# Counter"
    assert manifest.actions[0].name == "increment"
    assert manifest.actions[0].kind == "python"
    assert manifest.rewarders[0].name == "progress"
    assert manifest.rewarders[0].weight == 2
    assert manifest.state_schema["properties"]["answer"]["x-plural-hidden"] is True
    assert manifest.observation_schema["properties"]["count"]["type"] == "integer"
    assert manifest.resources[0].name == "orders"
    assert manifest.secrets[0].name == "DATABASE_URL"
    dumped = manifest.model_dump(mode="json")
    assert "tasks" not in dumped
    assert "verifier" not in dumped
    assert "mode" not in dumped
    assert "instructions" not in dumped


def test_snapshots_are_json_safe_and_detached() -> None:
    environment = CounterEnvironment()
    state = environment.state_snapshot()
    observation = environment.observation_snapshot()
    state["count"] = 99
    observation["count"] = 99
    assert environment.state.count == 0
    assert environment.observation.count == 0


def test_rewarder_signature_is_enforced() -> None:
    try:

        @rewarder
        def invalid(value) -> float:
            return float(value)

    except TypeError as exc:
        assert "previous_state" in str(exc)
    else:
        raise AssertionError("invalid rewarder signature was accepted")
