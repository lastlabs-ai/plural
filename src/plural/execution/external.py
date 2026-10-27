"""Run one episode with an External Agent: a service that runs somewhere else.

The Job resets the Environment, opens the episode on its episode server,
and sends the agent a signed start request. The agent acts through the
App host like any Harness, so the host records every step; its own trace is
kept apart, as self-reported. The episode ends when the agent finishes, or
at the Environment's ``max_seconds``.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from plural.agents import AgentBinding
from plural.atif import AGENT_TRACE_FILE
from plural.execution.apps import WORKSPACE
from plural.execution.episode_server import EpisodeRefused, EpisodeServer, EpisodeSession
from plural.external.protocol import (
    EpisodeAction,
    EpisodeGateway,
    EpisodeStart,
    EpisodeTask,
    sign,
)
from plural.harness.native_runner import SEAT_TOKEN, STEP_PROTOCOL
from plural.harness.protocol import FORBIDDEN_HARNESS_KEYS, HarnessRunRequest, find_forbidden
from plural.harness.runner import HarnessExecution, HarnessExecutionError
from plural.sandbox import DownloadedFile, ExecRequest, SandboxHandle, SandboxProvider

"""The External Agent's own ATIF trace. Self-reported, so nothing scores from it."""
MAX_START_REPLY_BYTES = 4 * 1024 * 1024
_SECRET_TASK_KEYS = FORBIDDEN_HARNESS_KEYS - {"actions"}
_ACTION_VARIABLES = frozenset(
    {
        "PATH",
        "PYTHONPATH",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "HOME",
        "SYSTEMROOT",
        "PLURAL_APPS_MANAGED",
        "PLURAL_RESOURCES_DIR",
        SEAT_TOKEN,
    }
)


