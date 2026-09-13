"""Offline player: attach Wordle to the Task, then follow reset / step."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from wordle import WORDS, Wordle

request = json.loads(sys.stdin.readline())
task = request["task"]
env = Wordle(info={"task_id": task["task_id"]})
observation, _info = env.reset()
env.persist()
trajectory = [
    {"turn": 0, "type": "reset", "observation": env.observation_snapshot()},
]
for turn, word in enumerate(WORDS, start=1):
    observation, reward, terminated, truncated, _info = env.step(word=word)
    env.persist()
    trajectory.append(
        {
            "turn": turn,
            "action": {"name": "guess", "word": word},
            "observation": env.observation_snapshot(),
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
        }
    )
    if terminated:
        break

Path("result.json").write_text(
    json.dumps({"task_id": task["task_id"], "solved": env.observation.solved}) + "\n"
)
Path("evidence.txt").write_text(env.observation.text + "\n")
Path("trajectory.jsonl").write_text("".join(json.dumps(item) + "\n" for item in trajectory))
print(
    json.dumps(
        {
            "protocol": "plural-harness-v1",
            "type": "result",
            "status": "succeeded",
            "outputs": ["result.json"],
            "artifacts": [
                "evidence.txt",
                "trajectory.jsonl",
                "state.json",
                "observation.json",
            ],
            "trace_id": f"wordle-{task['task_id']}",
        }
    ),
    flush=True,
)
