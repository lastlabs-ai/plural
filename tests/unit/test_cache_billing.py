from decimal import Decimal
from typing import Any

import pytest

from plural.catalog import estimate_cost
from plural.catalog.billing import PriceRates, charge, charge_usage
from plural.catalog.edit import validate_document
from plural.catalog.models import ModelPricing, ModelSpec, PriceTier
from plural.catalog.sync import parse_endpoints
from plural.providers.anthropic import _cache_counts
from plural.providers.bedrock import BedrockProvider
from plural.providers.google import _gemini_usage
from plural.providers.openai_compatible import _openai_usage
from plural.providers.openai_responses import _usage as responses_usage
from plural.types import Usage

M = Decimal(1_000_000)
SONNET = PriceRates.of("0.000003", "0.000015", "0.0000003", "0.00000375")


def per_million(value: str) -> Decimal:
    return Decimal(value) / M


def test_cached_tokens_are_a_subset_of_the_prompt() -> None:
    usage = Usage.from_counts(1_000, 10, cache_read_tokens=5_000, cache_write_tokens=5_000)
    assert usage.cache_read_tokens == 1_000
    assert usage.cache_write_tokens == 0


def test_declared_cache_prices_are_used() -> None:
    result = charge(
        SONNET,
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cache_read_tokens=600_000,
        cache_write_tokens=200_000,
    )
    assert result.prompt_usd == Decimal("0.6")
    assert result.cache_read_usd == Decimal("0.18")
    assert result.cache_write_usd == Decimal("0.75")
    assert result.total_usd == Decimal("1.53")


def test_undeclared_cache_prices_never_bill_below_list() -> None:
    rates = PriceRates.of("0.000002", "0.000008")
    read_only = charge(rates, prompt_tokens=1_000, completion_tokens=0, cache_read_tokens=1_000)
    uncached = charge(rates, prompt_tokens=1_000, completion_tokens=0)
    assert read_only.total_usd == uncached.total_usd

    written = charge(rates, prompt_tokens=1_000, completion_tokens=0, cache_write_tokens=1_000)
    assert written.total_usd == uncached.total_usd * Decimal("1.25")


def test_one_hour_cache_writes_bill_at_least_double_the_prompt() -> None:
    result = charge(
        SONNET,
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cache_write_tokens=1_000_000,
        cache_write_long_tokens=1_000_000,
    )
    assert result.cache_write_usd == Decimal("6")


def test_long_prompt_tier_scales_cache_rates() -> None:
    pricing = ModelPricing(
        prompt=0.000003,
        completion=0.000015,
        cache_read=0.0000003,
        cache_write=0.00000375,
        tiers=[PriceTier(min_prompt_tokens=200_000, prompt=0.000006, completion=0.0000225)],
    )
    short = pricing.rates_at(100_000)
    long = pricing.rates_at(300_000)
    assert short.cache_read == per_million("0.3")
    assert long.prompt == per_million("6")
    assert long.cache_read == per_million("0.6")
    assert long.cache_write == per_million("7.5")


def test_estimate_cost_charges_cache_tokens() -> None:
    spec = ModelSpec(
        id="anthropic/test",
        provider="anthropic",
        context_length=200_000,
        pricing=ModelPricing(
            prompt=0.000003, completion=0.000015, cache_read=0.0000003, cache_write=0.00000375
        ),
    )
    usage = Usage.from_counts(1_000_000, 0, cache_read_tokens=1_000_000)
    assert estimate_cost(usage, spec) == pytest.approx(0.3)
    assert float(charge_usage(SONNET, usage).total_usd) == pytest.approx(0.3)


def test_anthropic_counts_cached_input_back_into_the_prompt() -> None:
    raw: dict[str, Any] = {
        "input_tokens": 10,
        "cache_read_input_tokens": 1_000,
        "cache_creation_input_tokens": 500,
        "cache_creation": {"ephemeral_5m_input_tokens": 200, "ephemeral_1h_input_tokens": 300},
    }
    assert _cache_counts(raw) == (1_000, 500, 300)


