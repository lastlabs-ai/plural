"""Optional advanced extensions; the beginner Job does not need these."""

from harness import WordleHarness

from plural import (
    Agent,
    AgentVerifier,
    HumanVerifier,
    RubricCriterion,
)
from plural.environments import rewarder

custom_harness = WordleHarness()
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
