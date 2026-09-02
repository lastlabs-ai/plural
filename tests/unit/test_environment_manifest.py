from __future__ import annotations

from plural.environments.env import Environment, tool
from plural.environments.types import Observation, State
from plural.studio import environment_manifest


class MemoryState(State):
    notes: list[str] = []


class VisibleObs(Observation):
    n: int = 0

    def render(self) -> str:
        return f"n={self.n}"


class DemoEnv(Environment[VisibleObs, MemoryState]):
    name = "demo-world"
    version = "0.2.0"
    description = "A tiny writable counter."
    readme = "# Demo\n\nThe agent writes notes into state."
    system_prompt = "Stay inside the observation."
    guardrails = [
        "Do not invent hidden state.",
        {"name": "horizon", "rule": "Stop when the task is done."},
    ]
    skills = ["triage", {"name": "refund", "tool_names": ["inc"]}]

    def setup(self, task):
        super().setup(task)
        self.state = MemoryState(seed=self.seed, notes=[])

    def observe(self) -> VisibleObs:
        return VisibleObs(n=len(self.state.notes))

    @tool
    def inc(self) -> dict:
        """Append a note."""
        self.state.notes.append("tick")
        return {"n": len(self.state.notes)}


def test_observation_and_state_schemas_come_from_generic_models() -> None:
    env = DemoEnv()
    observation = env.observation_schema()
    state = env.state_schema()
    assert observation["properties"]["n"]["type"] == "integer"
    assert state["properties"]["notes"]["type"] == "array"
    assert env._contract_names() == ("VisibleObs", "MemoryState")


def test_plain_environment_uses_default_schemas() -> None:
    env = Environment(name="blank")
    assert "text" in env.observation_schema()["properties"]
    assert "seed" in env.state_schema()["properties"]
    assert env.normalized_guardrails() == []
    assert env.context_policy()["include_history"] is True


def test_environment_manifest_includes_world_contract() -> None:
    env = DemoEnv()
    manifest = environment_manifest(env)
    assert manifest["observation_type"] == "VisibleObs"
    assert manifest["state_type"] == "MemoryState"
    assert manifest["observation_schema"]["properties"]["n"]["type"] == "integer"
    assert manifest["state_schema"]["properties"]["notes"]["type"] == "array"
    assert manifest["guardrails"][0]["rule"] == "Do not invent hidden state."
    assert manifest["guardrails"][1] == {"name": "horizon", "rule": "Stop when the task is done."}
    assert manifest["skills"][0]["name"] == "triage"
    assert manifest["skills"][1]["tool_names"] == ["inc"]
    assert "setup" in manifest["hooks"]
    assert "observe" in manifest["hooks"]
    assert manifest["context"]["max_turns"] == 8
    assert manifest["tools"][0]["name"] == "inc"


def test_fingerprint_covers_guardrails_and_schemas() -> None:
    first = DemoEnv().fingerprint()
    other = DemoEnv()
    other.guardrails = ["A different rule."]
    assert other.fingerprint() != first
    third = DemoEnv()
    assert third.fingerprint() == first


def test_spawn_copies_world_fields() -> None:
    env = DemoEnv()
    env.guardrails.append("Copied rule.")
    spawned = env.spawn()
    assert spawned.description == env.description
    assert spawned.readme == env.readme
    assert spawned.guardrails == env.guardrails
    assert spawned.skills == env.skills
    spawned.guardrails.append("only-child")
    assert "only-child" not in env.guardrails
