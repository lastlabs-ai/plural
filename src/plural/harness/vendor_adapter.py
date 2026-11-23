"""Run an installed vendor CLI and normalize Plural artifacts."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
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


HERMES_USAGE = Path(".plural/hermes-usage.json")
"""Where Hermes reports its usage, beside the adapter and outside the Agent's workspace."""


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
    if vendor in _REPORTERS and environment.raw.get("tool_command"):
        completed = _run_reporting(command, environment, deadline, _REPORTERS[vendor]())
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
    usage = _hermes_usage() if vendor == "hermes" else None
    return HarnessResult(
        response=response,
        metadata={"vendor": vendor, "model": model},
        trajectory=(
            {
                "vendor": vendor,
                "model": model,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                **({"usage": usage} if usage is not None else {}),
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
    """Allow the Environment's tools, and report each of Claude Code's own tool calls.

    ``--print`` denies an MCP tool nobody allowed, so the Environment's server is
    allowed by name. Failed calls are reported too.
    """
    settings: dict[str, Any] = {"permissions": {"allow": [f"mcp__{ENVIRONMENT_SERVER}"]}}
    if environment.raw.get("tool_command"):
        hook = (
            f"PLURAL_APPS_WORKSPACE={shlex.quote(_host_workspace(environment))} "
            f"{shlex.quote(sys.executable)} -m plural.apps.daemon tool --claude-hook"
        )
        entry = [{"matcher": "*", "hooks": [{"type": "command", "command": hook}]}]
        settings["hooks"] = {"PostToolUse": entry, "PostToolUseFailure": entry}
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


Report = tuple[str, dict[str, Any]]


class StreamReports:
    """What a vendor CLI's output shows that the App host should record, read as it runs."""

    def event(self, event: Mapping[str, Any]) -> list[Report]:
        """Reports for one JSON event the CLI printed on stdout.

        Returns:
            ``(operation, fields)`` pairs for the App host.
        """
        return []

    def log(self, line: str) -> list[Report]:
        """Reports for one line the CLI logged on stderr.

        Returns:
            ``(operation, fields)`` pairs for the App host.
        """
        return []


def _unknown(name: str, arguments: Any) -> Report:
    return (
        "step",
        {
            "action": next(
                (name.removeprefix(item) for item in _ENVIRONMENT_TOOLS if name.startswith(item)),
                name,
            ),
            "arguments": arguments if isinstance(arguments, dict) else {"input": arguments},
            "unknown": True,
        },
    )


class ClaudeUnknownTools(StreamReports):
    """Each call of a tool that doesn't exist, read from Claude Code's ``stream-json`` events.

    Claude Code answers such a call itself and fires no hook for it, so the App host
    would never hear of it. Each one becomes an ``unknown_action`` step.

    Examples:
        >>> read = ClaudeUnknownTools().event
        >>> read(
        ...     {
        ...         "type": "assistant",
        ...         "message": {
        ...             "content": [
        ...                 {
        ...                     "type": "tool_use",
        ...                     "id": "t1",
        ...                     "name": "mcp__environment__quote",
        ...                     "input": {"tons": 3},
        ...                 }
        ...             ]
        ...         },
        ...     }
        ... )
        []
        >>> read(
        ...     {
        ...         "type": "user",
        ...         "message": {
        ...             "content": [
        ...                 {
        ...                     "type": "tool_result",
        ...                     "tool_use_id": "t1",
        ...                     "is_error": True,
        ...                     "content": "Error: No such tool available: x",
        ...                 }
        ...             ]
        ...         },
        ...     }
        ... )
        [('step', {'action': 'quote', 'arguments': {'tons': 3}, 'unknown': True})]
    """

    def __init__(self) -> None:
        self._calls: dict[str, tuple[str, Any]] = {}

    def event(self, event: Mapping[str, Any]) -> list[Report]:
        """The ``unknown_action`` steps one stream-json event shows.

        Returns:
            One ``step`` report per call of a tool that doesn't exist.
        """
        message = event.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list):
            return []
        reports: list[Report] = []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "tool_use":
                self._calls[str(block.get("id"))] = (
                    str(block.get("name") or ""),
                    block.get("input"),
                )
            elif block.get("type") == "tool_result" and _NO_SUCH_TOOL in _text(
                block.get("content")
            ):
                name, arguments = self._calls.pop(str(block.get("tool_use_id")), ("", None))
                if name:
                    reports.append(_unknown(name, arguments))
        return reports


def _text(content: Any) -> str:
    if isinstance(content, list):
        return " ".join(_text(item) for item in content)
    if isinstance(content, Mapping):
        return str(content.get("text") or "")
    return str(content or "")


_UNSUPPORTED_CALL = re.compile(r"unsupported call: (\S{1,128})")


class CodexReports(StreamReports):
    """Codex's own tool calls, from its events, and calls of tools that don't exist.

    Codex answers a call of a tool it doesn't have itself, and only logs it, without
    its arguments; each one becomes an ``unknown_action`` step.

    Examples:
        >>> CodexReports().log("ERROR codex_core::tools::router: error=unsupported call: quote")
        [('step', {'action': 'quote', 'arguments': {}, 'unknown': True})]
    """

    def event(self, event: Mapping[str, Any]) -> list[Report]:
        """Codex's own tool call one ``--json`` event finishes.

        Returns:
            A ``tool`` report, or none.
        """
        fields = codex_tool_fields(event)
        return [("tool", fields)] if fields is not None else []

    def log(self, line: str) -> list[Report]:
        """The ``unknown_action`` step one stderr line shows.

        Returns:
            A ``step`` report, or none.
        """
        found = _UNSUPPORTED_CALL.search(line)
        return [_unknown(found.group(1), {})] if found else []


_REPORTERS: dict[str, Callable[[], StreamReports]] = {
    "claude-code": ClaudeUnknownTools,
    "codex": CodexReports,
}


def _run_reporting(
    command: tuple[str, ...],
    environment: HarnessEnvironment,
    deadline: float,
    reports: StreamReports,
) -> subprocess.CompletedProcess[str]:
    """Run a vendor CLI, telling the App host what its output shows as it happens."""
    import threading

    from plural.apps.daemon import call

    root = Path(_host_workspace(environment))

    def send(found: list[Report]) -> None:
        for operation, fields in found:
            with contextlib.suppress(OSError, RuntimeError, ValueError):
                call(operation, root=root, timeout=30, **fields)

    def read_errors() -> None:
        for line in process.stderr or ():
            errors.append(line)
            send(reports.log(line))

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=_host_workspace(environment),
    )
    errors: list[str] = []
    reader = threading.Thread(target=read_errors, daemon=True)
    reader.start()
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        with contextlib.suppress(ValueError):
            event = json.loads(line)
            if isinstance(event, dict):
                send(reports.event(event))
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
            "stream-json",
            "--verbose",
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
        extra.extend(_codex_mcp_args(mcp_config))
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
        # A named custom provider: with "auto" and a vendor/model name, Hermes calls
        # OpenRouter itself. Its own config, rules and memory never apply.
        return (
            "hermes",
            "-z",
            prompt,
            *model_args,
            "--provider",
            "custom",
            "--usage-file",
            str(HERMES_USAGE.resolve()),
            "--yolo",
            "--ignore-user-config",
            "--ignore-rules",
        )
    raise SystemExit(f"unknown vendor adapter {vendor!r}")


def _hermes_usage() -> dict[str, Any] | None:
    """The usage report Hermes wrote: its model calls, tokens, and the provider it used."""
    try:
        value = json.loads(HERMES_USAGE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


ENVIRONMENT_SERVER = "environment"
"""The MCP server that offers a vendor CLI the Environment's actions. Its name is
part of every tool name the model sees, so it says nothing about Plural."""
_ENVIRONMENT_TOOLS = (f"mcp__{ENVIRONMENT_SERVER}__", "mcp__plural-environment__")
_NO_SUCH_TOOL = "No such tool available"


def _hermes_home() -> Path:
    folder = Path(".plural/hermes").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _codex_mcp_args(mcp_config: Path) -> list[str]:
    """``-c`` overrides that give Codex the Environment's MCP server, approved to run.

    Returns:
        The arguments, or none when there is no server.
    """
    if not mcp_config.is_file():
        return []
    servers = json.loads(mcp_config.read_text(encoding="utf-8")).get("mcpServers") or {}
    args: list[str] = []
    for name, server in servers.items():
        key = f"mcp_servers.{name}"
        env = ",".join(f"{field}={json.dumps(value)}" for field, value in server["env"].items())
        args.extend(["-c", f"{key}.command={json.dumps(server['command'])}"])
        args.extend(["-c", f"{key}.args={json.dumps(server['args'])}"])
        args.extend(["-c", f"{key}.env={{{env}}}"])
        # `codex exec` never asks, so an MCP tool nobody approved always fails.
        args.extend(["-c", f'{key}.default_tools_approval_mode="approve"'])
    return args


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
    env = {
        "PLURAL_ENVIRONMENT_FILE": str(path.resolve()),
        "PLURAL_ENVIRONMENT_WORKSPACE": str(
            environment.get("workspace") or "/workspace/environment"
        ),
    }
    if os.environ.get("PLURAL_SANDBOX_ROOT"):
        env["PLURAL_SANDBOX_ROOT"] = os.environ["PLURAL_SANDBOX_ROOT"]
    mcp = {
        "mcpServers": {
            ENVIRONMENT_SERVER: {
                "command": "python" if shutil.which("python") else sys.executable,
                "args": [str(Path(__file__).with_name("mcp_bridge.py"))],
                "env": env,
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
    # Hermes: its own home, and the bridge as its only endpoint. The bridge holds the
    # key, so no provider variable Hermes might send elsewhere carries it.
    os.environ["HERMES_HOME"] = str(_hermes_home())
    os.environ["CUSTOM_BASE_URL"] = _start_responses_bridge(deadline)
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"):
        os.environ.pop(name, None)


def _response(vendor: str, stdout: str) -> str:
    if vendor == "claude-code":
        # stream-json: the last "result" event is what --output-format json prints.
        payload: Any = None
        for line in stdout.splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                event = json.loads(line)
                if isinstance(event, dict) and event.get("type", "result") == "result":
                    payload = event
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