def test_bedrock_counts_cached_input_back_into_the_prompt() -> None:
    usage = BedrockProvider._usage(
        object(),  # type: ignore[arg-type]
        {
            "inputTokens": 10,
            "outputTokens": 5,
            "cacheReadInputTokens": 1_000,
            "cacheWriteInputTokens": 500,
        },
    )
    assert usage.prompt_tokens == 1_510
    assert usage.cache_read_tokens == 1_000
    assert usage.cache_write_tokens == 500


def test_gemini_bills_thinking_and_reports_cache_reads() -> None:
    usage = _gemini_usage(
        {
            "promptTokenCount": 1_000,
            "candidatesTokenCount": 100,
            "thoughtsTokenCount": 400,
            "cachedContentTokenCount": 800,
        }
    )
    assert usage.prompt_tokens == 1_000
    assert usage.completion_tokens == 500
    assert usage.cache_read_tokens == 800


def test_openai_shapes_report_cached_prompt_tokens() -> None:
    chat = _openai_usage(
        {
            "prompt_tokens": 1_000,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 600},
        }
    )
    assert (chat.prompt_tokens, chat.cache_read_tokens) == (1_000, 600)

    deepseek = _openai_usage(
        {"prompt_tokens": 1_000, "completion_tokens": 10, "prompt_cache_hit_tokens": 700}
    )
    assert deepseek.cache_read_tokens == 700

    responses = responses_usage(
        {"input_tokens": 1_000, "output_tokens": 10, "input_tokens_details": {"cached_tokens": 900}}
    )
    assert responses is not None
    assert responses.cache_read_tokens == 900


def test_parse_endpoints_records_undiscounted_cache_prices() -> None:
    payload = {
        "data": {
            "id": "anthropic/claude-test",
            "endpoints": [
                {
                    "name": "Anthropic | anthropic/claude-test",
                    "tag": "anthropic",
                    "pricing": {
                        "prompt": "0.0000015",
                        "completion": "0.0000075",
                        "input_cache_read": "0.00000015",
                        "input_cache_write": "0.000001875",
                        "discount": 0.5,
                    },
                }
            ],
        }
    }
    (host,) = parse_endpoints(payload)
    assert host.cache_read == pytest.approx(3e-7)
    assert host.cache_write == pytest.approx(3.75e-6)


def _document(pricing: dict[str, str], provider: str = "anthropic") -> dict[str, Any]:
    return {
        "updated_at": None,
        "models": [
            {
                "id": f"{provider}/m",
                "name": "M",
                "description": "A model.",
                "created": "2026-09-01",
                "context_length": 1000,
                "pricing": pricing,
                "endpoints": [
                    {"provider": provider, "region": "us", "upstream_id": "m", "pricing": pricing}
                ],
            }
        ],
    }


def test_validation_rejects_impossible_cache_prices() -> None:
    base = {"prompt": "0.000001", "completion": "0.000002"}
    cheap_write = validate_document(
        _document({**base, "cache_read": "0.0000001", "cache_write": "0.0000005"})
    )
    assert any("cache write" in issue.message for issue in cheap_write if issue.level == "error")

    costly_read = validate_document(
        _document({**base, "cache_read": "0.000002", "cache_write": "0.00000125"})
    )
    assert any(issue.level == "error" and "cache_read" in issue.path for issue in costly_read)


def test_validation_requires_a_write_price_where_writes_cost_extra() -> None:
    base = {"prompt": "0.000001", "completion": "0.000002", "cache_read": "0.0000001"}
    issues = validate_document(_document(base))
    assert any(issue.level == "error" and "cache_write" in issue.message for issue in issues)
    assert not [
        issue for issue in validate_document(_document(base, "fireworks")) if issue.level == "error"
    ]
