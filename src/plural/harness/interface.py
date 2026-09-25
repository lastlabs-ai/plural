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
from plural.harness.episode import EpisodeRecorder
from plural.usage import normalize_usage


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
        recorder: EpisodeRecorder | None = None,
    ) -> None:
        self._recorder = recorder
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
        started = self._recorder.start() if self._recorder else None
        try:
            response = _gateway_request(payload)
        except Exception as exc:
            if self._recorder and started:
                self._recorder.model_call(
                    started, model=str(model), messages=messages, tools=tools, error=str(exc)
                )
            raise
        choices = response.get("choices")
        message: dict[str, Any] = {}
        finish_reason: str | None = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            raw_message = choices[0].get("message")
            if isinstance(raw_message, dict):
                message = raw_message
            if isinstance(choices[0].get("finish_reason"), str):
                finish_reason = choices[0]["finish_reason"]
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        raw_tool_calls = message.get("tool_calls")
        tool_calls = (
            tuple(item for item in raw_tool_calls if isinstance(item, dict))
            if isinstance(raw_tool_calls, list)
            else ()
        )
        usage = response.get("usage")
        raw_usage = dict(usage) if isinstance(usage, dict) else {}
        if self._recorder and started:
            self._recorder.model_call(
                started,
                model=str(response.get("model") or model),
                messages=messages,
                tools=tools,
                text=text,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=normalize_usage(raw_usage, cost=response.get("cost")),
            )
        return HarnessCompletion(
            text=text,
            tool_calls=tool_calls,
            usage=raw_usage,
            raw=response,
        )


class HarnessStep(FrozenModel):
    """One Environment transition returned to a custom Harness.

    ``reward`` is recorded on the episode for credit assignment. Do not place it
    in the Agent's context: it can leak the expected outcome.
    """

    observation: Any = None
    reward: float = 0
    terminated: bool = False
    truncated: bool = False
    info: dict[str, Any] = Field(default_factory=dict)

    @property
    def done(self) -> bool:
        """Whether the Environment ended the episode."""
        return self.terminated or self.truncated


class HarnessEnvironment:
    """Environment controls supplied to ``Harness.run``."""

    def __init__(self, payload: dict[str, Any], *, recorder: EpisodeRecorder | None = None) -> None:
        self._recorder = recorder
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
        self.turns = 0
        self.terminated = False
        self.truncated = False

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
        started = self._recorder.start() if self._recorder else None
        try:
            step, view = self._exec(tuple(str(item) for item in raw_command))
        except Exception as exc:
            if self._recorder and started:
                self._recorder.reset(started, error=str(exc))
            raise
        self._observation = step.observation
        if self._recorder and started:
            self._recorder.reset(started, observation=step.observation, info=step.info, view=view)
        return self._observation

    def step(self, action: str, /, **arguments: Any) -> HarnessStep:
        """Run one named Environment action.

        Returns:
            The transition: observation, reward, terminated, truncated, info.
        """
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
        started = self._recorder.start() if self._recorder else None
        try:
            step, view = self._exec(
                tuple(str(item) for item in raw_command),
                stdin=json.dumps(arguments).encode(),
            )
        except Exception as exc:
            if self._recorder and started:
                self._recorder.step(started, action=action, arguments=arguments, error=str(exc))
            raise
        self._observation = step.observation
        self.turns += 1
        self.terminated = step.terminated
        self.truncated = step.truncated
        if self._recorder and started:
            self._recorder.step(
                started,
                action=action,
                arguments=arguments,
                observation=step.observation,
                reward=step.reward,
                terminated=step.terminated,
                truncated=step.truncated,
                info=step.info,
                view=view,
            )
        return step

    def _exec(
        self, command: tuple[str, ...], stdin: bytes | None = None
    ) -> tuple[HarnessStep, dict[str, Any] | None]:
        from plural.harness.native_runner import (
            STEP_PROTOCOL,
            _action_environment,
            _local_command,
            _workspace_path,
        )

        completed = subprocess.run(
            _local_command(list(command)),
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
            return HarnessStep(observation={}), None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return HarnessStep(observation={"output": text}), None
        if isinstance(parsed, dict) and parsed.get("protocol") == STEP_PROTOCOL:
            info = parsed.get("info")
            view = parsed.get("view")
            return (
                HarnessStep(
                    observation=parsed.get("observation"),
                    reward=float(parsed.get("reward") or 0),
                    terminated=bool(parsed.get("terminated")),
                    truncated=bool(parsed.get("truncated")),
                    info=info if isinstance(info, dict) else {},
                ),
                view if isinstance(view, dict) and view else None,
            )
        return HarnessStep(observation=parsed), None


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
    "HarnessStep",
    "HarnessTask",
]
