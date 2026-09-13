"""Check the actual final Environment state, not the model's final claim."""

import json
from pathlib import Path

payload = json.loads(Path(".plural/verifier-input.json").read_text())
view = payload["environment_view"]
observation = view["observation"]
state = view["state"]
correct = observation["done"] and observation["category"] == state["expected"]
reward = float(correct)
Path("verifier-result.json").write_text(
    json.dumps(
        {
            "reward": reward,
            "scores": {"correct": reward},
            "evidence": [f"category={observation['category']}", f"correct={correct}"],
            "feedback": "Correct category."
            if correct
            else "Incorrect or incomplete categorization.",
        }
    )
    + "\n"
)
