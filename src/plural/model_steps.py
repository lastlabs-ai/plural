"""Plural's own model-backed steps: drafting a Scorecard, generating Tasks.

Each step calls models through the Plural gateway with a key minted for that
step alone. The key calls chat completions only, expires within minutes, and
is revoked when the step ends. The user's long-lived ``PLURAL_API_KEY`` only
asks for it, and never makes a model call itself. Before each call the step
estimates the cost from the catalog's prices and refuses to go past its budget.

Examples:
    >>> estimate_usd("openai/gpt-5.6-luna", prompt_tokens=10_000, completion_tokens=1_000)
    0.0032
    >>> approx_tokens("x" * 400)
    100
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from plural.catalog import ModelCatalog
from plural.errors import NotFoundError, PluralError

DEFAULT_MODEL = "openai/gpt-5.6-luna"
"""The model Plural's own steps use unless told otherwise: cheap, with a long context."""
STEP_KEY_TTL_SECONDS = 900
"""A step key's lifetime. It is revoked as soon as the step ends, whichever comes first."""
CHARS_PER_TOKEN = 4


class ChatClient(Protocol):
    """What a step needs from a gateway client: :class:`plural.Client` fits."""

    def chat(self, *, model: str, messages: Any, **kwargs: Any) -> Any:
        """Create one chat completion."""


class BudgetExceeded(PluralError):
    """A model-backed step would spend more than its budget."""


def approx_tokens(text: str) -> int:
    """A rough token count for text, at four characters a token.

    Returns:
        The estimate.
    """
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_usd(
    model: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    catalog: ModelCatalog | None = None,
) -> float | None:
    """The catalog price of one call.

    Returns:
        USD, rounded to a hundredth of a cent, or ``None`` for a model the
        catalog does not price.
    """
    spec = (catalog or ModelCatalog()).get(model)
    pricing = spec.pricing if spec is not None else None
    if pricing is None:
        return None
    prompt, completion = pricing.prompt, pricing.completion
    for tier in sorted(pricing.tiers, key=lambda item: item.min_prompt_tokens):
        if prompt_tokens >= tier.min_prompt_tokens:
            prompt, completion = tier.prompt, tier.completion
    return round(prompt * prompt_tokens + completion * completion_tokens, 4)


@dataclass
class ModelStep:
    """One model-backed step's calls, budget, and spend.

    Use :func:`model_step` to get one with a scoped gateway key. ``spent_usd``
    counts the gateway's reported cost where it gives one, and the catalog
    price otherwise.
    """

    purpose: str
    model: str
    budget_usd: float
    client: ChatClient
    catalog: ModelCatalog = field(default_factory=ModelCatalog)
    spent_usd: float = 0.0
    calls: int = 0

    def estimate(self, prompt: str, completion_tokens: int) -> float:
        """The catalog price of one call with this prompt; zero for an unpriced model.

        Returns:
            USD.
        """
        price = estimate_usd(
            self.model,
            prompt_tokens=approx_tokens(prompt),
            completion_tokens=completion_tokens,
            catalog=self.catalog,
        )
        return price or 0.0

    def json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: Mapping[str, Any],
        max_tokens: int = 8_000,
    ) -> dict[str, Any]:
        """Ask the model for one JSON object matching ``schema``.

        Returns:
            The parsed object.

        Raises:
            BudgetExceeded: When the call could go past the budget.
            PluralError: When the model does not return valid JSON.
        """
        expected = self.estimate(system + user, max_tokens)
        if self.spent_usd + expected > self.budget_usd:
            raise BudgetExceeded(
                f"{self.purpose}: the next call could cost ${expected:.4f}, and "
                f"${self.spent_usd:.4f} of the ${self.budget_usd:.2f} budget is spent.\n"
                "Next: pass a larger --budget-usd, or fewer documents and traces."
            )
        response = self.client.chat(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": dict(schema)},
            },
            write_trace=False,
        )
        self.calls += 1
        usage = getattr(response, "usage", None)
        cost = getattr(usage, "cost", None)
        if cost is None and usage is not None:
            cost = estimate_usd(
                self.model,
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                catalog=self.catalog,
            )
        self.spent_usd += float(cost or 0.0)
        text = _content(response)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PluralError(
                f"{self.purpose}: the model did not return JSON ({exc}).\n"
                "Next: run it again, or pick another model with --model."
            ) from exc
        if not isinstance(value, dict):
            raise PluralError(
                f"{self.purpose}: the model returned {type(value).__name__}, not an object.\n"
                "Next: run it again, or pick another model with --model."
            )
        return value


def _content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, list):
        return "".join(str(getattr(part, "text", "") or "") for part in content)
    return str(content or "")


@contextmanager
def model_step(
    purpose: str,
    *,
    model: str = DEFAULT_MODEL,
    budget_usd: float,
    studio: Any = None,
    gateway_url: str | None = None,
    client: ChatClient | None = None,
    catalog: ModelCatalog | None = None,
) -> Iterator[ModelStep]:
    """A model-backed step with its own short-lived gateway key, revoked when it ends.

    Pass ``client`` to call models some other way, such as a scripted client
    in a test; then no key is minted.

    Args:
        purpose: What the step is for, recorded on the key, such as ``scorecard-draft``.
        model: The catalog model to call.
        budget_usd: The most the step may spend.
        studio: The hosted API, which mints and revokes the key.
        gateway_url: The gateway the key calls.
        client: A ready client, instead of a minted key.
        catalog: The model catalog, for prices.

    Yields:
        The step.

    Raises:
        PluralError: When the hosted project cannot mint a step key.
    """
    catalog = catalog or ModelCatalog()
    if catalog.get(model) is None:
        raise PluralError(
            f"{purpose}: {model} is not in the model catalog.\n"
            "Next: plural model list shows the models; pass one with --model."
        )
    if client is not None:
        yield ModelStep(purpose, model, budget_usd, client, catalog)
        return
    if studio is None:
        raise PluralError(
            f"{purpose} calls a model through the Plural gateway, and needs a hosted project.\n"
            "Next: plural auth login, then plural project init --push."
        )
    from plural.client import Client

    try:
        minted = studio.request(
            "POST",
            "/step-keys",
            json={"purpose": purpose, "ttl_seconds": STEP_KEY_TTL_SECONDS},
        )
    except NotFoundError as exc:
        raise PluralError(
            f"{purpose} needs a step key, and this Plural service cannot mint one.\n"
            "Next: update the service, or ask its operator to."
        ) from exc
    key_id = str(minted["id"])
    try:
        gateway = Client(
            api_key=str(minted["key"]),
            base_url=gateway_url,
            catalog=catalog,
            capture_content=False,
            project=getattr(studio, "project", None),
        )
        yield ModelStep(purpose, model, budget_usd, gateway, catalog)
    finally:
        studio.request("POST", f"/step-keys/{key_id}/revoke")


__all__ = [
    "DEFAULT_MODEL",
    "STEP_KEY_TTL_SECONDS",
    "BudgetExceeded",
    "ChatClient",
    "ModelStep",
    "approx_tokens",
    "estimate_usd",
    "model_step",
]
