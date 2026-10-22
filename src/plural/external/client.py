"""The agent's side of an episode: verify the start request, act, and finish."""

from __future__ import annotations

import json
import os
import ssl
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from plural.external.protocol import (
    EpisodeAction,
    EpisodeStart,
    EpisodeTask,
    SignatureError,
    signing_key,
    verify,
)
from plural.external.protocol import _Model as Model

KEY_VARIABLE = "PLURAL_SIGNING_KEY"


class Ping(Model):
    """A signed check, from ``plural agent test``, that the agent is reachable."""

    protocol: Literal["plural-episode-v1"] = "plural-episode-v1"
    type: Literal["ping"] = "ping"


def verify_request(
    body: bytes, headers: Mapping[str, str], *, key: str | None = None
) -> EpisodeStart | Ping:
    """Check that a request came from your Plural Job, and parse it.

    Args:
        body: The request's raw bytes, before any JSON parsing.
        headers: Its headers.
        key: The shared signing key. Defaults to ``PLURAL_SIGNING_KEY``.

    Returns:
        The episode to start, or a ping to answer with any 2xx.

    Raises:
        SignatureError: When the request is not signed with the key, is more
            than five minutes old, was received before, or is not one Plural sends.
    """
    secret = key if key is not None else os.environ.get(KEY_VARIABLE, "")
    if not secret:
        raise SignatureError(f"Set {KEY_VARIABLE} to the Agent's signing key")
    verify(signing_key(secret), body, headers)
    try:
        payload = json.loads(body)
        if isinstance(payload, dict) and payload.get("type") == "ping":
            return Ping.model_validate(payload)
        return EpisodeStart.model_validate(payload)
    except (ValueError, ValidationError):
        raise SignatureError("The signed request is not a plural-episode-v1 message") from None


class EpisodeError(RuntimeError):
    """The Job refused a request, such as an action after the episode ended."""


class Episode:
    """One episode, as the agent works it.

    Every call goes to the Job that started it, with the episode's own token.
    Pass ``verify`` (a CA bundle path, or ``False`` for a self-signed test
    certificate) when the Job serves HTTPS with a private certificate.
    """

    def __init__(
        self,
        start: EpisodeStart,
        *,
        verify: str | bool = True,
        timeout: float = 120.0,
    ) -> None:
        self.start = start
        self.observation: Any = start.observation
        self.done = False
        context: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=verify) if isinstance(verify, str) else verify
        )
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {start.token}"},
            follow_redirects=False,
            verify=context,
            timeout=timeout,
        )

    @property
    def task(self) -> EpisodeTask:
        """The Task's name, instructions, goals, and info."""
        return self.start.task

    @property
    def actions(self) -> tuple[EpisodeAction, ...]:
        """The actions the agent may take."""
        return self.start.actions

    @property
    def files(self) -> tuple[str, ...]:
        """The paths of the files the agent may read."""
        return self.start.files

    def tools(self) -> list[dict[str, Any]]:
        """Describe the actions for a model.

        Returns:
            The actions as OpenAI-compatible tools.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": item.name,
                    "description": item.description or item.name,
                    "parameters": item.parameters or {"type": "object"},
                },
            }
            for item in self.actions
        ]

    def act(self, action: str, /, **arguments: Any) -> Any:
        """Take one action.

        Returns:
            Its observation.
        """
        reply = self._post(f"{self.start.urls.actions}/{quote(action, safe='')}", arguments)
        self.observation = reply.get("observation")
        self.done = bool(reply.get("done"))
        return self.observation

    def read(self, path: str) -> bytes:
        """Read one of :attr:`files`.

        Returns:
            Its bytes.
        """
        response = self._client.get(f"{self.start.urls.files}/{quote(path)}")
        _raise_for(response)
        return response.content

    def trace(self, trajectory: Mapping[str, Any]) -> None:
        """Report the agent's own trace, as an ATIF document.

        The Trial keeps it as self-reported, next to the actions the Job saw.
        """
        self._post(self.start.urls.trace, dict(trajectory))

    def finish(self, response: Any) -> None:
        """End the episode with the agent's final answer. It can be sent once."""
        self._post(self.start.urls.finish, {"response": response})
        self.done = True
        self._client.close()

    def _post(self, url: str, payload: Any) -> dict[str, Any]:
        response = self._client.post(url, json=payload)
        _raise_for(response)
        body = response.json() if response.content else {}
        return body if isinstance(body, dict) else {}


def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        detail = response.json().get("error")
    except (ValueError, AttributeError):
        detail = None
    raise EpisodeError(f"{response.status_code}: {detail or response.reason_phrase}")


__all__ = ["KEY_VARIABLE", "Episode", "EpisodeError", "Ping", "verify_request"]
