"""Check the actual final Environment state, not the model's final claim."""

import json
from pathlib import Path

payload = json.loads(Path(".plural/verifier-input.json").read_text())
view = payload["environment_view"]
observation = view["observation"]
state = view["state"]
correct = (
    observation["done"]
    and observation["category"] == state["expected"]
    and bool(observation["draft_reply"].strip())
)
reward = float(correct)
Path("verifier-result.json").write_text(
    json.dumps(
        {
            "reward": reward,
            "scores": {
                "correct_category": reward,
                "response_drafted": float(bool(observation["draft_reply"])),
            },
            "evidence": [
                f"status={observation['status']}",
                f"category={observation['category']}",
                f"correct={correct}",
            ],
            "feedback": "Correct category and a response was drafted."
            if correct
            else "The ticket was not resolved with the correct category and a response.",
        }
    )
    + "\n"
)