@dataclass
class ExternalRun:
    """What one External Agent episode left behind."""

    execution: HarnessExecution
    artifacts: tuple[DownloadedFile, ...]
    actions: tuple[str, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExternalAgentRunner:
    """Runs External Agent episodes in Runtimes the Job owns."""

    def __init__(self, provider: SandboxProvider, server: EpisodeServer) -> None:
        self.provider = provider
        self.server = server

    async def run(
        self,
        handle: SandboxHandle,
        binding: AgentBinding,
        request: HarnessRunRequest,
        *,
        key: bytes,
        env: Mapping[str, str],
        user: str | None,
        files: Mapping[str, bytes],
        timeout_seconds: float,
        gateway: EpisodeGateway | None = None,
        on_token: Any = None,
    ) -> ExternalRun:
        """Run one episode to its finish or its deadline.

        ``on_token`` is called with the episode's token before it leaves this
        process, so the caller can mask it everywhere it stores text.

        Returns:
            The execution, and its ``result.json`` and self-reported trace.

        Raises:
            HarnessExecutionError: When the agent can't be reached or refuses the episode.
            TimeoutError: When it does not finish within ``timeout_seconds``.
        """
        external = binding.external
        assert external is not None
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        deadline = time.time() + timeout_seconds
        environment = request.environment
        declared = {
            str(item["name"]): item for item in environment.get("actions") or () if item.get("name")
        }
        variables = _ACTION_VARIABLES | set(environment.get("variable_names") or ())
        action_env = {name: value for name, value in env.items() if name in variables}
        outcome = {"terminated": False, "truncated": False}

        async def step(command: list[str], arguments: dict[str, Any] | None) -> dict[str, Any]:
            result = await self.provider.exec(
                handle,
                ExecRequest(
                    command=tuple(command),
                    cwd=WORKSPACE,
                    env=action_env,
                    stdin=json.dumps(arguments).encode() if arguments is not None else None,
                    timeout_seconds=max(1.0, deadline - time.time()),
                    user=user,
                ),
            )
            if result.timed_out:
                raise EpisodeRefused(504, "The action ran out of time.")
            if result.exit_code != 0:
                detail = (result.stderr or result.stdout).decode("utf-8", errors="replace")
                raise EpisodeRefused(422, f"The action failed: {detail.strip()[-2000:]}")
            return _transition(result.stdout)

        async def act(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            reply = await step(list(declared[name]["command"]), arguments)
            outcome["terminated"] = reply["terminated"]
            outcome["truncated"] = reply["truncated"]
            return reply

        observation = None
        reset = [str(item) for item in environment.get("reset_command") or ()]
        if reset:
            try:
                observation = (await step(reset, None))["observation"]
            except EpisodeRefused as exc:
                raise HarnessExecutionError(f"The Environment did not reset: {exc}") from None
        task = EpisodeTask.model_validate(
            {name: value for name, value in request.task.items() if value is not None}
        )
        leaked = find_forbidden(task.model_dump(mode="json"), _SECRET_TASK_KEYS)
        if leaked is not None:
            raise HarnessExecutionError(
                f"The Task's info has {leaked!r}, which an agent must never see. Move it to "
                "the Task's expected, which only Verifiers read, or the App's State."
            )
        actions = tuple(
            EpisodeAction(
                name=name,
                description=str(item.get("description") or ""),
                parameters=item.get("parameters")
                if isinstance(item.get("parameters"), dict)
                else {},
            )
            for name, item in declared.items()
        )
        raw_turns = (environment.get("limits") or {}).get("max_turns")
        max_turns = None if raw_turns is None else int(raw_turns)
        session, token, urls = await self.server.register(
            actions=actions, files=files, max_turns=max_turns, deadline=deadline, act=act
        )
        if on_token is not None:
            on_token(token)
        start = EpisodeStart(
            episode_id=session.episode_id,
            task=task,
            agent={
                "name": binding.name,
                "model": binding.model,
                "instructions": binding.agent.instructions,
            },
            observation=observation,
            actions=actions,
            files=tuple(sorted(files)),
            urls=urls,
            token=token,
            deadline=datetime.fromtimestamp(deadline, timezone.utc).isoformat(),
            max_turns=max_turns,
            gateway=gateway,
        )
        body = start.model_dump_json(exclude_none=True).encode()
        sending = asyncio.create_task(
            _post(
                external.url,
                body,
                headers=sign(key, body, message_id=session.episode_id),
                ca_bundle=external.ca_bundle,
                timeout=timeout_seconds,
            )
        )
        try:
            await _wait(sending, session, external.url, deadline)
        finally:
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
            await self.server.revoke(session.episode_id)
        if outcome["terminated"]:
            stop_reason = "environment_terminated"
        elif outcome["truncated"]:
            stop_reason = "environment_truncated"
        else:
            stop_reason = "agent_finished"
        result = {
            "response": session.finished.result(),
            "trace_id": session.episode_id,
            "stop_reason": stop_reason,
            "turns": session.turns,
            "agent_kind": "external",
            "trace": "self_reported" if session.trace is not None else "none",
            **outcome,
        }
        artifacts = [
            DownloadedFile(
                path="result.json", data=(json.dumps(result, sort_keys=True) + "\n").encode()
            )
        ]
        if session.trace is not None:
            artifacts.append(DownloadedFile(path=AGENT_TRACE_FILE, data=session.trace))
        execution = HarnessExecution(
            status="succeeded",
            events=(),
            output_paths=("result.json",),
            artifact_paths=tuple(item.path for item in artifacts[1:]),
            stdout=b"",
            stderr=b"",
            duration_seconds=time.monotonic() - started,
            trace_id=session.episode_id,
        )
        return ExternalRun(
            execution=execution,
            artifacts=tuple(artifacts),
            actions=tuple(declared),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )


async def _wait(
    sending: asyncio.Task[tuple[int, bytes]],
    session: EpisodeSession,
    url: str,
    deadline: float,
) -> None:
    """Wait for the agent to finish, or for its reply to the start to fail or answer."""
    host = urlsplit(url).hostname
    finished = session.finished
    done, _ = await asyncio.wait(
        {sending, finished},
        timeout=max(0.0, deadline - time.time()),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if sending in done and not finished.done():
        try:
            status, reply = sending.result()
        except httpx.HTTPError as exc:
            raise HarnessExecutionError(
                f"Could not reach the external Agent at {host}: {type(exc).__name__}"
            ) from None
        if not 200 <= status < 300:
            raise HarnessExecutionError(
                f"The external Agent at {host} refused the episode with HTTP {status}."
            )
        answer = _answer(reply)
        if answer is not None:
            session.finish(answer[0])
        else:
            await asyncio.wait({finished}, timeout=max(0.0, deadline - time.time()))
    if not finished.done():
        raise TimeoutError("The external Agent did not finish within max_seconds")


async def _post(
    url: str, body: bytes, *, headers: Mapping[str, str], ca_bundle: str | None, timeout: float
) -> tuple[int, bytes]:
    verify: ssl.SSLContext | bool = (
        ssl.create_default_context(cafile=ca_bundle) if ca_bundle is not None else True
    )
    async with (
        httpx.AsyncClient(
            verify=verify,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout, connect=10.0),
        ) as client,
        client.stream(
            "POST",
            url,
            content=body,
            headers={**headers, "Content-Type": "application/json"},
        ) as response,
    ):
        reply = bytearray()
        async for chunk in response.aiter_bytes():
            reply.extend(chunk)
            if len(reply) > MAX_START_REPLY_BYTES:
                break
        return response.status_code, bytes(reply[:MAX_START_REPLY_BYTES])


def _answer(reply: bytes) -> tuple[Any] | None:
    """The final answer a synchronous agent returned with its reply, if any."""
    try:
        payload = json.loads(reply) if reply else None
    except ValueError:
        return None
    if isinstance(payload, dict) and "response" in payload:
        return (payload["response"],)
    return None


def _transition(stdout: bytes) -> dict[str, Any]:
    text = stdout.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(text) if text else {}
    except json.JSONDecodeError:
        parsed = {"observation": {"output": text}}
    if not (isinstance(parsed, dict) and parsed.get("protocol") == STEP_PROTOCOL):
        parsed = {"observation": parsed}
    terminated = bool(parsed.get("terminated"))
    truncated = bool(parsed.get("truncated"))
    return {
        "observation": parsed.get("observation"),
        "done": terminated or truncated,
        "terminated": terminated,
        "truncated": truncated,
    }


__all__ = ["AGENT_TRACE_FILE", "ExternalAgentRunner", "ExternalRun"]
