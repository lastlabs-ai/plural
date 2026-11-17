"""Run an installed vendor CLI and normalize Plural artifacts."""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from plural.harness.deadline import call_timeout, episode_deadline
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
    resume = request.get("resume")
    result = run_vendor(
        vendor,
        HarnessTask.from_payload(task_payload),
        HarnessAgent(
            agent_payload,
            model_resolution=request.get("model_resolution") or {},
        ),
        HarnessEnvironment(
            environment_payload, resume=resume if isinstance(resume, dict) else None
        ),
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
    limits = environment.raw.get("limits")
    deadline = episode_deadline(limits if isinstance(limits, dict) else None)
    kwargs = agent.harness_config
    model = agent.model
    if model:
        os.environ.setdefault("PLURAL_MODEL", model)
    _write_environment(environment.raw)
    _write_config(vendor, kwargs.get("config"), root=Path(_host_workspace(environment)))
    _map_credentials(vendor, deadline)
    mcp_config = Path(".plural/mcp.json").resolve()
    resume = environment.resume
    if resume is not None and environment.raw.get("reset_command"):
        # The host's opening: observation k, or a diagnostic fork's forced action's result.
        environment.reset()
    prompt = _prompt(task, agent, environment)
    session: str | None = None
    if vendor == "claude-code":
        _write_claude_settings(environment)
        if resume is not None and resume.history == "native" and resume.messages:
            session = _write_claude_session(
                resume.messages, Path(_host_workspace(environment)), model
            )
            prompt = _continue_prompt(environment)
    command = _command(vendor, model, prompt, kwargs, mcp_config, session=session)
    if shutil.which(command[0]) is None:
        raise SystemExit(
            f"{vendor} requires installed executable {command[0]!r} on PATH. "
            "Plural installs it during Runtime setup; check network policy and the image tools."
        )
    if vendor == "codex" and environment.raw.get("tool_command"):
        completed = _run_reporting(command, environment, deadline)
    else:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=call_timeout(deadline),
            check=False,
            stdin=subprocess.DEVNULL,
            cwd=_host_workspace(environment),
        )
    if completed.returncode != 0:
        output = (completed.stderr or "", completed.stdout or "")
        detail = "\n".join(part.strip() for part in output if part.strip())
        raise SystemExit(f"{vendor} exited with code {completed.returncode}: {detail[-1500:]}")
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
    payload: dict[str, Any] = {
        "task": task.raw,
        "agent": agent.raw,
        "observation": environment.observation,
    }
    resume = environment.resume
    if resume is not None:
        if environment.observation is None:
            payload["observation"] = resume.observation
        if resume.history == "transcript" and resume.transcript:
            payload["history"] = resume.transcript
        else:
            payload["history"] = "This episode is already under way; earlier steps are not shown."
        if resume.note:
            payload["note"] = resume.note
    return json.dumps(payload, sort_keys=True)


def _continue_prompt(environment: HarnessEnvironment) -> str:
    """The message that continues a resumed Claude Code session."""
    resume = environment.resume
    current = environment.observation
    if current is not None:
        now = current if isinstance(current, str) else json.dumps(current, sort_keys=True)
    else:
        now = resume.rendered if resume is not None else ""
    text = "Continue the task from where you left off."
    parts = [f"{text}\n\nWhere things stand now:\n{now}" if now else text]
    if resume is not None and resume.note:
        parts.append(resume.note)
    return "\n\n".join(parts)


def _host_workspace(environment: HarnessEnvironment) -> str:
    from plural.harness.native_runner import _workspace_path

    return _workspace_path(environment.workspace)


