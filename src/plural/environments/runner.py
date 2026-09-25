"""Run an Environment reset or action inside a Runtime workspace."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from plural import Environment, Runtime

PROTOCOL = "plural-step-v1"


def main(argv: list[str] | None = None) -> None:
    """Dispatch ``reset`` or one ``@action`` and emit one step envelope."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit(
            "usage: python -m plural.environments.runner <file.py:Class> <reset|action>"
        )
    world = _load(args[0])
    _restore(world)
    envelope = _dispatch(world, args[1])
    world.persist()
    print(json.dumps(envelope, sort_keys=True))


def _load(reference: str) -> Environment[Any, Any]:
    script, separator, qualname = reference.partition(":")
    if not separator or not script or not qualname:
        raise SystemExit(f"environment reference must be file.py:Class, got {reference!r}")
    path = Path(script).expanduser()
    if not path.is_file():
        path = Path.cwd() / script
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"environment file not found: {script}")
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load environment file: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    target: Any = module
    for part in qualname.split("."):
        target = getattr(target, part)
    if not isinstance(target, type) or not issubclass(target, Environment):
        raise SystemExit(f"{reference} is not an Environment class")
    return target(runtime=Runtime.local(), info=_task_info())


def _task_info() -> Any:
    path = Path("task.json")
    if not path.exists():
        return None
    task = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(task, dict):
        return task.get("info")
    return None


def _restore(world: Environment[Any, Any]) -> None:
    observation_type, state_type = world._declared_types()
    state_path = Path("state.json")
    observation_path = Path("observation.json")
    if state_path.exists():
        world.state = state_type.model_validate_json(state_path.read_text(encoding="utf-8"))
    if observation_path.exists():
        world.observation = observation_type.model_validate_json(
            observation_path.read_text(encoding="utf-8")
        )


def _envelope(
    world: Environment[Any, Any],
    kind: str,
    *,
    reward: float = 0.0,
    terminated: bool | None = None,
    truncated: bool | None = None,
    info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "kind": kind,
        "observation": world.observation_snapshot(),
        "reward": reward,
        "terminated": world.terminated() if terminated is None else terminated,
        "truncated": world.truncated() if truncated is None else truncated,
        "info": info or {},
        # Display state for the run viewer. Recorded on the episode, never
        # returned to the Harness as part of the observation.
        "view": world.view() or None,
    }


def _dispatch(world: Environment[Any, Any], name: str) -> dict[str, Any]:
    if name == "reset":
        _observation, info = world.reset()
        return _envelope(world, "reset", info=info if isinstance(info, dict) else {})
    raw = sys.stdin.read().strip()
    params = json.loads(raw) if raw else {}
    if not isinstance(params, dict):
        raise ValueError("action parameters must be a JSON object")
    try:
        _observation, reward, terminated, truncated, info = world.step(name, **params)
    except ValueError as error:
        # Invalid Agent input is feedback, not an execution failure. The Agent
        # sees the error and can retry; the episode continues.
        return _envelope(world, "step", info={"error": str(error)})
    return _envelope(
        world,
        "step",
        reward=float(reward),
        terminated=terminated,
        truncated=truncated,
        info=info if isinstance(info, dict) else {},
    )


if __name__ == "__main__":
    main()
