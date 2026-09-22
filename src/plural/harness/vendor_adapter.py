"""Run an installed vendor CLI and normalize Plural artifacts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from plural.harness.interface import (
    HarnessAgent,
    HarnessEnvironment,
    HarnessResult,
    HarnessTask,
)


def main() -> None:
    """Compatibility entry point for direct vendor adapter execution."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: vendor_adapter.py {claude-code|codex|hermes}")
    vendor = sys.argv[1]
    if vendor == "hermes-agent":
        vendor = "hermes"
    request = json.loads(sys.stdin.readline())
    task_payload = request.get("task") or {}
    agent_payload = request.get("agent") or {}
    environment_payload = request.get("environment") or {}
    result = run_vendor(
        vendor,
        HarnessTask.from_payload(task_payload),
        HarnessAgent(
            agent_payload,
            model_resolution=request.get("model_resolution") or {},
        ),
        HarnessEnvironment(environment_payload),
    )
    trace_id = result.trace_id or str(uuid4())
    Path("result.json").write_text(
        json.dumps(
            {"response": result.response, "trace_id": trace_id, **result.metadata},
            sort_keys=True,
        )
        + "\n"
    )
    Path("trajectory.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in result.trajectory)
    )
    Path("logs.txt").write_text("\n".join(result.logs))
    print(
        json.dumps(
            {
                "protocol": "plural-harness-v1",
                "type": "result",
                "status": "succeeded",
                "outputs": ["result.json"],
                "artifacts": ["trajectory.jsonl", "logs.txt"],
                "trace_id": trace_id,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def run_vendor(
    vendor: str,
    task: HarnessTask,
    agent: HarnessAgent,
    environment: HarnessEnvironment,
) -> HarnessResult:
    """Run a built-in CLI through the same interface as a custom Harness."""
    limits = environment.raw.get("limits") or {}
    timeout = float(limits.get("max_seconds", 120))
    kwargs = agent.harness_kwargs
    model = agent.model
    if model:
        os.environ.setdefault("PLURAL_MODEL", model)
    _write_environment(environment.raw)
    _write_config(vendor, kwargs.get("config"), root=Path(environment.workspace))
    _map_credentials(vendor)
    mcp_config = Path(".plural/mcp.json").resolve()
    prompt = _prompt(task, agent, environment)
    command = _command(vendor, model, prompt, kwargs, mcp_config)
    if shutil.which(command[0]) is None:
        raise SystemExit(
            f"{vendor} requires installed executable {command[0]!r} on PATH. "
            "Plural installs it during Runtime setup; check network policy and the image tools."
        )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        cwd=environment.workspace,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"{vendor} exited with code {completed.returncode}: {(completed.stderr or '')[:1000]}"
        )
    response = _response(vendor, completed.stdout)
    return HarnessResult(
        response=response,
        metadata={"vendor": vendor, "model": model},
        trajectory=(
            {
                "vendor": vendor,
                "model": model,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        ),
        logs=tuple(item for item in (completed.stderr or "", completed.stdout or "") if item),
        trace_id=str(uuid4()),
    )


def _prompt(
    task: HarnessTask,
    agent: HarnessAgent,
    environment: HarnessEnvironment,
) -> str:
    return json.dumps(
        {
            "task": task.raw,
            "agent": agent.raw,
            "observation": environment.observation,
        },
        sort_keys=True,
    )


def _command(
    vendor: str,
    model: str,
    prompt: str,
    kwargs: dict[str, Any],
    mcp_config: Path,
) -> tuple[str, ...]:
    model_args = ("--model", model) if model else ()
    if vendor == "claude-code":
        extra: list[str] = []
        effort = kwargs.get("reasoning_effort")
        if effort:
            extra.extend(["--effort", str(effort)])
        permission = kwargs.get("permission_mode")
        if permission:
            extra.extend(["--permission-mode", str(permission)])
        max_turns = kwargs.get("max_turns")
        if max_turns:
            extra.extend(["--max-turns", str(max_turns)])
        if mcp_config.is_file():
            extra.extend(["--mcp-config", str(mcp_config)])
        return (
            "claude",
            "--print",
            "--output-format",
            "json",
            *model_args,
            *extra,
            prompt,
        )
    if vendor == "codex":
        extra = []
        effort = kwargs.get("reasoning_effort")
        if effort:
            extra.extend(["-c", f"model_reasoning_effort={effort}"])
        sandbox = kwargs.get("sandbox")
        if sandbox:
            extra.extend(["--sandbox", str(sandbox)])
        return ("codex", "exec", "--json", *model_args, *extra, prompt)
    if vendor == "hermes":
        return ("hermes", "chat", *model_args, "--prompt", prompt)
    raise SystemExit(f"unknown vendor adapter {vendor!r}")


def _start_messages_bridge() -> str:
    import importlib.util

    path = Path(__file__).with_name("messages_bridge.py")
    spec = importlib.util.spec_from_file_location("plural_messages_bridge", path)
    if spec is None or spec.loader is None:
        raise SystemExit("Claude Code adapter could not load the local Messages bridge")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _server, url = module.start()
    return str(url)


def _write_environment(environment: dict[str, Any]) -> None:
    root = Path(".plural")
    root.mkdir(parents=True, exist_ok=True)
    path = root / "environment.json"
    path.write_text(json.dumps(environment, sort_keys=True) + "\n", encoding="utf-8")
    os.environ["PLURAL_ENVIRONMENT_FILE"] = str(path)
    if environment.get("workspace"):
        os.environ["PLURAL_ENVIRONMENT_WORKSPACE"] = str(environment["workspace"])
    mcp = {
        "mcpServers": {
            "plural-environment": {
                "command": "python",
                "args": [str(Path(__file__).with_name("mcp_bridge.py"))],
                "env": {
                    "PLURAL_ENVIRONMENT_FILE": str(path.resolve()),
                    "PLURAL_ENVIRONMENT_WORKSPACE": str(
                        environment.get("workspace") or "/workspace/environment"
                    ),
                },
            }
        }
    }
    (root / "mcp.json").write_text(json.dumps(mcp, sort_keys=True) + "\n", encoding="utf-8")


def _write_config(vendor: str, config: Any, *, root: Path | None = None) -> None:
    if not isinstance(config, dict) or not config:
        return
    base = root or Path.cwd()
    names = {
        "claude-code": base / ".claude.json",
        "codex": base / ".codex/config.json",
        "hermes": base / ".hermes/config.json",
    }
    path = names.get(vendor)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _map_credentials(vendor: str) -> None:
    key = os.environ.get("PLURAL_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    gateway = os.environ.get("PLURAL_GATEWAY_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    if vendor == "claude-code":
        url = _start_messages_bridge()
        os.environ["ANTHROPIC_BASE_URL"] = url
        os.environ["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY") or key or "plural"
        if not gateway and not os.environ.get("PLURAL_ALLOW_NO_AUTH"):
            raise SystemExit(
                "Claude Code is missing PLURAL_GATEWAY_URL or OPENAI_BASE_URL in the "
                "environment, so model calls cannot authenticate. "
                "Job(client=...) sets PLURAL_GATEWAY_URL. "
                "Job(api_key=...) sets OPENAI_API_KEY."
            )
        return
    if key:
        os.environ.setdefault("OPENAI_API_KEY", key)
    if gateway:
        os.environ.setdefault("OPENAI_BASE_URL", gateway)
    if vendor in {"codex", "hermes"} and not (
        os.environ.get("OPENAI_API_KEY") or os.environ.get("PLURAL_ALLOW_NO_AUTH")
    ):
        raise SystemExit(
            f"{vendor} is missing a model key in the environment. "
            "Set one of: PLURAL_API_KEY, OPENAI_API_KEY. "
            "Job(client=...) and Job(api_key=...) set these for you."
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