def _write_claude_settings(environment: HarnessEnvironment) -> None:
    """A PostToolUse hook that reports each of Claude Code's own tool calls as a step."""
    if not environment.raw.get("tool_command"):
        return
    hook = (
        f"PLURAL_APPS_WORKSPACE={shlex.quote(_host_workspace(environment))} "
        f"{shlex.quote(sys.executable)} -m plural.apps.daemon tool --claude-hook"
    )
    settings = {
        "hooks": {
            "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": hook}]}]
        }
    }
    path = Path(".plural/claude-settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, sort_keys=True) + "\n", encoding="utf-8")


def _claude_config_dir() -> Path:
    folder = Path(".plural/claude").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_claude_session(messages: Any, workspace: Path, model: str | None) -> str:
    """Write a history as a Claude Code session, so ``--resume`` continues it natively.

    Returns:
        The session id.
    """
    session = str(uuid4())
    cwd = str(workspace.resolve())
    folder = (
        _claude_config_dir() / "projects" / "".join(char if char.isalnum() else "-" for char in cwd)
    )
    folder.mkdir(parents=True, exist_ok=True)
    lines: list[dict[str, Any]] = []
    parent: str | None = None
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def add(kind: str, message: dict[str, Any], **extra: Any) -> None:
        nonlocal parent
        uuid = str(uuid4())
        lines.append(
            {
                "parentUuid": parent,
                "isSidechain": False,
                "userType": "external",
                "cwd": cwd,
                "sessionId": session,
                "version": "2.1.236",
                "type": kind,
                "message": message,
                "uuid": uuid,
                "timestamp": stamp,
                **extra,
            }
        )
        parent = uuid

    for item in messages:
        if not isinstance(item, Mapping):
            continue
        role = item.get("role")
        content = item.get("content")
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        if role == "user":
            add("user", {"role": "user", "content": text or "(empty)"})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if text and text != "null":
                blocks.append({"type": "text", "text": text})
            for call in item.get("tool_calls") or ():
                function = call.get("function") or {}
                arguments = function.get("arguments")
                with contextlib.suppress(TypeError, ValueError):
                    arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": _tool_id(str(call.get("id") or "")),
                        "name": str(function.get("name") or "tool"),
                        "input": arguments if isinstance(arguments, dict) else {"input": arguments},
                    }
                )
            if not blocks:
                continue
            add(
                "assistant",
                {
                    "id": f"msg_{uuid4().hex[:24]}",
                    "type": "message",
                    "role": "assistant",
                    "model": model or "claude",
                    "content": blocks,
                    "stop_reason": "tool_use"
                    if len(blocks) > 1 or blocks[0]["type"] == "tool_use"
                    else "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            )
        elif role == "tool":
            add(
                "user",
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": _tool_id(str(item.get("tool_call_id") or "")),
                            "content": text,
                        }
                    ],
                },
            )
    (folder / f"{session}.jsonl").write_text(
        "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines), encoding="utf-8"
    )
    return session


def _tool_id(value: str) -> str:
    cleaned = "".join(char for char in value if char.isalnum() or char in "_-")
    return cleaned if cleaned.startswith("toolu_") else f"toolu_{cleaned or uuid4().hex[:24]}"


_CODEX_TOOLS = {
    "command_execution": "shell",
    "file_change": "apply_patch",
    "todo_list": "update_plan",
    "web_search": "web_search",
}


def codex_tool_fields(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """The tool call a finished Codex ``--json`` item describes, if it is one of Codex's own.

    Calls of the Environment's MCP tools are left out: the host ran those as actions.

    Returns:
        Fields for the App host's ``tool`` operation, or ``None``.
    """
    if event.get("type") != "item.completed":
        return None
    item = event.get("item")
    if not isinstance(item, Mapping):
        return None
    name = _CODEX_TOOLS.get(str(item.get("type") or item.get("item_type") or ""))
    if name is None:
        return None
    if name == "shell":
        command = item.get("command")
        arguments: dict[str, Any] = {"command": command}
        output: Any = item.get("aggregated_output")
        failed = item.get("exit_code") not in (None, 0)
        error = f"exit code {item.get('exit_code')}" if failed else None
    else:
        arguments = {
            key: value for key, value in item.items() if key not in {"id", "type", "item_type"}
        }
        output, error = None, None
    return {"name": name, "arguments": arguments, "output": output, "error": error}


def _run_reporting(
    command: tuple[str, ...], environment: HarnessEnvironment, deadline: float
) -> subprocess.CompletedProcess[str]:
    """Run Codex, reporting each of its own tool calls to the App host as it finishes."""
    import threading

    from plural.apps.daemon import call

    reporting = bool(environment.raw.get("tool_command"))
    root = Path(_host_workspace(environment))
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=_host_workspace(environment),
    )
    errors: list[str] = []
    reader = threading.Thread(
        target=lambda: errors.append(process.stderr.read() if process.stderr else ""),
        daemon=True,
    )
    reader.start()
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        if not reporting:
            continue
        with contextlib.suppress(ValueError):
            event = json.loads(line)
            fields = codex_tool_fields(event) if isinstance(event, dict) else None
            if fields is not None:
                with contextlib.suppress(OSError, RuntimeError, ValueError):
                    call("tool", root=root, timeout=30, **fields)
    try:
        process.wait(timeout=max(1.0, call_timeout(deadline)))
    except subprocess.TimeoutExpired:
        process.kill()
        raise
    reader.join(timeout=5)
    return subprocess.CompletedProcess(command, process.returncode, "".join(lines), "".join(errors))


