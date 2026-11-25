"""Runtime configuration for plural clients and sinks.

Examples:
    >>> from plural.config import Settings
    >>> s = Settings()
    >>> s.gateway_base_url
    'https://api.pluralintel.com/v1'
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

_LOCAL_NAMES = {"localhost", "host.docker.internal", "gateway.docker.internal"}


class Settings(BaseModel):
    """Process-wide defaults for plural.

    Attributes:
        gateway_base_url: Base URL of the hosted plural gateway. Used when
            constructing a client with a single ``api_key``.
        default_timeout_s: Default HTTP timeout for provider calls, in seconds.
        max_retries: Default number of retries for retryable provider errors.
        trace_dir: Default directory for local JSONL/SQLite sinks.
        capture_content: Whether to record full prompt/response content in traces.
            Disabled by default to reduce PII exposure risk.
    """

    gateway_base_url: str = "https://api.pluralintel.com/v1"
    default_timeout_s: float = 60.0
    max_retries: int = 2
    trace_dir: Path = Field(default_factory=lambda: Path(".plural"))
    capture_content: bool = False


DEFAULT_SETTINGS = Settings()


def resolve_gateway_url(
    explicit: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve the hosted gateway URL.

    Prefer an explicit constructor value, then ``PLURAL_GATEWAY_URL``, then
    ``PLURAL_API_URL``, then the production default. The gateway is served under
    ``/v1`` of the API, so it is added to ``PLURAL_API_URL`` when missing.

    Returns:
        The gateway base URL without a trailing slash.
    """
    env = os.environ if environ is None else environ
    gateway = explicit or env.get("PLURAL_GATEWAY_URL")
    if gateway:
        return gateway.rstrip("/")
    api = (env.get("PLURAL_API_URL") or "").rstrip("/")
    if api:
        return api if api.endswith("/v1") else f"{api}/v1"
    return DEFAULT_SETTINGS.gateway_base_url.rstrip("/")


def is_local_url(url: str) -> bool:
    """Whether a URL names this machine or a private network, or no host at all.

    Returns:
        True for loopback, private and link-local addresses and local host names.

    Examples:
        >>> is_local_url("http://localhost:8005/v1"), is_local_url("https://api.pluralintel.com")
        (True, False)
    """
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return True
    if host in _LOCAL_NAMES or host.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False
