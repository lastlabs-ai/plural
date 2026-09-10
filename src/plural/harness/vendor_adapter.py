"""Plural protocol adapters for separately installed vendor agent CLIs."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def main() -> None:
    """Invoke one installed vendor CLI and normalize its response."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: vendor_adapter.py {claude-code|codex|hermes-agent}")
    vendor = sys.argv[1]
    request = json.loads(sys.stdin.readline())
    environment = request.get("environment") or {}
    limits = environment.get("limits") or {}
    timeout = float(limits.get("max_seconds", 120))
    prompt = json.dumps(
        {
            "task": request.get("task"),
            "agent": request.get("agent"),
            "observation": environment.get("observation"),
        },
        sort_keys=True,
    )
    agent = request.get("agent") or {}
    model = str(agent.get("model") or "") if isinstance(agent, dict) else ""
    commands = {
        "claude-code": (
            "claude",
            "--print",
            "--output-format",
            "json",
            *(("--model", model) if model else ()),
            prompt,
        ),
        "codex": (
            "codex",
            "exec",
            "--json",
            *(("--model", model) if model else ()),
            prompt,
        ),
        "hermes-agent": (
            "hermes",
            "chat",
            *(("--model", model) if model else ()),
            "--prompt",
            prompt,
        ),
    }
    command = commands.get(vendor)
    if command is None:
        raise SystemExit(f"unknown vendor adapter {vendor!r}")
    if shutil.which(command[0]) is None:
        raise SystemExit(f"{vendor} adapter requires installed executable {command[0]!r} on PATH")
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"{vendor} exited with code {completed.returncode}: {completed.stderr[:1000]}"
        )
    response = _response(vendor, completed.stdout)
    trace_id = str(uuid4())
    result = {"response": response, "vendor": vendor, "trace_id": trace_id}
    Path("result.json").write_text(json.dumps(result, sort_keys=True) + "\n")
    Path("trajectory.jsonl").write_text(
        json.dumps(
            {"vendor": vendor, "stdout": completed.stdout, "stderr": completed.stderr},
            sort_keys=True,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "protocol": "plural-harness-v1",
                "type": "result",
                "status": "succeeded",
                "outputs": ["result.json"],
                "artifacts": ["trajectory.jsonl"],
                "trace_id": trace_id,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _response(vendor: str, stdout: str) -> str:
    if vendor == "claude-code":
        payload = json.loads(stdout)
        if isinstance(payload, dict):
            for key in ("result", "content", "text"):
                value = payload.get(key)
                if isinstance(value, str):
                    return value
    if vendor == "codex":
        values = []
        for line in stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                item = payload.get("item")
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    values.append(item["text"])
        if values:
            return "\n".join(values)
    if stdout.strip():
        return stdout.strip()
    raise ValueError(f"{vendor} emitted no usable response")


if __name__ == "__main__":
    main()