def _command(
    vendor: str,
    model: str,
    prompt: str,
    kwargs: dict[str, Any],
    mcp_config: Path,
    *,
    session: str | None = None,
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
        settings = Path(".plural/claude-settings.json")
        if settings.is_file():
            extra.extend(["--settings", str(settings.resolve())])
        if session is not None:
            extra.extend(["--resume", session])
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
        base = os.environ.get("PLURAL_CODEX_BASE_URL")
        if base:
            provider = {
                "name": "Plural",
                "base_url": base,
                "env_key": "OPENAI_API_KEY",
                "wire_api": "responses",
            }
            extra.extend(["-c", "model_provider=plural"])
            for field, value in provider.items():
                extra.extend(["-c", f"model_providers.plural.{field}={json.dumps(value)}"])
        # The Runtime workspace is never a git repository Codex has been told to trust.
        return ("codex", "exec", "--json", "--skip-git-repo-check", *model_args, *extra, prompt)
    if vendor == "hermes":
        return ("hermes", "chat", *model_args, "--prompt", prompt)
    raise SystemExit(f"unknown vendor adapter {vendor!r}")


def _codex_home() -> Path:
    folder = Path(".plural/codex").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _start_responses_bridge(deadline: float) -> str:
    from plural.harness import responses_bridge

    _server, url = responses_bridge.start(deadline=deadline)
    return url


def _start_messages_bridge(deadline: float) -> str:
    import importlib.util

    path = Path(__file__).with_name("messages_bridge.py")
    spec = importlib.util.spec_from_file_location("plural_messages_bridge", path)
    if spec is None or spec.loader is None:
        raise SystemExit("Claude Code adapter could not load the local Messages bridge")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _server, url = module.start(deadline=deadline)
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


def _map_credentials(vendor: str, deadline: float) -> None:
    """Point the vendor CLI at the Plural gateway, and nowhere else.

    Every model call goes through the gateway, which bills and records it, so a
    provider key or base URL already in the environment is overwritten.
    """
    key = os.environ.get("PLURAL_API_KEY") or ""
    gateway = os.environ.get("PLURAL_GATEWAY_URL") or ""
    if not gateway:
        raise SystemExit(
            f"{vendor} is missing PLURAL_GATEWAY_URL in the environment. Model calls go "
            "through the Plural gateway; Job(client=...) and `plural run` set it."
        )
    if not key and not os.environ.get("PLURAL_ALLOW_NO_AUTH"):
        raise SystemExit(
            f"{vendor} is missing PLURAL_API_KEY in the environment. "
            "Job(client=...) and `plural run` set it."
        )
    if vendor == "claude-code":
        # Its own configuration, so no login, hook, or instruction on this machine applies.
        os.environ["CLAUDE_CONFIG_DIR"] = str(_claude_config_dir())
        os.environ["ANTHROPIC_BASE_URL"] = _start_messages_bridge(deadline)
        os.environ["ANTHROPIC_API_KEY"] = key or "plural"
        return
    if vendor == "codex":
        # Its own home, so Codex never falls back to a login on this machine.
        os.environ["CODEX_HOME"] = str(_codex_home())
        os.environ["OPENAI_API_KEY"] = key or "plural"
        os.environ["PLURAL_CODEX_BASE_URL"] = _start_responses_bridge(deadline)
        return
    os.environ["OPENAI_API_KEY"] = key or "plural"
    os.environ["OPENAI_BASE_URL"] = gateway


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
