r"""Maintain the bundled model catalog: the data behind every model card.

``models.json`` is the single source for what a model card shows and what the
gateway routes and bills: the model's description, release date, context
window, modalities, parameters, and every host that serves it at that host's
price. This tool edits it without hand-writing JSON, validates the whole
document before every write, and speaks JSON so a coding agent can drive it.

Every command prints JSON on stdout. A failed command prints
``{"ok": false, "errors": [...]}`` and exits ``1``; nothing is written unless
the document still validates.

Prices are USD per token. Any price may instead be written per million tokens
with an ``/M`` suffix, so ``3/M`` stores ``0.000003``. Cached prompt tokens bill
at ``cache_read`` and cache writes at ``cache_write``; an undeclared read bills
at the prompt rate and an undeclared write at 1.25 times it, so a missing price
never undercharges. ``cache-prices`` fills both from OpenRouter's per-host data.

Run it with::

    python -m plural.catalog.edit schema
    python -m plural.catalog.edit list
    python -m plural.catalog.edit show openai/gpt-5.6-luna
    python -m plural.catalog.edit add --file card.json
    python -m plural.catalog.edit add acme/new-model --from-openrouter
    python -m plural.catalog.edit enrich acme/new-model --as acme-ai/new-model
    python -m plural.catalog.edit cache-prices acme/new-model
    python -m plural.catalog.edit set acme/new-model description="..." pricing.prompt=3/M
    python -m plural.catalog.edit endpoint add acme/new-model --provider fireworks \
        --upstream-id accounts/fireworks/models/new-model --prompt 0.9/M --completion 0.9/M
    python -m plural.catalog.edit endpoint set acme/new-model fireworks@us quantization=fp8
    python -m plural.catalog.edit endpoint remove acme/new-model fireworks@us
    python -m plural.catalog.edit remove acme/new-model
    python -m plural.catalog.edit validate --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from plural.catalog.sync import DATA_PATH, load_catalog, order_spec_keys, write_catalog

# Hosts the gateway can route to. ``vertex`` is carried for its published rates
# but has no adapter yet, so a Vertex-only model is never live.
ROUTABLE_HOSTS = frozenset(
    {
        "openai",
        "anthropic",
        "google",
        "groq",
        "together",
        "fireworks",
        "baseten",
        "xai",
        "deepseek",
        "mistral",
        "meta",
        "moonshot",
        "qwen",
        "zhipu",
        "azure",
        "bedrock",
    }
)
PRICE_ONLY_HOSTS = frozenset({"vertex"})
KNOWN_HOSTS = ROUTABLE_HOSTS | PRICE_ONLY_HOSTS
REGIONS = frozenset({"us", "eu", "global", "cn", "ap", "ca", "sa", "me", "af"})
MODALITIES = frozenset({"text", "image", "audio", "video", "file"})
# Request parameters the gateway forwards. Anything else on a card is a typo or
# a parameter callers cannot actually send.
PARAMETERS = frozenset(
    {
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "stop",
        "seed",
        "tools",
        "tool_choice",
        "response_format",
        "structured_outputs",
        "frequency_penalty",
        "presence_penalty",
        "repetition_penalty",
        "logit_bias",
        "logprobs",
        "top_logprobs",
        "min_p",
        "reasoning",
        "include_reasoning",
        "parallel_tool_calls",
    }
)
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._:-]*$")
_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")

Rate = str | float | int


class TierDocument(BaseModel):
    """A prompt-length price tier as stored."""

    model_config = ConfigDict(extra="forbid")

    min_prompt_tokens: int = Field(gt=0)
    prompt: Rate
    completion: Rate


class PricingDocument(BaseModel):
    """Per-token prices in USD, as stored. Strings keep exact decimals."""

    model_config = ConfigDict(extra="forbid")

    prompt: Rate
    completion: Rate
    cache_read: Rate | None = None
    cache_write: Rate | None = None
    tiers: list[TierDocument] = Field(default_factory=list)


class ArchitectureDocument(BaseModel):
    """Modalities, as stored."""

    model_config = ConfigDict(extra="forbid")

    modality: str | None = None
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])


class EndpointDocument(BaseModel):
    """One host that serves the model, at its own price."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="Host slug; see `providers`.")
    region: str = "us"
    upstream_id: str = Field(min_length=1, description="Model id the host expects.")
    pricing: PricingDocument | None = None
    context_length: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    quantization: str | None = None


