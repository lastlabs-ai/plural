"""Optional advanced extensions; the beginner Job does not need these."""

from plural import (
    Agent,
    AgentVerifier,
    HarnessCapability,
    HarnessPackage,
    HumanVerifier,
    PackageSource,
    RubricCriterion,
)
from plural.common import HarnessDefinition
from plural.environments import rewarder

custom_harness = HarnessPackage(
    definition=HarnessDefinition(
        name="custom-wordle-loop",
        implementation="runnable",
        command=("python", "harness.py"),
        capabilities=frozenset({HarnessCapability.FILE_READ}),
    ),
    source=PackageSource(kind="local", uri=".", unsafe_local=True),
)
custom_agent = Agent(model="openai/gpt-5.6-luna", harness=custom_harness)

quality = RubricCriterion(name="quality", description="The play is efficient and correct.")
agent_judge = AgentVerifier(
    name="judge",
    model="openai/gpt-5.6-luna",
    instructions="Score the completed Wordle trajectory.",
    criteria=[quality],
)
human_judge = HumanVerifier(name="human-review", criteria=[quality])


@rewarder
def efficient(previous_state, current_state, action, result) -> float:
    """Reward solving with guesses remaining."""
    del previous_state, action, result
    return float(current_state.get("solved", False)) * current_state.get("remaining", 0) / 6
