"""Model catalog types and cost estimation.

Examples:
    >>> from plural.catalog.models import ModelCatalog, estimate_cost
    >>> from plural.types import Usage
    >>> cat = ModelCatalog()
    >>> spec = cat.get("openai/gpt-5.6-luna")
    >>> spec is not None
    True
    >>> estimate_cost(Usage.from_counts(1000, 500), spec) > 0
    True
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from plural.catalog.billing import PriceRates, charge_usage
from plural.errors import NotFoundError
from plural.types import Usage

_US_HOST_ORDER = ("fireworks", "baseten")


def normalize_region(value: str) -> str:
    """Collapse a vendor region label to the catalog's coarse regions.

    Vendors name regions at finer grain than pricing varies, so ``us-east-1`` and
    ``us-west-2`` both bill as ``us``.

    Args:
        value: Region label such as ``us-east-1`` or ``europe-west4``.

    Returns:
        A short region key.

    Examples:
        >>> normalize_region("us-east-1"), normalize_region("europe-west4")
        ('us', 'eu')
        >>> normalize_region("global")
        'global'
    """
    lowered = value.lower()
    if lowered.startswith("us"):
        return "us"
    if lowered.startswith(("eu", "europe")):
        return "eu"
    if lowered.startswith("global"):
        return "global"
    return lowered


class PriceTier(BaseModel):
    """A rate that replaces the base rate once a prompt gets large enough.

    Attributes:
        min_prompt_tokens: Prompt size at which this tier starts applying.
        prompt: USD per prompt token at this tier.
        completion: USD per completion token at this tier.
    """

    min_prompt_tokens: int
    prompt: float
    completion: float


class ModelPricing(BaseModel):
    """Per-token pricing in USD.

    Attributes:
        prompt: USD per prompt token below the first tier threshold.
        completion: USD per completion token below the first tier threshold.
        tiers: Rates for larger prompts, if the model prices them differently.
        cache_read: USD per prompt token served from the host's prompt cache.
            Undeclared, a cache read bills at the prompt rate.
        cache_write: USD per prompt token written to the host's prompt cache.
            Undeclared, a write bills at 1.25 times the prompt rate; see
            :mod:`plural.catalog.billing`.
    """

    prompt: float
    completion: float
    tiers: list[PriceTier] = Field(default_factory=list)
    cache_read: float | None = None
    cache_write: float | None = None

    def rates_for_prompt(self, prompt_tokens: int) -> tuple[float, float]:
        """Resolve the rates that apply to a request of a given prompt size.

        Providers that price long context replace the rate for the whole request
        rather than charging a higher rate only on tokens past the threshold, so
        the matching tier supersedes the base rate outright.

        Args:
            prompt_tokens: Prompt tokens in the request being billed.

        Returns:
            A (prompt rate, completion rate) pair.

        Examples:
            >>> pricing = ModelPricing(
            ...     prompt=5e-06,
            ...     completion=3e-05,
            ...     tiers=[PriceTier(min_prompt_tokens=272000, prompt=1e-05, completion=6e-05)],
            ... )
            >>> pricing.rates_for_prompt(1000)
            (5e-06, 3e-05)
            >>> pricing.rates_for_prompt(300000)
            (1e-05, 6e-05)
        """
        applicable = [tier for tier in self.tiers if prompt_tokens >= tier.min_prompt_tokens]
        if not applicable:
            return self.prompt, self.completion
        tier = max(applicable, key=lambda item: item.min_prompt_tokens)
        return tier.prompt, tier.completion

    def rates_at(self, prompt_tokens: int) -> PriceRates:
        """Every rate that applies to a request of a given prompt size.

        A long-context tier raises the cache rates in proportion to the prompt
        rate, as hosts that tier by prompt size do.

        Args:
            prompt_tokens: Prompt tokens in the request, cached or not.

        Returns:
            Per-token rates, including cache rates when declared.

        Examples:
            >>> pricing = ModelPricing(
            ...     prompt=2e-06,
            ...     completion=1e-05,
            ...     cache_read=2e-07,
            ...     tiers=[PriceTier(min_prompt_tokens=200000, prompt=4e-06, completion=1.5e-05)],
            ... )
            >>> str(pricing.rates_at(250000).cache_read)
            '4E-7'
        """
        prompt, completion = self.rates_for_prompt(prompt_tokens)
        ratio = Decimal(str(prompt)) / Decimal(str(self.prompt)) if self.prompt else Decimal(1)

        def scaled(rate: float | None) -> Decimal | None:
            return None if rate is None else Decimal(str(rate)) * ratio

        return PriceRates(
            prompt=Decimal(str(prompt)),
            completion=Decimal(str(completion)),
            cache_read=scaled(self.cache_read),
            cache_write=scaled(self.cache_write),
        )


class Architecture(BaseModel):
    """Model modality metadata.

    Attributes:
        modality: High-level modality string.
        input_modalities: Accepted input modalities.
        output_modalities: Produced output modalities.
    """

    modality: str | None = None
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])


class ModelEndpoint(BaseModel):
    """A concrete inference host for a catalog model.

    Attributes:
        provider: Host slug (``openai``, ``fireworks``, ``moonshot``, …).
        region: Serving region hint (``us``, ``cn``, ``global``).
        upstream_id: Model id the host expects.
        pricing: Pass-through price at this host.
        context_length: This host's context window, when it serves less than
            the model's.
        max_output_tokens: This host's completion limit, when it differs.
        quantization: Weight precision the host serves, such as ``fp8``.
    """

    provider: str
    region: str = "us"
    upstream_id: str
    pricing: ModelPricing | None = None
    context_length: int | None = None
    max_output_tokens: int | None = None
    quantization: str | None = None


class ModelSpec(BaseModel):
    """A catalog entry for a model.

    Attributes:
        id: Model id in ``author/slug`` form.
        name: Human-readable display name.
        context_length: Maximum context window in tokens.
        pricing: Default per-token pricing (US-first host, then first endpoint).
        architecture: Modality metadata.
        supported_parameters: Request parameters the model accepts.
        endpoints: Inference hosts. Empty means the author is the only host.
        description: What the model is for, shown on its model card.
        created: Release date, ``YYYY-MM-DD``.
        knowledge_cutoff: Training data cutoff, ``YYYY-MM`` or ``YYYY-MM-DD``.
        max_output_tokens: Largest completion the model produces.
        open_weights: Whether the weights are published.
        license: License of published weights, such as ``apache-2.0``.
        links: Named reference URLs, such as ``homepage`` or ``model_card``.
        provider: Derived provider slug (author segment of ``id``).
    """

    id: str
    name: str | None = None
    context_length: int | None = None
    pricing: ModelPricing | None = None
    architecture: Architecture = Field(default_factory=Architecture)
    supported_parameters: list[str] = Field(default_factory=list)
    endpoints: list[ModelEndpoint] = Field(default_factory=list)
    description: str | None = None
    created: str | None = None
    knowledge_cutoff: str | None = None
    max_output_tokens: int | None = None
    open_weights: bool | None = None
    license: str | None = None
    links: dict[str, str] = Field(default_factory=dict)

    @property
    def provider(self) -> str:
        """Author slug derived from the model id.

        Returns:
            The ``author`` segment of ``author/slug``, or the full id.
        """
        if "/" in self.id:
            return self.id.split("/", 1)[0]
        return self.id

    def ordered_endpoints(self) -> list[ModelEndpoint]:
        """Return endpoints with US hosts first (Fireworks, then Baseten).

        Returns:
            Ordered endpoints, or a single implicit author host when none are listed.
        """
        if not self.endpoints:
            upstream = self.id.split("/", 1)[1] if "/" in self.id else self.id
            return [
                ModelEndpoint(
                    provider=self.provider,
                    region="us",
                    upstream_id=upstream,
                    pricing=self.pricing,
                )
            ]
        us = [endpoint for endpoint in self.endpoints if endpoint.region == "us"]
        rest = [endpoint for endpoint in self.endpoints if endpoint.region != "us"]

        def us_key(endpoint: ModelEndpoint) -> int:
            if endpoint.provider in _US_HOST_ORDER:
                return _US_HOST_ORDER.index(endpoint.provider)
            return 50

        us.sort(key=us_key)
        return us + rest

    def host_providers(self) -> list[str]:
        """Return host slugs that can serve this model."""
        return [endpoint.provider for endpoint in self.ordered_endpoints()]

    def pricing_for(
        self, provider: str | None = None, region: str | None = None
    ) -> ModelPricing | None:
        """Return pricing for a host, or the default US-first price.

        Region matters because the same provider charges different rates in
        different regions: Azure EU lists above Azure US for identical models.
        When a region is given it must match, so a miss falls back to the default
        rather than billing a cheaper region's rate for a pricier one.

        Args:
            provider: Host slug. ``None`` uses the default endpoint.
            region: Host region. ``None`` matches the first endpoint for the provider.

        Returns:
            Per-token pricing, or ``None``.
        """
        endpoints = self.ordered_endpoints()
        if provider:
            for endpoint in endpoints:
                if endpoint.provider != provider or endpoint.pricing is None:
                    continue
                if region is not None and endpoint.region != region:
                    continue
                return endpoint.pricing
        if endpoints and endpoints[0].pricing is not None:
            return endpoints[0].pricing
        return self.pricing


def estimate_cost(
    usage: Usage,
    spec: ModelSpec | None,
    *,
    provider: str | None = None,
    region: str | None = None,
) -> float | None:
    """Estimate USD cost for a usage record against a model spec.

    Args:
        usage: Token usage.
        spec: Model catalog entry, or ``None``.
        provider: Optional host slug; bills at that host's pass-through price.
        region: Optional host region, for providers whose rates vary by region.

    Returns:
        Estimated USD cost, or ``None`` if pricing is unavailable.

    Examples:
        >>> from plural.types import Usage
        >>> spec = ModelSpec(
        ...     id="openai/gpt-5.6-luna",
        ...     pricing=ModelPricing(prompt=0.0000002, completion=0.0000012),
        ... )
        >>> round(estimate_cost(Usage.from_counts(1_000_000, 0), spec) or 0, 2)
        0.2
    """
    if spec is None:
        return None
    pricing = spec.pricing_for(provider, region)
    if pricing is None:
        return None
    return float(charge_usage(pricing.rates_at(usage.prompt_tokens), usage).total_usd)


def _parse_tiers(raw: Any) -> list[PriceTier]:
    tiers: list[PriceTier] = []
    for item in raw or []:
        try:
            tiers.append(
                PriceTier(
                    min_prompt_tokens=int(item["min_prompt_tokens"]),
                    prompt=float(item["prompt"]),
                    completion=float(item["completion"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            # A malformed tier must not silently become the base rate.
            continue
    tiers.sort(key=lambda tier: tier.min_prompt_tokens)
    return tiers


def _optional_rate(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _optional_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_pricing(raw: dict[str, Any] | None) -> ModelPricing | None:
    if not raw:
        return None
    try:
        return ModelPricing(
            prompt=float(raw["prompt"]),
            completion=float(raw["completion"]),
            tiers=_parse_tiers(raw.get("tiers")),
            cache_read=_optional_rate(raw.get("cache_read")),
            cache_write=_optional_rate(raw.get("cache_write")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _dump_pricing(pricing: ModelPricing | None) -> dict[str, Any] | None:
    if pricing is None:
        return None
    payload: dict[str, Any] = {
        "prompt": str(pricing.prompt),
        "completion": str(pricing.completion),
    }
    if pricing.cache_read is not None:
        payload["cache_read"] = str(pricing.cache_read)
    if pricing.cache_write is not None:
        payload["cache_write"] = str(pricing.cache_write)
    if pricing.tiers:
        payload["tiers"] = [
            {
                "min_prompt_tokens": tier.min_prompt_tokens,
                "prompt": str(tier.prompt),
                "completion": str(tier.completion),
            }
            for tier in pricing.tiers
        ]
    return payload


def _parse_endpoint(raw: dict[str, Any]) -> ModelEndpoint | None:
    provider = raw.get("provider")
    upstream_id = raw.get("upstream_id")
    if not provider or not upstream_id:
        return None
    return ModelEndpoint(
        provider=str(provider),
        region=str(raw.get("region") or "us"),
        upstream_id=str(upstream_id),
        pricing=_parse_pricing(raw.get("pricing")),
        context_length=_optional_int(raw.get("context_length")),
        max_output_tokens=_optional_int(raw.get("max_output_tokens")),
        quantization=raw.get("quantization") or None,
    )


def _dump_endpoint(endpoint: ModelEndpoint) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": endpoint.provider,
        "region": endpoint.region,
        "upstream_id": endpoint.upstream_id,
        "pricing": _dump_pricing(endpoint.pricing),
    }
    for key in ("context_length", "max_output_tokens", "quantization"):
        value = getattr(endpoint, key)
        if value is not None:
            payload[key] = value
    return payload


_CARD_FIELDS = (
    "description",
    "created",
    "knowledge_cutoff",
    "max_output_tokens",
    "open_weights",
    "license",
)


def _card_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {key: item.get(key) for key in _CARD_FIELDS}
    fields["max_output_tokens"] = _optional_int(item.get("max_output_tokens"))
    open_weights = item.get("open_weights")
    fields["open_weights"] = open_weights if isinstance(open_weights, bool) else None
    for key in ("description", "created", "knowledge_cutoff", "license"):
        value = fields[key]
        fields[key] = str(value) if value else None
    links = item.get("links")
    fields["links"] = (
        {str(name): str(url) for name, url in links.items() if url}
        if isinstance(links, Mapping)
        else {}
    )
    return fields


def spec_from_payload(item: Mapping[str, Any]) -> ModelSpec:
    """Build a :class:`ModelSpec` from one ``models.json`` entry.

    Malformed optional values are dropped rather than rejected, so one bad field
    never takes a model out of the catalog. ``plural.catalog.edit validate``
    reports them instead.

    Args:
        item: A decoded catalog entry.

    Returns:
        The model spec, priced at its default host when it has no base price.
    """
    endpoints = [
        endpoint
        for raw in item.get("endpoints") or []
        if (endpoint := _parse_endpoint(raw)) is not None
    ]
    architecture = item.get("architecture") or {}
    spec = ModelSpec(
        id=item["id"],
        name=item.get("name"),
        context_length=item.get("context_length"),
        pricing=_parse_pricing(item.get("pricing")),
        architecture=Architecture(
            modality=architecture.get("modality"),
            input_modalities=list(architecture.get("input_modalities") or ["text"]),
            output_modalities=list(architecture.get("output_modalities") or ["text"]),
        ),
        supported_parameters=list(item.get("supported_parameters") or []),
        endpoints=endpoints,
        **_card_fields(item),
    )
    if spec.pricing is None:
        spec.pricing = spec.pricing_for()
    return spec


def spec_to_payload(spec: ModelSpec) -> dict[str, Any]:
    """Serialize a :class:`ModelSpec` the way ``models.json`` stores it.

    Returns:
        A JSON-compatible entry. Unset card fields are omitted.
    """
    payload: dict[str, Any] = {
        "id": spec.id,
        "name": spec.name,
    }
    for key in ("description", "created", "knowledge_cutoff"):
        value = getattr(spec, key)
        if value is not None:
            payload[key] = value
    payload["context_length"] = spec.context_length
    if spec.max_output_tokens is not None:
        payload["max_output_tokens"] = spec.max_output_tokens
    payload["pricing"] = _dump_pricing(spec.pricing)
    payload["architecture"] = spec.architecture.model_dump()
    payload["supported_parameters"] = spec.supported_parameters
    if spec.open_weights is not None:
        payload["open_weights"] = spec.open_weights
    if spec.license is not None:
        payload["license"] = spec.license
    if spec.links:
        payload["links"] = dict(spec.links)
    payload["endpoints"] = [_dump_endpoint(endpoint) for endpoint in spec.endpoints]
    return payload


class ModelCatalog:
    """In-memory model catalog loaded from a bundled JSON snapshot.

    Args:
        path: Optional path to a catalog JSON file. Defaults to the bundled snapshot.

    Examples:
        >>> catalog = ModelCatalog()
        >>> len(catalog.models()) > 0
        True
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        entries: Iterable[ModelSpec | Mapping[str, Any]] = (),
        include_bundled: bool = True,
    ) -> None:
        self._models: dict[str, ModelSpec] = {}
        self._updated_at: str | None = None
        if path is not None:
            self.load_path(Path(path))
        elif include_bundled:
            self.load_bundled()
        self.add(*entries)

    def add(self, *entries: ModelSpec | Mapping[str, Any]) -> ModelCatalog:
        """Add explicit project entries and return this effective catalog.

        Project entries replace bundled entries with the same stable model ID.
        The catalog is intentionally passed explicitly; no process-global
        registration is performed.

        Returns:
            This catalog, for convenient construction.
        """
        for entry in entries:
            spec = entry if isinstance(entry, ModelSpec) else ModelSpec.model_validate(entry)
            self._models[spec.id] = spec.model_copy(deep=True)
        return self

    def with_entries(self, *entries: ModelSpec | Mapping[str, Any]) -> ModelCatalog:
        """Return an independent catalog extended with project entries.

        Returns:
            A copy containing the effective bundled and project entries.
        """
        catalog = ModelCatalog(include_bundled=False)
        catalog._updated_at = self._updated_at
        catalog._models = {
            model_id: spec.model_copy(deep=True) for model_id, spec in self._models.items()
        }
        return catalog.add(*entries)

    @property
    def updated_at(self) -> str | None:
        """Catalog snapshot timestamp, if known."""
        return self._updated_at

    def load_bundled(self) -> None:
        """Load the package-bundled catalog snapshot."""
        ref = resources.files("plural.catalog.data").joinpath("models.json")
        with ref.open("r", encoding="utf-8") as fh:
            self._load_payload(json.load(fh))

    def load_path(self, path: Path) -> None:
        """Load a catalog from a filesystem path.

        Args:
            path: Path to a JSON catalog file.
        """
        with path.open("r", encoding="utf-8") as fh:
            self._load_payload(json.load(fh))

    def _load_payload(self, payload: dict[str, Any]) -> None:
        self._updated_at = payload.get("updated_at")
        models: dict[str, ModelSpec] = {}
        for item in payload.get("models") or []:
            spec = spec_from_payload(item)
            models[spec.id] = spec
        self._models = models

    def models(self) -> list[ModelSpec]:
        """Return all model specs.

        Returns:
            A list of :class:`ModelSpec` entries.
        """
        return list(self._models.values())

    def ids(self) -> list[str]:
        """Return registered model IDs in catalog order."""
        return [spec.id for spec in self._models.values()]

    def suggest(self, model_id: str, *, limit: int = 5) -> list[str]:
        """Return nearby catalog IDs for an unknown model.

        Args:
            model_id: The ID the caller tried to use.
            limit: Maximum suggestions.

        Returns:
            Close catalog IDs, or a short prefix of the catalog.
        """
        import difflib

        known = self.ids()
        close = difflib.get_close_matches(model_id, known, n=limit, cutoff=0.4)
        if close:
            return close
        needle = model_id.lower()
        contains = [item for item in known if needle in item.lower() or item.lower() in needle]
        return contains[:limit] or known[:limit]

    def get(self, model_id: str) -> ModelSpec | None:
        """Look up a model by id.

        Args:
            model_id: Model id in ``author/slug`` form.

        Returns:
            The matching :class:`ModelSpec`, or ``None``.
        """
        return self._models.get(model_id)

    def require(self, model_id: str) -> ModelSpec:
        """Look up a model by id or raise.

        Args:
            model_id: Model id in ``author/slug`` form.

        Returns:
            The matching :class:`ModelSpec`.

        Raises:
            NotFoundError: If the model is not in the catalog.
        """
        spec = self.get(model_id)
        if spec is None:
            raise NotFoundError(f"model not found in catalog: {model_id}", model=model_id)
        return spec

    def refresh_from_openrouter(self, url: str = "https://openrouter.ai/api/v1/models") -> int:
        """Refresh the in-memory catalog from OpenRouter's public models API.

        Args:
            url: Models endpoint URL.

        Returns:
            Number of models loaded.

        Note:
            This performs a network request and is intended for maintainer
            tooling, not runtime hot paths.
        """
        import httpx

        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        models = []
        for item in data.get("data") or []:
            models.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "context_length": item.get("context_length"),
                    "pricing": item.get("pricing"),
                    "architecture": item.get("architecture"),
                    "supported_parameters": item.get("supported_parameters"),
                }
            )
        self._load_payload({"updated_at": None, "models": models})
        return len(models)

    def write_snapshot(self, path: Path) -> None:
        """Write the current catalog to a JSON snapshot file.

        Args:
            path: Destination path.
        """
        payload = {
            "updated_at": self._updated_at,
            "models": [spec_to_payload(spec) for spec in self.models()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
