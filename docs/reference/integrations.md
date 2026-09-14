---
route: /docs/reference/integrations
title: Providers and integrations
order: 230
description: Distinguish model endpoints from Runtime sandboxes and integrate Daytona, future partners, routing, tracing, CI, and Plural Intel accurately.
audience: all
nav: true
nav_group: Operations
---
# Providers and integrations

Plural uses two unrelated provider layers:

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

Register private or partner endpoints as explicit project catalog entries.
Never imply that a catalog row guarantees live access.

For evaluation, avoid fallbacks when the objective is one model. For
application routing after evaluation, `Client` supports ordered fallbacks and
routing policies. Preserve actual endpoint, cost, latency, and trace evidence.

## Built-in Runtime providers

- `local`: trusted development subprocess; no isolation.
- `docker`: local containers with the capability limits documented in
  [Runtime](../project/runtime.md).
- `daytona`: optional remote adapter installed through `plural[daytona]`.

Daytona is implemented. Blaxel is not bundled or registered. A Blaxel
team—or any future partner—can implement the plugin contract below without
being described as generally available before that package ships and passes
conformance.

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
