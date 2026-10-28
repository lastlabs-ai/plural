"""Provider-neutral token usage for one model call.

``input_tokens`` counts every prompt token the provider billed or served,
including cached ones. ``cached_input_tokens`` is the part of ``input_tokens``
served from a prompt cache, never an addition to it. Providers that report
cache reads separately from input, such as Anthropic, are folded into this
shape so that totals are never double-counted.
"""

from __future__ import annotations

import ipaddress
import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from plural.common import FrozenModel


class TokenUsage(FrozenModel):
    """Token counts and cost for one model call, each ``None`` when unreported."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None

    @property
    def reported(self) -> bool:
        """Whether the provider reported any usage at all."""
        return any(
            value is not None for value in (self.input_tokens, self.output_tokens, self.cost_usd)
        )


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value)


def _cost(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def normalize_usage(raw: Mapping[str, Any] | None, *, cost: Any = None) -> TokenUsage:
    """Read OpenAI-compatible or Anthropic usage into :class:`TokenUsage`.

    Args:
        raw: The ``usage`` object from a provider response.
        cost: A response-level cost, when the gateway reports one outside ``usage``.

    Returns:
        The normalized usage. Unreported counts stay ``None``, never zero.
    """
    usage = dict(raw or {})
    output = _count(usage.get("completion_tokens"))
    if output is None:
        output = _count(usage.get("output_tokens"))
    reasoning = None
    completion_details = usage.get("completion_tokens_details")
    if isinstance(completion_details, Mapping):
        reasoning = _count(completion_details.get("reasoning_tokens"))
    if "prompt_tokens" in usage:
        prompt = _count(usage.get("prompt_tokens"))
        cached = None
        details = usage.get("prompt_tokens_details")
        if isinstance(details, Mapping):
            cached = _count(details.get("cached_tokens"))
    else:
        base = _count(usage.get("input_tokens"))
        read = _count(usage.get("cache_read_input_tokens"))
        written = _count(usage.get("cache_creation_input_tokens"))
        prompt = None if base is None else base + (read or 0) + (written or 0)
        cached = read
    if cached is not None and prompt is not None:
        cached = min(cached, prompt)
    reported_cost = _cost(usage.get("cost"))
    if reported_cost is None:
        reported_cost = _cost(usage.get("cost_usd"))
    if reported_cost is None:
        reported_cost = _cost(cost)
    return TokenUsage(
        input_tokens=prompt,
        output_tokens=output,
        cached_input_tokens=cached,
        reasoning_tokens=reasoning,
        cost_usd=reported_cost,
    )


class UsageTotals(FrozenModel):
    """Summed usage across calls, with how many calls left each field unreported."""

    calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cost_usd: float | None = None
    calls_missing_tokens: int = 0
    calls_missing_cost: int = 0

    @property
    def complete(self) -> bool:
        """Whether every call reported both tokens and cost."""
        return self.calls_missing_tokens == 0 and self.calls_missing_cost == 0

    def add(self, usage: TokenUsage) -> UsageTotals:
        """Return these totals with one more call counted."""

        def plus(total: int | None, value: int | None) -> int | None:
            if value is None:
                return total
            return (total or 0) + value

        return UsageTotals(
            calls=self.calls + 1,
            input_tokens=plus(self.input_tokens, usage.input_tokens),
            output_tokens=plus(self.output_tokens, usage.output_tokens),
            cached_input_tokens=plus(self.cached_input_tokens, usage.cached_input_tokens),
            cost_usd=(
                self.cost_usd if usage.cost_usd is None else (self.cost_usd or 0.0) + usage.cost_usd
            ),
            calls_missing_tokens=self.calls_missing_tokens
            + (usage.input_tokens is None or usage.output_tokens is None),
            calls_missing_cost=self.calls_missing_cost + (usage.cost_usd is None),
        )


def on_own_hardware(endpoint: str) -> bool:
    """Whether ``endpoint`` is on this machine or a private network, so its calls cost nothing.

    Returns:
        ``True`` for a loopback, private, or link-local address, ``localhost``,
        a ``.local`` name, or Docker's ``host.docker.internal``.
    """
    host = (urlsplit(endpoint).hostname or "").lower()
    if host in {"localhost", "host.docker.internal"} or host.endswith((".localhost", ".local")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_loopback or address.is_private or address.is_link_local or address.is_unspecified
    )


def price_own_hardware(response: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Price a call to a model on the user's own hardware at zero, unless it reports a cost.

    Returns:
        ``response``, with ``usage.cost`` set to 0 when Plural adds it.
    """
    if not endpoint or not on_own_hardware(endpoint):
        return response
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = response["usage"] = {}
    if response.get("cost") is None and usage.get("cost") is None and usage.get("cost_usd") is None:
        usage["cost"] = 0.0
    return response


__all__ = [
    "TokenUsage",
    "UsageTotals",
    "normalize_usage",
    "on_own_hardware",
    "price_own_hardware",
]
