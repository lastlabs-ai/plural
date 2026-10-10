"""Connect any MCP server as an App.

An MCP App turns a server's tools into actions and each tool result into the
observation for that step. It does not model the server's internals. A server
started with ``command`` runs inside the Runtime, so every Trial starts it
fresh and the App is ``owned``. A server reached by ``url`` lives elsewhere: it
is ``sandboxed`` when you give it a ``reset`` hook and ``live`` otherwise.

Settings that hold secrets reference them as ``${NAME}``; list each name in
``secrets`` so the Job supplies it::

    App.mcp(
        "crm",
        url="https://mcp.example.com/v1",
        headers={"Authorization": "Bearer ${CRM_TOKEN}"},
        secrets=["CRM_TOKEN"],
        tools=["create_record", "get_record"],
    )
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import select
import shlex
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from plural.apps.base import App
from plural.apps.definition import AppAction, SecretReference
from plural.environments.types import State

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "plural", "version": "1"}
_VARIABLE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class MCPError(RuntimeError):
    """The MCP server failed or answered with a protocol error."""


def expand(value: str, environ: Mapping[str, str] | None = None) -> str:
    """Replace ``${NAME}`` with the value of that environment variable.

    Returns:
        ``value`` with every reference replaced.

    Raises:
        MCPError: When a referenced variable is not set.
    """
    source = os.environ if environ is None else environ

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        found = source.get(name)
        if found is None:
            raise MCPError(
                f"{name} is not set. Export it to reach the server from here. In a Job, "
                "list it in the App's secrets and the Job supplies it."
            )
        return found

    return _VARIABLE.sub(replace, value)


def referenced_variables(values: Iterable[str]) -> set[str]:
    """Every ``${NAME}`` a list of settings references.

    Returns:
        The referenced names.
    """
    found: set[str] = set()
    for value in values:
        found.update(_VARIABLE.findall(value))
    return found


class _Stdio:
    """JSON-RPC over a server process's standard input and output."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: str | None,
        log: Path | None,
    ) -> None:
        stderr: Any = subprocess.DEVNULL
        self._log = None
        if log is not None:
            log.parent.mkdir(parents=True, exist_ok=True)
            self._log = log.open("ab")
            stderr = self._log
        try:
            self.process = subprocess.Popen(  # noqa: S603 - the App's declared server
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                env={**os.environ, **env},
                cwd=cwd,
            )
        except FileNotFoundError as exc:
            raise MCPError(f"Cannot start MCP server {command[0]!r}: {exc}") from exc
        self._buffer = bytearray()

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(json.dumps(message).encode() + b"\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPError(f"MCP server exited: {self._exit_detail()}") from exc

    def receive(self, deadline: float) -> dict[str, Any]:
        assert self.process.stdout is not None
        descriptor = self.process.stdout.fileno()
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self._buffer[:newline]).strip()
                del self._buffer[: newline + 1]
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPError("MCP server did not answer in time")
            ready, _, _ = select.select([descriptor], [], [], min(remaining, 1.0))
            if not ready:
                continue
            chunk = os.read(descriptor, 65536)
            if not chunk:
                raise MCPError(f"MCP server exited: {self._exit_detail()}")
            self._buffer.extend(chunk)

    def _exit_detail(self) -> str:
        code = self.process.poll()
        return f"exit code {code}" if code is not None else "closed its output"

    def close(self) -> None:
        with contextlib.suppress(Exception):
            if self.process.stdin is not None:
                self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if self._log is not None:
            self._log.close()


