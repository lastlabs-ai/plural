"""Credential-free example implementation of plural-harness-v1."""

from __future__ import annotations

import json
import sys
from pathlib import Path

request = json.loads(sys.stdin.readline())
task = request["task"]
response = f"offline response for {task['task_id']}: {task['input']}"
Path("result.json").write_text(json.dumps({"response": response}) + "\n", encoding="utf-8")
Path("evidence.txt").write_text(response + "\n", encoding="utf-8")
Path("trajectory.jsonl").write_text(
    json.dumps({"type": "response", "text": response}) + "\n",
    encoding="utf-8",
)
print(
    json.dumps(
        {
            "protocol": "plural-harness-v1",
            "type": "result",
            "status": "succeeded",
            "outputs": ["result.json"],
            "artifacts": ["evidence.txt", "trajectory.jsonl"],
            "trace_id": f"offline-{task['task_id']}",
        },
        sort_keys=True,
    )
)
