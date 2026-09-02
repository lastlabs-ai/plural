"""Classified exception hierarchy for plural.

Provider adapters map HTTP status codes and provider-specific error payloads
into these types so routers can make retry and fallback decisions without
parsing raw response bodies.

Examples:
    >>> from plural.errors import RateLimitError, is_retryable
    >>> err = RateLimitError("too many requests", provider="openai", status_code=429)
    >>> is_retryable(err)
    True
"""

from __future__ import annotations

from typing import Any


class PluralError(Exception):
    """Base class for all plural errors.

    Args:
        message: Human-readable description of the failure.
        provider: Provider slug associated with the failure, if any.
        status_code: HTTP status code, if the failure came from an HTTP response.
        body: Raw response body or structured error payload, if available.
        model: Model id that was being called, if known.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        body: Any = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.body = body
        self.model = model

    def __str__(self) -> str:  # noqa: D105
        parts = [self.message]
        if self.provider:
            parts.append(f"provider={self.provider}")
        if self.model:
            parts.append(f"model={self.model}")
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        return " | ".join(parts)


class AuthenticationError(PluralError):
    """Raised when credentials are missing or rejected (typically HTTP 401/403)."""


class RateLimitError(PluralError):
    """Raised when a provider rate-limits the request (typically HTTP 429)."""


class ContextLengthError(PluralError):
    """Raised when the request exceeds the model's context window."""


class ContentFilterError(PluralError):
    """Raised when a provider refuses the request due to a content filter."""


class ProviderUnavailable(PluralError):
    """Raised when a provider is down or returns a transient 5xx error."""


class InvalidRequestError(PluralError):
    """Raised when the request is malformed or uses unsupported parameters."""


class TimeoutError(PluralError):
    """Raised when a provider call exceeds the configured timeout."""


class BudgetExceededError(PluralError):
    """Raised when a request would exceed a configured cost or token budget."""


class ConfigurationError(PluralError):
    """Raised when plural is misconfigured (missing keys, unknown models, etc.)."""


class NotFoundError(PluralError):
    """Raised when a requested resource (model, trace, dataset) cannot be found."""


class ConflictError(PluralError):
    """Raised when a unique slug or name already exists (typically HTTP 409)."""


RETRYABLE_ERRORS: tuple[type[PluralError], ...] = (
    RateLimitError,
    ProviderUnavailable,
    TimeoutError,
)


def is_retryable(error: BaseException) -> bool:
    """Return whether ``error`` should be retried by the router.

    Args:
        error: The exception raised by a provider call.

    Returns:
        ``True`` if the error is a known retryable plural error.

    Examples:
        >>> is_retryable(TimeoutError("timed out"))
        True
        >>> is_retryable(AuthenticationError("bad key"))
        False
    """
    return isinstance(error, RETRYABLE_ERRORS)