class _Http:
    """JSON-RPC over MCP's Streamable HTTP transport."""

    def __init__(self, url: str, *, headers: Mapping[str, str]) -> None:
        import httpx

        self.url = url
        self.headers = dict(headers)
        self.session_id: str | None = None
        self.protocol: str | None = None
        self._client = httpx.Client(timeout=None, follow_redirects=True)
        self._pending: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        import httpx

        headers = {
            **self.headers,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        try:
            response = self._client.post(self.url, headers=headers, json=message)
        except httpx.HTTPError as exc:
            raise MCPError(f"Cannot reach MCP server {self.url}: {exc}") from exc
        session = response.headers.get("mcp-session-id")
        if session:
            self.session_id = session
        if response.status_code == 202 or "id" not in message or "method" not in message:
            return
        if response.status_code in {401, 403}:
            raise MCPError(
                f"MCP server {self.url} refused the request ({response.status_code}). "
                "Check the credentials in the App's headers and secrets."
            )
        if response.status_code >= 400:
            raise MCPError(
                f"MCP server {self.url} answered {response.status_code}: {response.text[:500]}"
            )
        kind = response.headers.get("content-type", "")
        if "text/event-stream" in kind:
            self._pending.extend(_sse_messages(response.text))
        elif response.content:
            parsed = response.json()
            self._pending.extend(parsed if isinstance(parsed, list) else [parsed])

    def receive(self, deadline: float) -> dict[str, Any]:
        del deadline
        while self._pending:
            item = self._pending.pop(0)
            if isinstance(item, dict):
                return item
        raise MCPError(f"MCP server {self.url} sent no response")

    def close(self) -> None:
        if self.session_id:
            with contextlib.suppress(Exception):
                self._client.delete(
                    self.url, headers={**self.headers, "Mcp-Session-Id": self.session_id}
                )
        self._client.close()


def _sse_messages(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            with contextlib.suppress(json.JSONDecodeError):
                parsed = json.loads("\n".join(data))
                messages.extend(parsed if isinstance(parsed, list) else [parsed])
            data = []
    return [item for item in messages if isinstance(item, dict)]


class MCPClient:
    """A minimal MCP client: initialize, list tools, call tools."""

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        url: str | None = None,
        headers: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        log: Path | None = None,
        timeout_seconds: float = 60,
    ) -> None:
        if bool(command) == bool(url):
            raise MCPError("An MCP App needs exactly one of command or url")
        self.timeout_seconds = timeout_seconds
        self._next_id = 0
        self.transport: _Stdio | _Http = (
            _Stdio(command, env=env or {}, cwd=cwd, log=log)
            if command
            else _Http(str(url), headers=headers or {})
        )
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        self.server_info = result.get("serverInfo") or {}
        if isinstance(self.transport, _Http):
            self.transport.protocol = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        self.transport.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Send one request and wait for its result.

        Returns:
            The JSON-RPC result.

        Raises:
            MCPError: When the server answers with an error or not at all.
        """
        self._next_id += 1
        ident = self._next_id
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": ident, "method": method}
        if params is not None:
            message["params"] = params
        self.transport.send(message)
        deadline = time.monotonic() + (timeout or self.timeout_seconds)
        while True:
            reply = self.transport.receive(deadline)
            if reply.get("id") == ident and ("result" in reply or "error" in reply):
                if "error" in reply:
                    error = reply.get("error") or {}
                    detail = error.get("message") if isinstance(error, dict) else error
                    raise MCPError(f"MCP {method} failed: {detail}")
                result = reply.get("result")
                return result if isinstance(result, dict) else {}
            if "method" in reply and "id" in reply:
                # The server asked us something (roots, sampling). Plural offers none.
                self.transport.send(
                    {
                        "jsonrpc": "2.0",
                        "id": reply["id"],
                        "error": {"code": -32601, "message": "not supported by Plural"},
                    }
                )

    def list_tools(self) -> list[dict[str, Any]]:
        """Return every tool the server offers, following pagination."""
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(item for item in result.get("tools") or [] if isinstance(item, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(
        self, name: str, arguments: Mapping[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Call one tool.

        Returns:
            The raw ``CallToolResult``.
        """
        return self.request(
            "tools/call", {"name": name, "arguments": dict(arguments)}, timeout=timeout
        )

    def close(self) -> None:
        """End the session and stop a server process."""
        self.transport.close()


def tool_text(result: Mapping[str, Any]) -> str:
    """The readable text of a ``CallToolResult``.

    Returns:
        Text content joined by blank lines, with other content described.
    """
    parts: list[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text") or ""))
        elif kind == "resource":
            resource = item.get("resource") or {}
            parts.append(str(resource.get("text") or f"[resource {resource.get('uri')}]"))
        elif kind == "resource_link":
            parts.append(f"[resource {item.get('uri')}]")
        else:
            parts.append(f"[{kind} {item.get('mimeType') or ''}]".replace(" ]", "]"))
    return "\n\n".join(part for part in parts if part)


def tool_action(tool: Mapping[str, Any], timeout_seconds: float) -> AppAction:
    """Turn one MCP tool declaration into an App action.

    Returns:
        The action.
    """
    annotations = tool.get("annotations") or {}
    schema = tool.get("inputSchema")
    return AppAction(
        name=str(tool["name"]),
        description=str(tool.get("description") or tool.get("title") or tool["name"]).strip(),
        parameters=schema
        if isinstance(schema, dict)
        else {"type": "object", "additionalProperties": True},
        mutates_state=not bool(
            isinstance(annotations, dict) and annotations.get("readOnlyHint") is True
        ),
        timeout_seconds=timeout_seconds,
    )


def _argv(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    return shlex.split(value) if isinstance(value, str) else [str(item) for item in value]


class MCPApp(App[State]):
    """An App backed by an MCP server.

    Settings:
        command: Start the server inside the Runtime, such as
            ``["npx", "-y", "@modelcontextprotocol/server-memory"]``.
        url: Reach a server over Streamable HTTP instead.
        headers: HTTP headers; values may reference ``${SECRET}``.
        env: Environment variables for a command server; values may
            reference ``${SECRET}``.
        cwd: Working folder for a command server, relative to the workspace.
        tools: Only offer these tools. Default: every tool.
        exclude: Never offer these tools.
        reset: Command run at the start of each episode, from the workspace,
            with the App's initial state as JSON on stdin. Use it to seed a
            sandbox tenant. Its output, if any, is the App's first observation.
        snapshot: Command that prints the App's state as JSON, for Verifiers.
        snapshot_on_step: Also snapshot before and after each action, so
            rewarders receive states. Off by default because it costs a call.
        actions: Tool declarations to use instead of asking the server, so a
            definition can be built without reaching it.
        secrets: Names the Job must supply.
        timeout_seconds: How long one tool call may run.

    Subclass ``MCPApp`` to write ``reset`` or ``snapshot`` in Python with
    :meth:`call_tool`, or to add ``@rewarder`` methods.
    """

    kind = "mcp"
    snapshot_on_step = False

    def __init__(
        self,
        *,
        name: str | None = None,
        command: str | Sequence[str] | None = None,
        url: str | None = None,
        headers: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        tools: Sequence[str] | None = None,
        exclude: Sequence[str] = (),
        reset: str | Sequence[str] | None = None,
        snapshot: str | Sequence[str] | None = None,
        snapshot_on_step: bool = False,
        actions: Sequence[Mapping[str, Any] | AppAction] | None = None,
        secrets: Iterable[str | SecretReference] | None = None,
        description: str | None = None,
        timeout_seconds: float = 60,
    ) -> None:
        super().__init__(
            name=name or type(self).name or None, description=description, secrets=secrets
        )
        self.command = _argv(command)
        self.url = url
        if bool(self.command) == bool(url):
            raise ValueError(
                f"MCP App {self.name!r} needs exactly one of command (a server started in "
                "the Runtime) or url (a server reached over HTTP)"
            )
        self.headers = dict(headers or {})
        self.env = dict(env or {})
        self.cwd = cwd
        self.tool_filter = tuple(tools) if tools is not None else None
        self.exclude = tuple(exclude)
        self.reset_command = _argv(reset)
        self.snapshot_command = _argv(snapshot)
        self.snapshot_on_step = snapshot_on_step  # type: ignore[misc]
        self.timeout_seconds = timeout_seconds
        self._pinned = (
            tuple(
                item if isinstance(item, AppAction) else AppAction.model_validate(item)
                for item in actions
            )
            if actions is not None
            else None
        )
        self._client: MCPClient | None = None
        undeclared = sorted(
            referenced_variables([*self.headers.values(), *self.env.values()])
            - {SecretReference.model_validate(item).name for item in self.secrets}
        )
        if undeclared:
            raise ValueError(
                f"MCP App {self.name!r} references {', '.join(undeclared)} but does not list "
                f"it in secrets. Add secrets={undeclared!r} so a Job supplies the value."
            )

    # Connection.

    def connect(self) -> MCPClient:
        """Open the MCP session, or return the open one.

        Returns:
            The connected client.
        """
        if self._client is None:
            log = self.workspace / ".plural" / "apps" / self.name / "server.log"
            cwd = str((self.workspace / self.cwd).resolve()) if self.cwd else str(self.workspace)
            self._client = MCPClient(
                command=self.command or None,
                url=self.url,
                headers={key: expand(value) for key, value in self.headers.items()},
                env={key: expand(value) for key, value in self.env.items()},
                cwd=cwd if self.command else None,
                log=log if self.command else None,
                timeout_seconds=self.timeout_seconds,
            )
        return self._client

    def call_tool(self, tool: str, **arguments: Any) -> Any:
        """Call one of the server's tools and return its observation.

        Use this from a Python ``reset`` or ``snapshot`` override.

        Returns:
            Structured content when the tool returns it, otherwise text.

        Raises:
            ValueError: When the tool reports an error.
        """
        result = self.connect().call_tool(tool, arguments, timeout=self.timeout_seconds)
        text = tool_text(result)
        if result.get("isError"):
            raise ValueError(text or f"{tool} failed")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        return text

    # App interface.

    def actions(self) -> tuple[AppAction, ...]:
        """The server's tools, filtered by ``tools`` and ``exclude``.

        Returns:
            One action per offered tool.
        """
        if self._pinned is not None:
            offered = self._pinned
        else:
            offered = tuple(
                tool_action(item, self.timeout_seconds) for item in self.connect().list_tools()
            )
        by_name = {item.name: item for item in offered}
        if self.tool_filter is not None:
            missing = [item for item in self.tool_filter if item not in by_name]
            if missing and self._pinned is None:
                available = ", ".join(sorted(by_name)) or "none"
                raise ValueError(
                    f"MCP App {self.name!r} lists tools the server does not offer: "
                    f"{', '.join(missing)}. The server offers: {available}"
                )
            offered = tuple(by_name[item] for item in self.tool_filter if item in by_name)
        return tuple(item for item in offered if item.name not in self.exclude)

    def call(self, action: str, arguments: Mapping[str, Any]) -> Any:
        """Call the tool behind one action.

        Returns:
            The tool's observation.
        """
        offered = {item.name for item in self.actions()}
        if action not in offered:
            raise ValueError(
                f"unknown action {action!r}; available actions: {', '.join(sorted(offered))}"
            )
        return self.call_tool(action, **dict(arguments))

    def reset(self, initial_state: Mapping[str, Any]) -> Any:
        """Run the ``reset`` command, if any, and open the session.

        Returns:
            The command's output, or ``None``.
        """
        opening = None
        if self.reset_command:
            output = self._run(self.reset_command, stdin=json.dumps(dict(initial_state)))
            opening = output.strip() or None
        self.connect()
        return opening

    def snapshot(self) -> Any:
        """Run the ``snapshot`` command.

        Returns:
            Its JSON output, or ``None`` without a snapshot command.
        """
        if not self.snapshot_command:
            return None
        output = self._run(self.snapshot_command, stdin="")
        try:
            return json.loads(output) if output.strip() else None
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCP App {self.name!r} snapshot did not print JSON: {exc}") from exc

    def has_reset(self) -> bool:
        """Whether a reset command or Python ``reset`` override sets up each episode.

        Returns:
            True when episodes start from a known state.
        """
        return bool(self.reset_command) or type(self).reset is not MCPApp.reset

    def has_snapshot(self) -> bool:
        """Whether a snapshot command or Python override reports state.

        Returns:
            True when the App can report its state.
        """
        return bool(self.snapshot_command) or type(self).snapshot is not MCPApp.snapshot

    def is_local(self) -> bool:
        """Whether the server runs inside the Runtime.

        Returns:
            True for a server started as a command.
        """
        return bool(self.command)

    def close(self) -> None:
        """Close the MCP session."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _run(self, command: Sequence[str], *, stdin: str) -> str:
        completed = subprocess.run(  # noqa: S603 - the App's declared hook
            list(command),
            input=stdin.encode(),
            capture_output=True,
            cwd=str(self.workspace),
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).decode(errors="replace")[-2000:]
            raise RuntimeError(
                f"MCP App {self.name!r} hook {' '.join(command)} failed "
                f"({completed.returncode}): {detail}"
            )
        return completed.stdout.decode(errors="replace")

    def _config(self) -> dict[str, Any]:
        config = super()._config()
        config.pop("actions", None)
        return config

    def _state_schema(self) -> dict[str, Any]:
        return {}


__all__ = ["MCPApp", "MCPClient", "MCPError", "expand", "tool_action", "tool_text"]
