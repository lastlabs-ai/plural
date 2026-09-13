"""Runtime configuration for plural clients and sinks.

Examples:
    >>> from plural.config import Settings
    >>> s = Settings()
    >>> s.gateway_base_url
    'https://api.pluralintel.com/v1'
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, Field


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
    ``PLURAL_API_URL``, then the production default.

    Returns:
        The gateway base URL without a trailing slash.
    """
    env = os.environ if environ is None else environ
    raw = (
        explicit
        or env.get("PLURAL_GATEWAY_URL")
        or env.get("PLURAL_API_URL")
        or DEFAULT_SETTINGS.gateway_base_url
    )
    return raw.rstrip("/")
