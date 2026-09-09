# Contributing to Plural

Thanks for helping. Documentation quality is part of the definition of done.

## Setup

```bash
uv sync --group dev --group docs
```

## Checks (same as CI)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/plural
uv run mypy --strict tests/typing/consumer.py
uv run pytest -m "not live"
uv run python scripts/generate_trace_schema.py --check
uv run python scripts/generate_package_schemas.py --check
uv run python scripts/generate_cli_reference.py --check
uv run python scripts/check_docs.py
uv run python scripts/run_offline_job_examples.py
uv run mkdocs build --strict
```

## Module definition of done

A change that adds a public symbol is incomplete until:

1. Google-style docstring with `Args` / `Returns` / `Raises` and a runnable `Examples:` block
2. Doctests pass (`pytest --doctest-modules`)
3. Concept or guide page updated when behavior changes
4. Example under `examples/` still runs
5. Public CLI help and checked-in reference regenerated when commands change
6. Pydantic manifests and checked-in package schemas regenerated together

Package/execution changes must also document provider enforcement, secret and
verifier boundaries, receipt trust, migration impact, and unsupported backend
or external-service behavior. Do not describe a placeholder as live.

## Tests

- `tests/unit` — pure logic, no network
- `tests/contract` — provider adapters against `respx` fixtures
- `tests/live` — real keys only; marked `@pytest.mark.live`

## Model catalog

`src/plural/catalog/data/models.json` is the source of truth for model ids,
context windows, and pass-through pricing. It is static so every rate change is
reviewable in git history.

A weekly workflow refreshes it from OpenRouter's public catalog and opens a PR
rather than pushing to `main`, because a wrong price costs real money on every
request. It uses no secrets: this repository is public, and provider keys belong
to the deployments that consume the library.

Run it yourself with:

```bash
uv run python -m plural.catalog.sync --check   # report drift, exit 1 if stale
uv run python -m plural.catalog.sync --write   # apply price changes
uv run python -m plural.catalog.sync --write --add openai/gpt-5.6-luna
uv run python -m plural.catalog.sync --write --add-host azure
```

Four rules keep the file trustworthy:

- **Prices are applied automatically.** A stale rate misbills every request, so
  drift is the one thing the job fixes on its own.
- **Prices are list prices, never promotional ones.** OpenRouter's `/models` list
  reports what a caller pays after a discount and omits the discount field, so the
  sync reads `/endpoints` and divides the discount back out. Recording a promo
  would undercharge the moment it expires, and the gap is ours.
- **Additions are deliberate.** The catalog is curated, not a mirror. New models
  are listed in the report as candidates; `--add` brings one in.
- **Removals never happen automatically.** Dropping a model breaks callers, so
  the job reports and leaves it.

A model with no price is left unpriced. Downstream gateways treat an unpriced
model as unavailable, so it stays hidden until someone fills the rate in.

Each `endpoints` entry carries its own rate, because the same model costs
different amounts on different clouds and in different regions. The model-level
price tracks the first endpoint, which is the host routing prefers, so it
advertises what we will actually pay rather than the cheapest listing anywhere.
`--add-host <provider>` pulls a cloud's regional endpoints in for every model that
offers them. An endpoint whose provider has no configured key reports unavailable
and is skipped during routing, so listing a cloud before holding credentials for
it is safe.

Two kinds of upstream endpoint are deliberately excluded from pricing:

- **Service tiers** such as `flex` and `priority` are separate products with their
  own rates and latency characteristics, so one flat number cannot represent both.
- **Quantized deployments** such as `fp8` and `fp4` are cheaper because they are
  smaller, and pricing the full-precision model from them would misrepresent it.

Models that charge more above a prompt-token threshold carry `pricing.tiers`, and
those are synced like any other rate. A tier replaces the base rate for the whole
request, matching how providers bill long context, so a 300k-token prompt is not
charged at the short-prompt price. A tier is only recorded when upstream gives
both a prompt and a completion rate for it; billing one side at the long-prompt
rate and the other at the base rate would match neither.

## Release

Tags matching `v*` publish to PyPI via Trusted Publishing.

Before tagging:

1. Run every command in **Checks (same as CI)** from a clean checkout.
2. Confirm generated Trace/package schemas and CLI reference have no drift.
3. Run offline examples and verify Docker/Daytona tests are either successful
   or explicitly reported as credential/daemon-gated.
4. Review `CHANGELOG.md`, migration notes, security boundaries, and known
   limitations against the actual implementation.
5. Build wheel/sdist and inspect that docs, examples, and packaged schemas are
   present.
6. Keep the PyPI classifier Alpha until compatibility, backend, plugin, trust,
   and hosted execution contracts justify promotion.

Downstream deployments pin a tag, so after merging a catalog PR cut a release
and bump the pinned ref where it is consumed.
