"""What one model call costs, including prompt caching.

This is the one place that turns token counts and per-token rates into money,
so the SDK's cost estimate and the hosted gateway's bill cannot disagree.

The rules err toward charging at least what the host charges:

* A cache read with no declared cache price bills at the full prompt rate.
* A cache write with no declared price bills at
  :data:`UNDECLARED_CACHE_WRITE_MULTIPLIER` times the prompt rate, the highest
  premium any host charges for a short-lived write.
* A long-lived write (Anthropic's one-hour TTL) bills at
  :data:`LONG_CACHE_WRITE_MULTIPLIER` times the prompt rate, or the declared
  write rate if that is higher.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

UNDECLARED_CACHE_WRITE_MULTIPLIER = Decimal("1.25")
LONG_CACHE_WRITE_MULTIPLIER = Decimal("2")
_ZERO = Decimal(0)


def _decimal(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class PriceRates:
    """USD per token for one call, after any long-context tier is applied.

    Attributes:
        prompt: Rate for prompt tokens not served from or written to a cache.
        completion: Rate for completion tokens, including reasoning.
        cache_read: Rate for prompt tokens read from the cache, when declared.
        cache_write: Rate for prompt tokens written to the cache, when declared.
    """

    prompt: Decimal
    completion: Decimal
    cache_read: Decimal | None = None
    cache_write: Decimal | None = None

    @classmethod
    def of(
        cls,
        prompt: float | Decimal | None,
        completion: float | Decimal | None,
        cache_read: float | Decimal | None = None,
        cache_write: float | Decimal | None = None,
    ) -> PriceRates:
        """Build rates from floats or decimals; a missing prompt or completion rate is zero.

        Args:
            prompt: USD per prompt token.
            completion: USD per completion token.
            cache_read: USD per cached prompt token read, if the host prices it.
            cache_write: USD per prompt token written to the cache, if priced.

        Returns:
            Rates as decimals.
        """
        return cls(
            prompt=_decimal(prompt) or _ZERO,
            completion=_decimal(completion) or _ZERO,
            cache_read=_decimal(cache_read),
            cache_write=_decimal(cache_write),
        )

    def scaled(self, factor: Decimal) -> PriceRates:
        """Every rate multiplied by ``factor``, for a discount.

        Args:
            factor: Multiplier, such as ``Decimal("0.8")`` for 20% off.

        Returns:
            The scaled rates; undeclared cache rates stay undeclared.
        """
        return PriceRates(
            prompt=self.prompt * factor,
            completion=self.completion * factor,
            cache_read=None if self.cache_read is None else self.cache_read * factor,
            cache_write=None if self.cache_write is None else self.cache_write * factor,
        )

    @property
    def effective_cache_read(self) -> Decimal:
        """The rate a cache read bills at."""
        return self.prompt if self.cache_read is None else self.cache_read

    @property
    def effective_cache_write(self) -> Decimal:
        """The rate a short-lived cache write bills at."""
        if self.cache_write is None:
            return self.prompt * UNDECLARED_CACHE_WRITE_MULTIPLIER
        return self.cache_write

    @property
    def effective_long_cache_write(self) -> Decimal:
        """The rate a long-lived cache write bills at."""
        return max(self.effective_cache_write, self.prompt * LONG_CACHE_WRITE_MULTIPLIER)


@dataclass(frozen=True)
class Charge:
    """A call's cost, split by what the tokens were.

    Attributes:
        prompt_usd: Prompt tokens neither read from nor written to a cache.
        cache_read_usd: Prompt tokens read from the cache.
        cache_write_usd: Prompt tokens written to the cache.
        completion_usd: Completion tokens.
    """

    prompt_usd: Decimal
    cache_read_usd: Decimal
    cache_write_usd: Decimal
    completion_usd: Decimal

    @property
    def input_usd(self) -> Decimal:
        """Everything billed for the prompt, cached or not."""
        return self.prompt_usd + self.cache_read_usd + self.cache_write_usd

    @property
    def total_usd(self) -> Decimal:
        """The whole call."""
        return self.input_usd + self.completion_usd


def charge(
    rates: PriceRates,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_write_long_tokens: int = 0,
) -> Charge:
    """Price one call.

    ``prompt_tokens`` counts every prompt token, cached or not; the cache counts
    are subsets of it, as :class:`plural.types.Usage` reports them.

    Args:
        rates: Per-token rates for the call.
        prompt_tokens: All prompt tokens.
        completion_tokens: All completion tokens.
        cache_read_tokens: Prompt tokens read from the cache.
        cache_write_tokens: Prompt tokens written to the cache.
        cache_write_long_tokens: How many of the writes used a long-lived TTL.

    Returns:
        The cost, split by token kind.

    Examples:
        >>> from decimal import Decimal
        >>> rates = PriceRates.of(3e-06, 1.5e-05, cache_read=3e-07, cache_write=3.75e-06)
        >>> bill = charge(
        ...     rates,
        ...     prompt_tokens=10_000,
        ...     completion_tokens=1_000,
        ...     cache_read_tokens=8_000,
        ...     cache_write_tokens=1_000,
        ... )
        >>> bill.total_usd.normalize()
        Decimal('0.02415')
    """
    prompt_tokens = max(prompt_tokens, 0)
    read = min(max(cache_read_tokens, 0), prompt_tokens)
    write = min(max(cache_write_tokens, 0), prompt_tokens - read)
    long_write = min(max(cache_write_long_tokens, 0), write)
    uncached = prompt_tokens - read - write
    return Charge(
        prompt_usd=rates.prompt * uncached,
        cache_read_usd=rates.effective_cache_read * read,
        cache_write_usd=(
            rates.effective_cache_write * (write - long_write)
            + rates.effective_long_cache_write * long_write
        ),
        completion_usd=rates.completion * max(completion_tokens, 0),
    )


def charge_usage(rates: PriceRates, usage: Any) -> Charge:
    """Price a :class:`plural.types.Usage`, or any object with the same fields.

    Args:
        rates: Per-token rates for the call.
        usage: Token usage.

    Returns:
        The cost, split by token kind.
    """
    return charge(
        rates,
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_tokens", 0) or 0),
        cache_write_tokens=int(getattr(usage, "cache_write_tokens", 0) or 0),
        cache_write_long_tokens=int(getattr(usage, "cache_write_long_tokens", 0) or 0),
    )