class ModelCardDocument(BaseModel):
    """One ``models.json`` entry: everything a model card shows.

    Unknown keys are rejected so a misspelled field fails validation instead of
    silently never reaching the card.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="`author/slug`, lowercase.")
    name: str = Field(min_length=1, description="Display name, `Author: Model`.")
    description: str | None = None
    created: str | None = Field(default=None, description="Release date, YYYY-MM-DD.")
    knowledge_cutoff: str | None = Field(default=None, description="YYYY-MM or YYYY-MM-DD.")
    context_length: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    pricing: PricingDocument | None = Field(
        default=None, description="Default price; each endpoint carries its own."
    )
    architecture: ArchitectureDocument = Field(default_factory=ArchitectureDocument)
    supported_parameters: list[str] = Field(default_factory=list)
    open_weights: bool | None = None
    license: str | None = None
    links: dict[str, str] = Field(default_factory=dict)
    endpoints: list[EndpointDocument] = Field(default_factory=list)


class Issue(BaseModel):
    """A validation finding."""

    level: Literal["error", "warning"]
    model: str | None
    path: str
    message: str


def _rate(value: Rate | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def parse_rate(raw: str) -> str:
    """Parse a price written per token or per million tokens.

    Args:
        raw: ``0.000003``, ``3e-6``, or ``3/M``.

    Returns:
        The per-token price as a plain decimal string.

    Raises:
        ValueError: If the value is not a non-negative number.

    Examples:
        >>> parse_rate("3/M")
        '0.000003'
        >>> parse_rate("0.0000025")
        '0.0000025'
        >>> parse_rate("0.15/m")
        '0.00000015'
    """
    text = raw.strip()
    per_million = text.lower().endswith("/m")
    if per_million:
        text = text[:-2].strip()
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a price: {raw!r}") from exc
    if value < 0:
        raise ValueError(f"price cannot be negative: {raw!r}")
    if per_million:
        value = value / Decimal(1_000_000)
    return _plain(value)


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text not in {"-0", ""} else "0"


def _issues_for_pricing(
    model: str, path: str, pricing: PricingDocument | None, issues: list[Issue]
) -> None:
    if pricing is None:
        return
    for key in ("prompt", "completion", "cache_read", "cache_write"):
        raw = getattr(pricing, key)
        if raw is None:
            continue
        value = _rate(raw)
        if value is None or value < 0:
            issues.append(
                Issue(
                    level="error", model=model, path=f"{path}.{key}", message=f"bad price {raw!r}"
                )
            )
        elif value > Decimal("0.01"):
            issues.append(
                Issue(
                    level="warning",
                    model=model,
                    path=f"{path}.{key}",
                    message=f"{raw} per token is ${value * 1_000_000}/M; prices are per token",
                )
            )
    prompt = _rate(pricing.prompt)
    read = _rate(pricing.cache_read) if pricing.cache_read is not None else None
    write = _rate(pricing.cache_write) if pricing.cache_write is not None else None
    if prompt is not None and read is not None and read > prompt:
        issues.append(
            Issue(
                level="error",
                model=model,
                path=f"{path}.cache_read",
                message="a cache read never costs more than a prompt token",
            )
        )
    if prompt is not None and write is not None and write < prompt:
        issues.append(
            Issue(
                level="error",
                model=model,
                path=f"{path}.cache_write",
                message="a cache write never costs less than a prompt token",
            )
        )
    if read is None:
        issues.append(
            Issue(
                level="warning",
                model=model,
                path=f"{path}.cache_read",
                message="no cache read price; cached tokens bill at the full prompt rate",
            )
        )
    thresholds = [tier.min_prompt_tokens for tier in pricing.tiers]
    if thresholds != sorted(set(thresholds)):
        issues.append(
            Issue(
                level="error",
                model=model,
                path=f"{path}.tiers",
                message="tier thresholds must be unique and ascending",
            )
        )
    for index, tier in enumerate(pricing.tiers):
        for key in ("prompt", "completion"):
            raw = getattr(tier, key)
            value = _rate(raw)
            if value is None or value < 0:
                issues.append(
                    Issue(
                        level="error",
                        model=model,
                        path=f"{path}.tiers[{index}].{key}",
                        message=f"bad price {raw!r}",
                    )
                )


CACHE_WRITE_PREMIUM = frozenset({"anthropic"})
"""Model authors whose models bill a premium to write the prompt cache, on any host."""


def _charges_for_cache_writes(model: str, host: str) -> bool:
    return host in CACHE_WRITE_PREMIUM or model.split("/", 1)[0] in CACHE_WRITE_PREMIUM


def validate_entry(card: ModelCardDocument) -> list[Issue]:
    """Check one parsed entry beyond its shape.

    Args:
        card: A parsed catalog entry.

    Returns:
        Errors, which block a write, and warnings, which ``--strict`` promotes.
    """
    issues: list[Issue] = []
    model = card.id

    def add(level: Literal["error", "warning"], path: str, message: str) -> None:
        issues.append(Issue(level=level, model=model, path=path, message=message))

    if not _MODEL_ID.match(card.id):
        add("error", "id", "id must be lowercase `author/slug`")
    for key in ("created", "knowledge_cutoff"):
        value = getattr(card, key)
        if value is not None and not _DATE.match(value):
            add("error", key, f"{key} must be YYYY-MM or YYYY-MM-DD, got {value!r}")
    if not card.description:
        add("warning", "description", "model card has no description")
    if not card.created:
        add("warning", "created", "model card has no release date")
    if card.context_length is None:
        add("warning", "context_length", "model card has no context length")
    if (
        card.max_output_tokens is not None
        and card.context_length is not None
        and card.max_output_tokens > card.context_length
    ):
        add("error", "max_output_tokens", "max_output_tokens exceeds context_length")
    for name, url in card.links.items():
        if not url.startswith("https://"):
            add("error", f"links.{name}", "links must be https URLs")

    modalities = [*card.architecture.input_modalities, *card.architecture.output_modalities]
    for modality in modalities:
        if modality not in MODALITIES:
            add("error", "architecture", f"unknown modality {modality!r}")
    expected = (
        "+".join(card.architecture.input_modalities)
        + "->"
        + "+".join(card.architecture.output_modalities)
    )
    if card.architecture.modality and card.architecture.modality != expected:
        add("warning", "architecture.modality", f"modality should read {expected!r}")
    for parameter in card.supported_parameters:
        if parameter not in PARAMETERS:
            add("warning", "supported_parameters", f"unknown parameter {parameter!r}")
    if len(set(card.supported_parameters)) != len(card.supported_parameters):
        add("error", "supported_parameters", "duplicate parameters")

    _issues_for_pricing(model, "pricing", card.pricing, issues)
    seen: set[tuple[str, str]] = set()
    live = False
    for index, endpoint in enumerate(card.endpoints):
        path = f"endpoints[{index}]"
        host = (endpoint.provider, endpoint.region)
        if host in seen:
            add("error", path, f"duplicate endpoint {endpoint.provider}@{endpoint.region}")
        seen.add(host)
        if endpoint.provider not in KNOWN_HOSTS:
            add(
                "error",
                f"{path}.provider",
                f"unknown host {endpoint.provider!r}; see `providers`",
            )
        if endpoint.region not in REGIONS:
            add("warning", f"{path}.region", f"unusual region {endpoint.region!r}")
        if endpoint.pricing is None:
            add("warning", f"{path}.pricing", "unpriced endpoint is never routed")
        elif endpoint.provider in ROUTABLE_HOSTS:
            live = True
        _issues_for_pricing(model, f"{path}.pricing", endpoint.pricing, issues)
        if (
            endpoint.pricing is not None
            and endpoint.pricing.cache_write is None
            and _charges_for_cache_writes(model, endpoint.provider)
        ):
            add(
                "error",
                f"{path}.pricing.cache_write",
                "this host charges extra to write the prompt cache; declare cache_write",
            )
        if (
            endpoint.context_length is not None
            and card.context_length is not None
            and endpoint.context_length > card.context_length
        ):
            add("error", f"{path}.context_length", "host context exceeds the model's")
    if not card.endpoints:
        if card.pricing is None:
            add("warning", "pricing", "no price and no endpoints; the model is never live")
        else:
            live = model.split("/", 1)[0] in ROUTABLE_HOSTS
    if not live:
        add("warning", "endpoints", "no priced endpoint on a routable host; the model is hidden")
    return issues


def validate_document(document: Mapping[str, Any]) -> list[Issue]:
    """Validate a whole catalog document.

    Args:
        document: Decoded ``models.json``.

    Returns:
        Every issue across every entry.
    """
    issues: list[Issue] = []
    seen: set[str] = set()
    for index, raw in enumerate(document.get("models") or []):
        model_id = raw.get("id") if isinstance(raw, Mapping) else None
        label = str(model_id) if model_id else f"models[{index}]"
        if model_id in seen:
            issues.append(Issue(level="error", model=label, path="id", message="duplicate id"))
        if model_id:
            seen.add(str(model_id))
        try:
            card = ModelCardDocument.model_validate(raw)
        except ValidationError as exc:
            for error in exc.errors():
                issues.append(
                    Issue(
                        level="error",
                        model=label,
                        path=".".join(str(part) for part in error["loc"]),
                        message=error["msg"],
                    )
                )
            continue
        issues.extend(validate_entry(card))
    return issues


class EditError(Exception):
    """A command that cannot be applied."""


def _entries(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): dict(item) for item in document.get("models") or []}


def _require(entries: Mapping[str, dict[str, Any]], model_id: str) -> dict[str, Any]:
    entry = entries.get(model_id)
    if entry is None:
        raise EditError(f"no model {model_id!r} in the catalog")
    return entry


def _rebuild(
    document: Mapping[str, Any], entries: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "models": [_clean(order_spec_keys(entries[key])) for key in sorted(entries)],
    }


def _clean(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Drop empty optional card fields so unset values do not litter the file.

    Returns:
        The entry without empty optional fields.
    """
    return {
        key: value
        for key, value in entry.items()
        if not (key in {"links", "description", "license"} and value in ({}, None, ""))
        and not (
            key in {"created", "knowledge_cutoff", "max_output_tokens", "open_weights"}
            and value is None
        )
    }


