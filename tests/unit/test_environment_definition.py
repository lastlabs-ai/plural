from __future__ import annotations

from plural import (
    Environment,
    Observation,
    Resource,
    Runtime,
    Secret,
    State,
    action,
    rewarder,
)


class CounterState(State):
    count: int = 0
    answer: str = "secret"


class CounterObservation(Observation):
    count: int = 0


class CounterEnvironment(Environment[CounterObservation, CounterState]):
    name = "counter"
    version = "1.2.0"
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
        runtime=Runtime.docker(),
        resources=(Resource(kind="data", name="orders"),),
        secrets=(Secret(name="DATABASE_URL"),),
        metadata={"owner": "evals"},
    )
    manifest = environment.definition()
    assert manifest.name == "counter"
    assert manifest.version == "1.2.0"
    assert manifest.overview == "A stateful counter."
    assert manifest.readme == "# Counter"
    assert manifest.actions[0].name == "increment"
    assert manifest.actions[0].kind == "command"
    assert manifest.actions[0].command[-1] == "increment"
    assert manifest.reset_command[-1] == "reset"
    assert manifest.rewarders[0].name == "progress"
    assert manifest.rewarders[0].weight == 2
    assert manifest.state_schema["properties"]["answer"]["type"] == "string"
    assert "x-plural-hidden" not in manifest.state_schema["properties"]["answer"]
    assert manifest.observation_schema["properties"]["count"]["type"] == "integer"
    assert manifest.resources[0].name == "orders"
    assert manifest.secrets[0].name == "DATABASE_URL"
    dumped = manifest.model_dump(mode="json")
    assert "tasks" not in dumped
    assert "verifier" not in dumped
    assert "mode" not in dumped
    assert "instructions" not in dumped
    assert "schema_version" not in dumped
    assert "revision" not in dumped


def test_snapshots_are_json_safe_and_detached() -> None:
    environment = CounterEnvironment(runtime=Runtime.docker())
    state = environment.state_snapshot()
    observation = environment.observation_snapshot()
    state["count"] = 99
    observation["count"] = 99
    assert environment.state.count == 0
    assert environment.observation.count == 0


def test_reset_and_step_follow_gymnasium() -> None:
    environment = CounterEnvironment(runtime=Runtime.docker())
    observation, info = environment.reset()
    assert observation.count == 0
    assert info == {}
    observation, reward, terminated, truncated, info = environment.step(
        {"name": "increment", "amount": 2}
    )
    assert observation.count == 2
    assert environment.state.count == 2
    # The `progress` rewarder scored this transition and its weight applied.
    assert reward == 2
    assert info["rewards"] == [{"name": "progress", "weight": 2.0, "value": 1.0}]
    assert terminated is False
    assert truncated is False
    assert [item.name for item in environment.definition().actions] == ["increment"]


def test_environment_does_not_terminate_unless_it_says_so() -> None:
    class Quiet(Environment[Observation, CounterState]):
        name = "quiet"

        @action
        def touch(self) -> dict[str, bool]:
            """Mark the observation done without declaring termination."""
            self.observation.metadata["done"] = True
            return {"ok": True}

    environment = Quiet(runtime=Runtime.docker())
    _observation, _reward, terminated, truncated, _info = environment.step("touch")
    assert terminated is False
    assert truncated is False


def test_rewarder_failure_does_not_fail_the_step() -> None:
    class Fragile(Environment[Observation, CounterState]):
        name = "fragile"

        @action
        def bump(self) -> dict[str, int]:
            """Advance the counter."""
            self.state.count += 1
            return {"count": self.state.count}

        @rewarder
        def broken(self, previous_state, current_state, action, result) -> float:
            """Fail on purpose."""
            raise RuntimeError("judge unavailable")

    environment = Fragile(runtime=Runtime.docker())
    _observation, reward, _terminated, _truncated, info = environment.step("bump")
    assert environment.state.count == 1
    assert reward == 0
    assert info["rewards"][0]["error"] == "judge unavailable"


def test_reward_method_and_rewarders_combine() -> None:
    class Scored(Environment[Observation, CounterState]):
        name = "scored"

        @action
        def bump(self) -> dict[str, int]:
            """Advance the counter."""
            self.state.count += 1
            return {"count": self.state.count}

        def reward(self, previous_state, current_state, action, result) -> float:
            return 0.5

        @rewarder(weight=3)
        def progress(self, previous_state, current_state, action, result) -> float:
            """Reward any advance."""
            return 1.0

    environment = Scored(runtime=Runtime.docker())
    _observation, reward, _terminated, _truncated, info = environment.step("bump")
    assert reward == 3.5
    assert [item["name"] for item in info["rewards"]] == ["reward", "progress"]


def test_reset_cannot_be_an_action() -> None:
    class Broken(Environment):
        @action
        def reset(self) -> dict[str, str]:
            return {}

    try:
        Broken(runtime=Runtime.docker()).definition()
    except TypeError as exc:
        assert "episode API" in str(exc)
    else:
        raise AssertionError("reset @action was compiled")


def test_rewarder_signature_is_enforced() -> None:
    try:

        @rewarder
        def invalid(value) -> float:
            return float(value)

    except TypeError as exc:
        assert "previous_state" in str(exc)
    else:
        raise AssertionError("invalid rewarder signature was accepted")
