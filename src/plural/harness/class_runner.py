"""Load and execute one class-based Harness inside a Runtime."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from plural.harness.episode import EPISODE_FILE, EpisodeRecorder
from plural.harness.interface import (
    HarnessAgent,
    HarnessEnvironment,
    HarnessResult,
    HarnessTask,
)
from plural.harness.models import Harness


def main(argv: list[str] | None = None) -> None:
    """Read one execution request, invoke ``Harness.run``, and emit artifacts."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in {1, 2}:
        raise SystemExit(
            "usage: python -m plural.harness.class_runner file.py:HarnessClass [CONFIG_JSON]"
        )
    config = json.loads(args[1]) if len(args) == 2 else {}
    if not isinstance(config, dict):
        raise SystemExit("Harness config must be a JSON object")
    harness = _load(args[0], config)
    request = json.loads(sys.stdin.readline())
    if not isinstance(request, dict):
        raise SystemExit("Harness request must be a JSON object")
    task_payload = request.get("task")
    agent_payload = request.get("agent")
    environment_payload = request.get("environment")
    if not isinstance(task_payload, dict):
        raise SystemExit("Harness request is missing task")
    if not isinstance(agent_payload, dict):
        raise SystemExit("Harness request is missing agent")
    if not isinstance(environment_payload, dict):
        raise SystemExit("Harness request is missing environment")
    task = HarnessTask.from_payload(task_payload)
    recorder = EpisodeRecorder(EPISODE_FILE)
    agent = HarnessAgent(
        agent_payload,
        model_resolution=(
            request["model_resolution"] if isinstance(request.get("model_resolution"), dict) else {}
        ),
        recorder=recorder,
    )
    environment = HarnessEnvironment(environment_payload, recorder=recorder)
    try:
        value = harness.run(task, agent, environment)
        if inspect.isawaitable(value):
            value = asyncio.run(_await_value(value))
        result = _normalize(value)
        _write_result(result)
    except Exception as exc:  # noqa: BLE001 - normalize user Harness failures
        print(
            json.dumps(
                {
                    "protocol": "plural-harness-v1",
                    "type": "error",
                    "status": "failed",
                    "message": f"{type(harness).name}.run failed: {exc}",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def _load(reference: str, config: dict[str, Any]) -> Harness:
    script, separator, qualname = reference.partition(":")
    if not separator or not script or not qualname:
        raise SystemExit(f"Harness reference must be file.py:Class, got {reference!r}")
    path = Path(script)
    if not path.is_file():
        path = Path.cwd() / script
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"Harness file not found: {script}")
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(f"_plural_harness_{uuid4().hex}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load Harness file: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    target: Any = module
    for part in qualname.split("."):
        target = getattr(target, part)
    if not inspect.isclass(target) or not issubclass(target, Harness):
        raise SystemExit(f"{reference} is not a Harness subclass")
    return target(config=config)


def _normalize(value: Any) -> HarnessResult:
    if isinstance(value, HarnessResult):
        return value
    if isinstance(value, (str, dict, list)):
        return HarnessResult(response=value)
    raise TypeError(
        "Harness.run must return HarnessResult, a string, a mapping, or a list; "
        f"got {type(value).__name__}"
    )


async def _await_value(value: Any) -> Any:
    return await value


def _encodable(value: Any) -> Any:
    """Serialize values a Harness may pass through, such as HarnessStep."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=_encodable)


def _write_result(result: HarnessResult) -> None:
    trace_id = result.trace_id or str(uuid4())
    payload = {
        "response": result.response,
        "trace_id": trace_id,
        **result.metadata,
    }
    Path("result.json").write_text(
        _dumps(payload) + "\n",
        encoding="utf-8",
    )
    artifacts: list[str] = []
    if result.trajectory:
        Path("trajectory.jsonl").write_text(
            "".join(_dumps(item) + "\n" for item in result.trajectory),
            encoding="utf-8",
        )
        artifacts.append("trajectory.jsonl")
    if result.logs:
        Path("logs.txt").write_text("\n".join(result.logs) + "\n", encoding="utf-8")
        artifacts.append("logs.txt")
    if result.tito:
        Path("tito.jsonl").write_text(
            "".join(_dumps(item) + "\n" for item in result.tito),
            encoding="utf-8",
        )
        artifacts.append("tito.jsonl")
    episode = Path(EPISODE_FILE)
    if episode.exists() and episode.stat().st_size:
        artifacts.append(EPISODE_FILE)
    print(
        json.dumps(
            {
                "protocol": "plural-harness-v1",
                "type": "result",
                "status": "succeeded",
                "outputs": ["result.json"],
                "artifacts": artifacts,
                "trace_id": trace_id,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
