"""The ``plural-episode-v1`` wire protocol between a Job and an External Agent.

The Job signs every request it sends the agent with Standard Webhooks
headers. The agent answers through the episode's own URLs, with the bearer
token the start request carries.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL = "plural-episode-v1"
SIGNATURE_TOLERANCE_SECONDS = 300
"""How old, or how far in the future, a signed request may be."""
MIN_KEY_BYTES = 32
KEY_PREFIX = "whsec_"


class SignatureError(ValueError):
    """A request whose signature, timestamp, or id does not check out."""


def is_loopback(host: str | None) -> bool:
    """Whether ``host`` names this machine only.

    Returns:
        True for ``localhost`` and loopback addresses.
    """
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def check_agent_url(url: str) -> str:
    """Refuse a URL a signed request should not go to.

    Returns:
        ``url`` unchanged.

    Raises:
        ValueError: Unless it is ``https``, or ``http`` on loopback, with a host
            and no user name or password.
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"{url!r} must be an https URL, such as https://agent.example.com/plural")
    if parts.username is not None or parts.password is not None:
        raise ValueError("The URL may not carry a user name or password")
    if parts.fragment:
        raise ValueError("The URL may not have a #fragment")
    if parts.scheme == "http" and not is_loopback(parts.hostname):
        raise ValueError(
            f"{url!r} uses http, which only a loopback address such as 127.0.0.1 may. Use https."
        )
    return url


def signing_key(value: str) -> bytes:
    """The key bytes of a ``whsec_``-prefixed base64 secret, or of a raw one.

    Returns:
        The bytes to sign with.

    Raises:
        ValueError: When the key is shorter than 32 bytes.
    """
    if value.startswith(KEY_PREFIX):
        try:
            key = base64.b64decode(value.removeprefix(KEY_PREFIX), validate=True)
        except ValueError:
            raise ValueError("The signing key is not valid base64 after whsec_") from None
    else:
        key = value.encode()
    if len(key) < MIN_KEY_BYTES:
        raise ValueError(
            f"The signing key must be at least {MIN_KEY_BYTES} bytes. Make one with "
            "`plural agent key`."
        )
    return key


def new_signing_key() -> str:
    """Make a fresh signing key.

    Returns:
        32 random bytes, as ``whsec_`` and base64.
    """
    import secrets

    return KEY_PREFIX + base64.b64encode(secrets.token_bytes(MIN_KEY_BYTES)).decode()


def _signature(key: bytes, message_id: str, timestamp: str, body: bytes) -> str:
    content = f"{message_id}.{timestamp}.".encode() + body
    digest = hmac.new(key, content, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def sign(
    key: bytes, body: bytes, *, message_id: str, timestamp: int | None = None
) -> dict[str, str]:
    """Standard Webhooks headers for ``body``.

    Returns:
        ``webhook-id``, ``webhook-timestamp``, and ``webhook-signature``.
    """
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    return {
        "webhook-id": message_id,
        "webhook-timestamp": stamp,
        "webhook-signature": _signature(key, message_id, stamp, body),
    }


class _Seen:
    """Message ids verified within the tolerance, so none is accepted twice."""

    def __init__(self, limit: int = 10_000) -> None:
        self.limit = limit
        self._ids: OrderedDict[str, float] = OrderedDict()

    def add(self, message_id: str, now: float) -> bool:
        while self._ids and next(iter(self._ids.values())) < now - 2 * SIGNATURE_TOLERANCE_SECONDS:
            self._ids.popitem(last=False)
        if message_id in self._ids:
            return False
        self._ids[message_id] = now
        if len(self._ids) > self.limit:
            self._ids.popitem(last=False)
        return True


_SEEN = _Seen()


def verify(
    key: bytes,
    body: bytes,
    headers: Mapping[str, str],
    *,
    now: float | None = None,
    seen: _Seen | None = _SEEN,
) -> str:
    """Check a signed request and remember its id.

    Returns:
        The request's ``webhook-id``.

    Raises:
        SignatureError: When a header is missing, the timestamp is more than
            five minutes off, the id was already seen, or no signature matches.
    """
    lowered = {name.lower(): value for name, value in headers.items()}
    message_id = lowered.get("webhook-id") or ""
    stamp = lowered.get("webhook-timestamp") or ""
    signatures = lowered.get("webhook-signature") or ""
    if not message_id or not stamp.isdigit() or not signatures:
        raise SignatureError("The request is missing its webhook signature headers")
    current = time.time() if now is None else now
    if abs(current - int(stamp)) > SIGNATURE_TOLERANCE_SECONDS:
        raise SignatureError("The request's timestamp is more than five minutes off")
    expected = _signature(key, message_id, stamp, body)
    if not any(hmac.compare_digest(expected, item) for item in signatures.split()):
        raise SignatureError("The request's signature does not match")
    if seen is not None and not seen.add(message_id, current):
        raise SignatureError("The request was already received once")
    return message_id


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class EpisodeTask(_Model):
    """What the agent is asked to do."""

    name: str = ""
    instructions: str = ""
    goals: tuple[str, ...] = ()
    info: dict[str, Any] = Field(default_factory=dict)


class EpisodeAction(_Model):
    """One action the agent may take, as a tool."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class EpisodeURLs(_Model):
    """Where the agent acts, reads files, reports its trace, and finishes."""

    mcp: str
    actions: str
    files: str
    trace: str
    finish: str


class EpisodeGateway(_Model):
    """A model gateway key that is valid for this episode only."""

    url: str
    key: str


class EpisodeStart(_Model):
    """The signed request that starts one episode."""

    protocol: Literal["plural-episode-v1"] = "plural-episode-v1"
    type: Literal["episode.start"] = "episode.start"
    episode_id: str
    task: EpisodeTask
    agent: dict[str, str] = Field(default_factory=dict)
    observation: Any = None
    actions: tuple[EpisodeAction, ...] = ()
    files: tuple[str, ...] = ()
    urls: EpisodeURLs
    token: str
    deadline: str
    max_turns: int
    gateway: EpisodeGateway | None = None


__all__ = [
    "PROTOCOL",
    "SIGNATURE_TOLERANCE_SECONDS",
    "EpisodeAction",
    "EpisodeGateway",
    "EpisodeStart",
    "EpisodeTask",
    "EpisodeURLs",
    "SignatureError",
    "check_agent_url",
    "is_loopback",
    "new_signing_key",
    "sign",
    "signing_key",
    "verify",
]
