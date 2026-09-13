"""Adapt Wordle reset/step to the native runner's JSON command interface."""

import json
import sys
from pathlib import Path

from wordle import Board, Game, Wordle


def task_id() -> str:
    if not Path("task.json").exists():
        return "easy-01"
    task = json.loads(Path("task.json").read_text())
    info = task.get("info") if isinstance(task.get("info"), dict) else {}
    return str(info.get("task_id") or task.get("task_id") or "easy-01")


world = Wordle(info={"task_id": task_id()})
if Path("state.json").exists():
    world.state = Game.model_validate_json(Path("state.json").read_text())
if Path("observation.json").exists():
    world.observation = Board.model_validate_json(Path("observation.json").read_text())
name = sys.argv[1]
if name == "reset":
    observation, _info = world.reset()
elif name == "guess":
    if not world.state.secret:
        world.reset()
    try:
        observation, _reward, _terminated, _truncated, _info = world.step(**json.load(sys.stdin))
    except ValueError as error:
        observation = {"error": str(error), **world.observation_snapshot()}
else:
    raise ValueError("Unknown action")
world.persist()
print(json.dumps(observation if isinstance(observation, dict) else world.observation_snapshot()))
