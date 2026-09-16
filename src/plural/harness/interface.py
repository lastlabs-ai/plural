"""Standard values passed to every class-based Harness."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any

from pydantic import Field

from plural.common import FrozenModel


class HarnessTask(FrozenModel):
    """Task view supplied to ``Harness.run``."""

    id: str = ""
    name: str = ""
    instructions: str = ""
    info: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> HarnessTask:
        """Build a convenient Task view from the execution request."""
        return cls(
            id=str(payload.get("task_id") or payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            instructions=str(payload.get("instructions") or payload.get("input") or ""),
            info=payload.get("info"),
            metadata=(
                dict(payload["metadata"]) if isinstance(payload.get("metadata"), dict) else {}
            ),
            raw=payload,
        )


class HarnessCompletion(FrozenModel):
    """One model response returned by ``HarnessAgent.complete``."""

    text: str
    tool_calls: tuple[dict[str, Any], ...] = ()
    usage: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class HarnessAgent:
    """Agent configuration and model client supplied to ``Harness.run``."""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        model_resolution: dict[str, Any] | None = None,
    ) -> None:
        self.raw = dict(payload)
        self.name = str(payload.get("name") or "")
        self.model = str(payload.get("model") or "")
        self.instructions = str(payload.get("instructions") or "")
        self.routing = dict(payload["routing"]) if isinstance(payload.get("routing"), dict) else {}
        self.harness_kwargs = (
            dict(payload["harness_kwargs"])
            if isinstance(payload.get("harness_kwargs"), dict)
            else {}
        )
        self.model_resolution = dict(model_resolution or {})

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **options: Any,
    ) -> HarnessCompletion:
        """Call the Job's OpenAI-compatible model gateway."""
        model = (
            self.model_resolution.get("upstream_id")
            or self.model_resolution.get("model")
            or self.model
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            **self.routing,
            **options,
        }
        if tools:
            payload["tools"] = tools
        response = _gateway_request(payload)
        choices = response.get("choices")
        message: dict[str, Any] = {}
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            raw_message = choices[0].get("message")
            if isinstance(raw_message, dict):
                message = raw_message
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        raw_tool_calls = message.get("tool_calls")
        tool_calls = (
            tuple(item for item in raw_tool_calls if isinstance(item, dict))
            if isinstance(raw_tool_calls, list)
            else ()
        )
        usage = response.get("usage")
        return HarnessCompletion(
            text=text,
            tool_calls=tool_calls,
            usage=dict(usage) if isinstance(usage, dict) else {},
            raw=response,
        )


class HarnessEnvironment:
    """Environment controls supplied to ``Harness.run``."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.raw = dict(payload)
        self.name = str(payload.get("name") or "")
        self.overview = str(payload.get("overview") or "")
        self.workspace = str(payload.get("workspace") or "/workspace/environment")
        raw_actions = payload.get("actions")
        self.actions = (
            tuple(dict(item) for item in raw_actions if isinstance(item, dict))
            if isinstance(raw_actions, list)
            else ()
        )
        self._observation = payload.get("observation")

    @property
    def observation(self) -> Any:
        """Return the latest observation seen by this Harness."""
        return self._observation

    def tools(self) -> list[dict[str, Any]]:
        """Return Environment actions as OpenAI-compatible tools."""
        tools: list[dict[str, Any]] = []
        for action in self.actions:
            name = action.get("name")
            if not name:
                continue
            parameters = action.get("parameters")
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": str(name),
                        "description": str(action.get("description") or name),
                        "parameters": (
                            parameters
                            if isinstance(parameters, dict)
                            else {"type": "object", "additionalProperties": True}
                        ),
                    },
                }
            )
        return tools

    def reset(self) -> Any:
        """Reset the Environment and return its first observation."""
        raw_command = self.raw.get("reset_command")
        if not isinstance(raw_command, list) or not raw_command:
            return self._observation
        self._observation = self._exec(tuple(str(item) for item in raw_command))
        return self._observation

    def step(self, action: str, /, **arguments: Any) -> Any:
        """Run one named Environment action and return its observation."""
        declaration = next(
            (item for item in self.actions if str(item.get("name") or "") == action),
            None,
        )
        if declaration is None:
            available = ", ".join(
                str(item.get("name")) for item in self.actions if item.get("name")
            )
            raise ValueError(
                f"unknown Environment action {action!r}; available actions: {available or 'none'}"
            )
        raw_command = declaration.get("command")
        if not isinstance(raw_command, list) or not raw_command:
            raise ValueError(f"Environment action {action!r} has no executable command")
        self._observation = self._exec(
            tuple(str(item) for item in raw_command),
            stdin=json.dumps(arguments).encode(),
        )
        return self._observation

    def _exec(self, command: tuple[str, ...], stdin: bytes | None = None) -> Any:
        from plural.harness.native_runner import _action_environment, _workspace_path

        completed = subprocess.run(
            command,
            cwd=_workspace_path(self.workspace),
            env=_action_environment(self.raw),
            input=stdin,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Environment command failed with code {completed.returncode}: {detail[:2000]}"
            )
        text = completed.stdout.decode("utf-8", errors="replace").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"output": text}


class HarnessResult(FrozenModel):
    """Normalized value returned from ``Harness.run``."""

    response: Any
    trajectory: tuple[dict[str, Any], ...] = ()
    tito: tuple[dict[str, Any], ...] = ()
    logs: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None


def _gateway_request(payload: dict[str, Any]) -> dict[str, Any]:
    base = (os.environ.get("PLURAL_GATEWAY_URL") or os.environ.get("OPENAI_BASE_URL") or "").rstrip(
        "/"
    )
    if not base:
        raise RuntimeError(
            "HarnessAgent.complete requires Job(client=...) or Job(api_key=...) "
            "to configure the model gateway"
        )
    key = os.environ.get("PLURAL_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {key}"} if key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"model gateway rejected Harness request: {detail[:1000]}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("model gateway returned a non-object response")
    return result


__all__ = [
    "HarnessAgent",
    "HarnessCompletion",
    "HarnessEnvironment",
    "HarnessResult",
    "HarnessTask",
]
