---
route: /docs/reference/integrations
title: Providers and integrations
order: 230
description: Configure model endpoints and Runtime providers, then use evaluation results to choose application routes.
audience: all
nav: true
nav_group: Operations
---
# Providers and integrations

An evaluation needs a model endpoint and a place to run code. Configure these separately:

- a **model provider** answers model requests;
- a **SandboxProvider** creates the Runtime where Agent and Verifier code runs.

## Model endpoints

Agents and Agent Verifiers use stable IDs from the effective `ModelCatalog`.
Catalog endpoint rows describe model resolution; they are not transport
adapters and do not guarantee live access.

Package Job native runners speak OpenAI-compatible `POST /chat/completions`.
They send the catalog ID to `PLURAL_GATEWAY_URL`, or the resolved upstream ID
to `OPENAI_BASE_URL` and default OpenAI. Anthropic, Google, Bedrock, and Azure
native APIs are not directly executed by Job.

`Client` is a separate application inference API with provider adapters for
OpenAI, Anthropic, Google, Azure, Bedrock, and OpenAI-compatible services.
Actual access depends on credentials, endpoint configuration, region, account
entitlements, and current provider availability.

For private endpoints, create a project catalog entry using the [Agents guide](../project/agents.md#find-a-model), then verify connectivity with a small Job.

## Route after evaluation

Use Benchmark results to choose which agent configuration should handle each kind of work. First set the quality requirement for that workflow, then compare cost and latency among the candidates that meet it.

For example, choose a model for routine support requests only after it meets your support Benchmark's quality threshold. Evaluate difficult or high-risk requests separately before choosing their route.

The package does not automatically turn Job scores into a learned router. Your application selects the approved candidates and routing policy. `Client` supports model selection, ordered fallbacks, and cost or latency policies. A fallback handles a failed request; it does not judge whether a successful response is correct.

Given the model ID you selected from your evaluation and your application's messages:

```python
from plural import Client

client = Client()
response = client.chat(
    model=selected_model_id,
    messages=messages,
)
```

Configure Client authentication before making the request. `selected_model_id` and `messages` are application values, not automatic outputs wired from a Benchmark. `Client.chat` routes model calls; your application must retain the instructions, tools, and Harness behavior you evaluated. It does not launch an evaluated Agent's custom Harness for you.

Track the model actually used, along with quality, cost, and latency. Re-evaluate when Tasks, models, or Harnesses change. If the available candidates miss your quality target, inspect the failures and consider [training](../running/training.md).

## Built-in Runtime providers

- `local`: trusted development subprocess; no isolation.
- `docker`: local containers with the capability limits documented in
  [Runtime](../project/environments.md#runtime).
- `daytona`: optional remote adapter installed through `plural[daytona]`.

Additional Runtime providers can be added through the extension interface below.

## Sandbox provider extensions

Subclass `SandboxProvider` and implement:

- truthful `capabilities()` and `doctor()` reports;
- fresh `create(requirements)`;
- scoped `upload_files` and exact `download_files`;
- argv-based `exec` with cwd, environment, timeout, and captured logs;
- forceful `cancel` and idempotent `destroy`.

Register in-process:

```python
from plural import ProviderRegistry
from my_partner import PartnerProvider

registry = ProviderRegistry()
registry.register(PartnerProvider())
```

Or publish an entry point:

```toml
[project.entry-points."plural.sandbox_providers"]
partner = "my_partner:PartnerProvider"
```

The base preflight compares `SandboxRequirements.required_capabilities()` with
the provider's declaration. Provider-specific preflight must also reject image
forms, network policy, compute controls, stdin, persistence, compose, or
filesystem behavior it cannot enforce. Never silently broaden network,
filesystem, or credential access.

The provider must also map to the Environment's target and fit any hosted
project policy. Plugin discovery alone is not a partner certification.

## Plural Intel, CI, and OpenTelemetry

`plural run job.yaml` is local. `plural run job.yaml --hosted` explicitly
synchronizes and submits to Plural Intel. Hosted support depends on backend
revision APIs, artifact transport, source materialization, and configured
Runtime providers.

CI should validate and dry-run the same pinned Job, then execute only when
credentials and costs are intentional.

Install `plural[otel]` to export tracing-SDK spans to an existing collector.
OpenTelemetry is an observability sink, not the Job's artifact store or a
replacement for Trial receipts.