_PRICE_KEYS = frozenset({"prompt", "completion", "cache_read", "cache_write"})
_LIST_KEYS = frozenset({"supported_parameters", "input_modalities", "output_modalities"})


def parse_value(path: str, raw: str) -> Any:
    """Decode a ``key=value`` right-hand side for the field it targets.

    Prices accept ``/M``; list fields accept ``a,b,c``; anything else is read as
    JSON when it parses and as a string otherwise.

    Returns:
        The value to store.

    Examples:
        >>> parse_value("pricing.prompt", "3/M")
        '0.000003'
        >>> parse_value("supported_parameters", "tools,temperature")
        ['tools', 'temperature']
        >>> parse_value("context_length", "200000")
        200000
        >>> parse_value("description", "A small model")
        'A small model'
    """
    leaf = path.rsplit(".", 1)[-1]
    if leaf in _PRICE_KEYS:
        return parse_rate(raw)
    if leaf in _LIST_KEYS and not raw.strip().startswith("["):
        return [item.strip() for item in raw.split(",") if item.strip()]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _assign(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = target
    for part in parts[:-1]:
        child = node.get(part)
        if child is None:
            child = {}
        elif not isinstance(child, dict):
            raise EditError(f"{path}: {part} is not an object")
        node[part] = dict(child)
        node = node[part]
    if value is None:
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = value


def _assignments(pairs: Sequence[str]) -> list[tuple[str, Any]]:
    result = []
    for pair in pairs:
        if "=" not in pair:
            raise EditError(f"expected key=value, got {pair!r}")
        path, raw = pair.split("=", 1)
        path = path.strip()
        if not path:
            raise EditError(f"expected key=value, got {pair!r}")
        try:
            result.append((path, parse_value(path, raw)))
        except ValueError as exc:
            raise EditError(f"{path}: {exc}") from exc
    return result


def _endpoint_ref(ref: str) -> tuple[str, str | None]:
    provider, _, region = ref.partition("@")
    return provider, region or None


def _find_endpoint(entry: Mapping[str, Any], ref: str) -> int:
    provider, region = _endpoint_ref(ref)
    matches = [
        index
        for index, endpoint in enumerate(entry.get("endpoints") or [])
        if endpoint.get("provider") == provider
        and (region is None or (endpoint.get("region") or "us") == region)
    ]
    if not matches:
        raise EditError(f"{entry['id']} has no endpoint {ref!r}")
    if len(matches) > 1:
        raise EditError(f"{ref!r} matches several regions; name one as provider@region")
    return matches[0]


def template(model_id: str) -> dict[str, Any]:
    """A complete, valid-shaped entry to fill in for a new model.

    Returns:
        An entry with placeholder values for every card field.
    """
    return {
        "id": model_id,
        "name": "Author: Model Name",
        "description": "One or two sentences on what the model is for and how it compares.",
        "created": "YYYY-MM-DD",
        "knowledge_cutoff": "YYYY-MM",
        "context_length": 128000,
        "max_output_tokens": 16384,
        "pricing": {"prompt": "0.000001", "completion": "0.000004"},
        "architecture": {
            "modality": "text->text",
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        "supported_parameters": ["max_tokens", "temperature", "tools", "tool_choice"],
        "open_weights": False,
        "links": {"homepage": "https://example.com/model"},
        "endpoints": [
            {
                "provider": model_id.split("/", 1)[0],
                "region": "us",
                "upstream_id": model_id.split("/", 1)[-1],
                "pricing": {"prompt": "0.000001", "completion": "0.000004"},
            }
        ],
    }


def _from_openrouter(model_id: str) -> dict[str, Any]:
    import httpx

    from plural.catalog.sync import (
        _spec_from_upstream,
        fetch_endpoints,
        fetch_openrouter,
        standard_endpoints,
    )

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        upstream = fetch_openrouter(client)
        model = upstream.get(model_id)
        if model is None:
            raise EditError(f"OpenRouter does not list {model_id!r}")
        hosts = fetch_endpoints(client, model_id)
    entry = _spec_from_upstream(model)
    endpoints = []
    for (provider, region), host in sorted(standard_endpoints(hosts).items()):
        if provider not in KNOWN_HOSTS:
            continue
        endpoint: dict[str, Any] = {
            "provider": provider,
            "region": region,
            "upstream_id": host.upstream_id,
        }
        if host.priced:
            endpoint["pricing"] = {
                "prompt": _plain(Decimal(str(host.prompt))),
                "completion": _plain(Decimal(str(host.completion))),
            }
        endpoints.append(endpoint)
    entry["endpoints"] = endpoints
    return entry


_ENRICHED = ("description", "created", "max_output_tokens")


def _slug_key(model_id: str) -> str:
    slug = model_id.rsplit("/", 1)[-1].lower()
    return re.sub(r"[^a-z0-9]", "", slug)


def match_upstream(model_id: str, upstream: Mapping[str, Any], alias: str | None = None) -> Any:
    """Find a catalog model in the upstream list, which names some authors differently.

    OpenRouter lists ``x-ai/grok-4.3`` where the catalog says ``xai/grok-4.3``, and
    writes versions with dots where a lab uses dashes. An exact id wins, then an
    ``alias``, then a unique match on the version-insensitive slug.

    Returns:
        The upstream record, or ``None`` when there is no unambiguous match.

    Examples:
        >>> match_upstream("xai/grok-4.3", {"x-ai/grok-4.3": 1})
        1
        >>> match_upstream("anthropic/claude-haiku-4-5", {"anthropic/claude-haiku-4.5": 2})
        2
        >>> match_upstream("a/x", {"b/x": 1, "c/x": 2}) is None
        True
    """
    if alias:
        return upstream.get(alias)
    if model_id in upstream:
        return upstream[model_id]
    key = _slug_key(model_id)
    found = [value for upstream_id, value in upstream.items() if _slug_key(upstream_id) == key]
    return found[0] if len(found) == 1 else None


def complete_sentences(text: str) -> str:
    """Drop a trailing fragment from a description the upstream list cut short.

    Returns:
        The text ending at its last complete sentence.

    Examples:
        >>> complete_sentences("Fast model. Good at code, and...")
        'Fast model.'
        >>> complete_sentences("Fast model.")
        'Fast model.'
    """
    stripped = text.strip()
    if not stripped.endswith(("...", "…")):
        return stripped
    cut = max(stripped.rfind(". "), stripped.rfind("! "), stripped.rfind("? "))
    return stripped[: cut + 1] if cut > 0 else stripped.rstrip(".… ")


def _enrich(entries: dict[str, dict[str, Any]], ids: Sequence[str], alias: str | None) -> list[str]:
    import httpx

    from plural.catalog.sync import fetch_openrouter

    if alias and len(ids) != 1:
        raise EditError("--as names the upstream id for exactly one model")
    targets = list(ids) or sorted(entries)
    for model_id in targets:
        _require(entries, model_id)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        upstream = fetch_openrouter(client)
    changed = []
    for model_id in targets:
        model = match_upstream(model_id, upstream, alias)
        if model is None:
            continue
        entry = entries[model_id]
        filled = False
        for key in _ENRICHED:
            value = getattr(model, key)
            if key == "description" and value:
                value = complete_sentences(value)
            if value and not entry.get(key):
                entry[key] = value
                filled = True
        if filled:
            changed.append(model_id)
    return changed


_CACHE_PRICE_STEP = Decimal("1e-12")


def _cache_ratio(field: str, prompt: float | None, rate: float | None) -> Decimal | None:
    """The cache price as a fraction of the prompt price, when it is a usable one.

    Some hosts list a sub-prompt ``input_cache_write`` that amortizes explicit cache
    storage rather than pricing a write; a write that costs less than a fresh prompt
    token is never taken as the write rate.

    Returns:
        The ratio, or ``None`` when the upstream figure should not be used.
    """
    if not prompt or rate is None:
        return None
    ratio = Decimal(str(rate)) / Decimal(str(prompt))
    if field == "cache_write" and ratio < 1:
        return None
    if field == "cache_read" and ratio > 1:
        return None
    return ratio


def _cache_prices(
    entries: dict[str, dict[str, Any]],
    ids: Sequence[str],
    alias: str | None,
    replace: bool,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Fill cache read and write prices from OpenRouter's per-host listings.

    A host's cache price is taken as the same fraction of its prompt price that
    OpenRouter lists for that host and region, else for that host in any region,
    rounded up to a millionth of a dollar per million tokens. One host's cache
    discount is never assumed for another: a host with no upstream cache price is
    left alone, so its cached tokens bill at the full prompt rate.

    Returns:
        The changed model ids and one report row per price written or model skipped.

    Raises:
        EditError: When ``alias`` is given for more than one model, or an id is unknown.
    """
    import httpx

    from plural.catalog.sync import fetch_endpoints, fetch_openrouter

    if alias and len(ids) != 1:
        raise EditError("--as names the upstream id for exactly one model")
    targets = list(ids) or sorted(entries)
    for model_id in targets:
        _require(entries, model_id)
    changed: list[str] = []
    report: list[dict[str, Any]] = []
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        upstream = fetch_openrouter(client)
        for model_id in targets:
            model = match_upstream(model_id, upstream, alias)
            if model is None:
                report.append({"model": model_id, "skipped": "not on OpenRouter"})
                continue
            exact: dict[tuple[str, str], Any] = {}
            by_provider: dict[str, Any] = {}
            for host in fetch_endpoints(client, model.id):
                if host.provider is None or host.tier != "standard" or not host.prompt:
                    continue
                exact.setdefault((host.provider, host.region), host)
                by_provider.setdefault(host.provider, host)
            entry = entries[model_id]
            endpoints: list[dict[str, Any]] = entry.get("endpoints") or []
            priced = [
                (f"endpoints[{index}]", endpoint, endpoint.get("pricing"))
                for index, endpoint in enumerate(endpoints)
            ]
            if entry.get("pricing"):
                priced.append(("pricing", endpoints[0] if endpoints else {}, entry["pricing"]))
            touched = False
            for path, endpoint, pricing in priced:
                if not isinstance(pricing, dict) or pricing.get("prompt") is None:
                    continue
                provider = str(endpoint.get("provider"))
                region = str(endpoint.get("region") or "us")
                match = exact.get((provider, region)) or by_provider.get(provider)
                if match is None:
                    continue
                source = "host+region" if (provider, region) in exact else "host"
                for field in ("cache_read", "cache_write"):
                    if pricing.get(field) is not None and not replace:
                        continue
                    ratio = _cache_ratio(field, match.prompt, getattr(match, field))
                    if ratio is None:
                        continue
                    exact_value = Decimal(str(pricing["prompt"])) * ratio
                    value = _plain(exact_value.quantize(_CACHE_PRICE_STEP, rounding=ROUND_CEILING))
                    if pricing.get(field) == value:
                        continue
                    pricing[field] = value
                    touched = True
                    report.append(
                        {
                            "model": model_id,
                            "path": f"{path}.{field}",
                            "value": value,
                            "host": f"{provider}@{region}",
                            "source": source,
                        }
                    )
            if touched:
                changed.append(model_id)
    return changed, report


def _summary(entry: Mapping[str, Any]) -> dict[str, Any]:
    endpoints = entry.get("endpoints") or []
    return {
        "id": entry["id"],
        "name": entry.get("name"),
        "hosts": [f"{e.get('provider')}@{e.get('region') or 'us'}" for e in endpoints],
        "priced": any(e.get("pricing") for e in endpoints) or bool(entry.get("pricing")),
        "card_complete": all(
            entry.get(key) for key in ("description", "created", "context_length")
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Execute one parsed command against the catalog at ``args.path``.

    Returns:
        The JSON result to print.

    Raises:
        EditError: When the command cannot be applied or would leave the
            catalog invalid.
    """
    path: Path = args.path
    document = load_catalog(path)
    entries = _entries(document)
    command = args.command
    cache_report: list[dict[str, Any]] | None = None

    if command == "schema":
        return {"ok": True, "schema": ModelCardDocument.model_json_schema()}
    if command == "providers":
        return {
            "ok": True,
            "routable": sorted(ROUTABLE_HOSTS),
            "price_only": sorted(PRICE_ONLY_HOSTS),
            "regions": sorted(REGIONS),
            "modalities": sorted(MODALITIES),
            "parameters": sorted(PARAMETERS),
        }
    if command == "template":
        return {"ok": True, "entry": template(args.model_id)}
    if command == "list":
        return {"ok": True, "models": [_summary(entries[key]) for key in sorted(entries)]}
    if command == "show":
        return {"ok": True, "entry": _require(entries, args.model_id)}
    if command == "validate":
        issues = validate_document(document)
        errors = [issue for issue in issues if issue.level == "error"]
        warnings = [issue for issue in issues if issue.level == "warning"]
        failed = errors or (args.strict and warnings)
        return {
            "ok": not failed,
            "models": len(entries),
            "errors": [issue.model_dump() for issue in errors],
            "warnings": [issue.model_dump() for issue in warnings],
        }

    changed: list[str]
    if command == "add":
        if args.file:
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text("utf-8")
            try:
                entry = json.loads(text)
            except json.JSONDecodeError as exc:
                raise EditError(f"entry is not JSON: {exc}") from exc
            if not isinstance(entry, dict) or "id" not in entry:
                raise EditError("entry must be a JSON object with an id")
            if args.model_id and args.model_id != entry["id"]:
                raise EditError(f"entry id {entry['id']!r} does not match {args.model_id!r}")
        elif args.from_openrouter and args.model_id:
            entry = _from_openrouter(args.model_id)
        else:
            raise EditError("add needs --file PATH (or -) or MODEL_ID --from-openrouter")
        if entry["id"] in entries and not args.replace:
            raise EditError(f"{entry['id']} is already in the catalog; pass --replace")
        entries[entry["id"]] = entry
        changed = [entry["id"]]
    elif command == "set":
        entry = _require(entries, args.model_id)
        for key, value in _assignments(args.assignments):
            if key == "id":
                raise EditError("rename a model by adding the new id and removing the old one")
            _assign(entry, key, value)
        for key in args.unset or []:
            _assign(entry, key, None)
        changed = [args.model_id]
    elif command == "enrich":
        changed = _enrich(entries, args.model_ids, args.alias)
        if not changed:
            return {"ok": True, "written": False, "changed": [], "entries": [], "warnings": []}
    elif command == "cache-prices":
        changed, cache_report = _cache_prices(entries, args.model_ids, args.alias, args.replace)
        if not changed:
            return {"ok": True, "written": False, "changed": [], "prices": cache_report}
    elif command == "remove":
        _require(entries, args.model_id)
        del entries[args.model_id]
        changed = [args.model_id]
    elif command == "endpoint":
        entry = _require(entries, args.model_id)
        endpoints = [dict(item) for item in entry.get("endpoints") or []]
        if args.endpoint_command == "add":
            endpoint: dict[str, Any] = {
                "provider": args.provider,
                "region": args.region,
                "upstream_id": args.upstream_id,
            }
            if args.prompt is not None or args.completion is not None:
                if args.prompt is None or args.completion is None:
                    raise EditError("an endpoint price needs both --prompt and --completion")
                pricing: dict[str, Any] = {
                    "prompt": parse_rate(args.prompt),
                    "completion": parse_rate(args.completion),
                }
                if args.cache_read is not None:
                    pricing["cache_read"] = parse_rate(args.cache_read)
                if args.cache_write is not None:
                    pricing["cache_write"] = parse_rate(args.cache_write)
                endpoint["pricing"] = pricing
            for key in ("context_length", "max_output_tokens", "quantization"):
                value = getattr(args, key)
                if value is not None:
                    endpoint[key] = value
            if any(
                e.get("provider") == args.provider and (e.get("region") or "us") == args.region
                for e in endpoints
            ):
                raise EditError(
                    f"{args.model_id} already has {args.provider}@{args.region}; use endpoint set"
                )
            endpoints.append(endpoint)
        elif args.endpoint_command == "set":
            index = _find_endpoint(entry, args.ref)
            target = endpoints[index]
            for key, value in _assignments(args.assignments):
                _assign(target, key, value)
            for key in args.unset or []:
                _assign(target, key, None)
        elif args.endpoint_command == "remove":
            endpoints.pop(_find_endpoint(entry, args.ref))
        entry["endpoints"] = endpoints
        changed = [args.model_id]
    else:  # pragma: no cover - argparse rejects unknown commands
        raise EditError(f"unknown command {command!r}")

    updated = _rebuild(document, entries)
    issues = validate_document(updated)
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        rejected: dict[str, Any] = {
            "ok": False,
            "errors": [issue.model_dump() for issue in errors],
        }
        if cache_report is not None:
            rejected["prices"] = cache_report
        return rejected
    if not args.dry_run:
        write_catalog(updated, path)
    changed_entries = {item["id"]: item for item in updated["models"] if item["id"] in changed}
    extra: dict[str, Any] = {"prices": cache_report} if cache_report is not None else {}
    return {
        **extra,
        "ok": True,
        "written": not args.dry_run,
        "changed": changed,
        "entries": [changed_entries[key] for key in changed if key in changed_entries],
        "warnings": [
            issue.model_dump()
            for issue in issues
            if issue.level == "warning" and issue.model in changed
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    """The command-line interface.

    Returns:
        The argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="python -m plural.catalog.edit",
        description="Maintain the bundled model catalog. Prints JSON.",
    )
    parser.add_argument("--path", type=Path, default=DATA_PATH, help="Catalog file to edit.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and print the result without writing."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("schema", help="JSON Schema of one catalog entry.")
    commands.add_parser("providers", help="Known hosts, regions, modalities, parameters.")
    template_cmd = commands.add_parser("template", help="A complete entry to fill in.")
    template_cmd.add_argument("model_id")
    commands.add_parser("list", help="Every model with its hosts.")
    show = commands.add_parser("show", help="One entry.")
    show.add_argument("model_id")
    validate = commands.add_parser("validate", help="Check the whole catalog.")
    validate.add_argument("--strict", action="store_true", help="Fail on warnings too.")

    add = commands.add_parser("add", help="Add a model from a JSON entry or from OpenRouter.")
    add.add_argument("model_id", nargs="?")
    add.add_argument("--file", help="JSON entry to add; - reads stdin.")
    add.add_argument(
        "--from-openrouter",
        action="store_true",
        help="Prefill the card and host prices from OpenRouter. Review before committing.",
    )
    add.add_argument("--replace", action="store_true", help="Overwrite an existing entry.")

    set_cmd = commands.add_parser("set", help="Set card fields: key=value, dotted for nesting.")
    set_cmd.add_argument("model_id")
    set_cmd.add_argument("assignments", nargs="*", metavar="key=value")
    set_cmd.add_argument("--unset", action="append", metavar="KEY", help="Remove a field.")

    enrich = commands.add_parser(
        "enrich",
        help="Fill missing description, release date, and max output from OpenRouter.",
    )
    enrich.add_argument("model_ids", nargs="*", metavar="MODEL_ID", help="Default: every model.")
    enrich.add_argument("--as", dest="alias", help="OpenRouter id, when it differs.")

    cache = commands.add_parser(
        "cache-prices",
        help="Fill cache read and write prices from OpenRouter's per-host listings.",
    )
    cache.add_argument("model_ids", nargs="*", metavar="MODEL_ID", help="Default: every model.")
    cache.add_argument("--as", dest="alias", help="OpenRouter id, when it differs.")
    cache.add_argument("--replace", action="store_true", help="Overwrite declared cache prices.")

    remove = commands.add_parser("remove", help="Drop a model from the catalog.")
    remove.add_argument("model_id")

    endpoint = commands.add_parser("endpoint", help="Add, change, or remove a host.")
    endpoint_commands = endpoint.add_subparsers(dest="endpoint_command", required=True)
    endpoint_add = endpoint_commands.add_parser("add")
    endpoint_add.add_argument("model_id")
    endpoint_add.add_argument("--provider", required=True)
    endpoint_add.add_argument("--region", default="us")
    endpoint_add.add_argument("--upstream-id", required=True)
    endpoint_add.add_argument("--prompt", help="USD per prompt token, or N/M.")
    endpoint_add.add_argument("--completion", help="USD per completion token, or N/M.")
    endpoint_add.add_argument("--cache-read")
    endpoint_add.add_argument("--cache-write")
    endpoint_add.add_argument("--context-length", type=int)
    endpoint_add.add_argument("--max-output-tokens", type=int)
    endpoint_add.add_argument("--quantization")
    endpoint_set = endpoint_commands.add_parser("set")
    endpoint_set.add_argument("model_id")
    endpoint_set.add_argument("ref", metavar="provider[@region]")
    endpoint_set.add_argument("assignments", nargs="*", metavar="key=value")
    endpoint_set.add_argument("--unset", action="append", metavar="KEY")
    endpoint_remove = endpoint_commands.add_parser("remove")
    endpoint_remove.add_argument("model_id")
    endpoint_remove.add_argument("ref", metavar="provider[@region]")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and print its JSON result.

    Returns:
        ``0`` on success, ``1`` when the command failed or validation did.
    """
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (EditError, ValueError) as exc:
        result = {"ok": False, "errors": [{"level": "error", "message": str(exc)}]}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
