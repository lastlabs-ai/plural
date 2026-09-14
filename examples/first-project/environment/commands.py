"""Adapt typed actions to the package runner's JSON command interface."""

import json
import sys
from pathlib import Path

from world import QueueState, SupportQueue


def task_ticket_id() -> str | None:
    if not Path("task.json").exists():
        return None
    task = json.loads(Path("task.json").read_text())
    info = task.get("info") if isinstance(task.get("info"), dict) else {}
    return info.get("ticket_id") or task.get("task_id")


world = SupportQueue(ticket_id=task_ticket_id())
if Path("state.json").exists():
    world.state = QueueState.model_validate_json(Path("state.json").read_text())
    world.observe()
name = sys.argv[1]
if name == "reset":
    observation, _info = world.reset()
elif name in {"inspect_ticket", "categorize", "draft_response", "resolve"}:
    if not world.state.ticket_id:
        world.reset()
    try:
        parameters = json.load(sys.stdin)
        observation, _reward, _terminated, _truncated, _info = world.step(
            {"name": name, **parameters}
        )
    except ValueError as error:
        observation = {"error": str(error), **world.observe()}
else:
    raise ValueError("Unknown action")
world.persist()
print(json.dumps(observation if isinstance(observation, dict) else world.observation_snapshot()))
