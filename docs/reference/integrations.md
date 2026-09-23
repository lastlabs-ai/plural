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

Agents and Agent Verifiers name models by stable IDs from a `ModelCatalog`. A
catalog entry says which upstream model an ID resolves to; it does not by
itself give you access to that model.

A Job makes every model call as an OpenAI-compatible `POST /chat/completions`.
It sends the catalog ID to `PLURAL_GATEWAY_URL`, or the resolved upstream ID to
`OPENAI_BASE_URL` or, when neither is set, to OpenAI. Anthropic, Google, Bedrock,
and Azure native APIs are not directly executed by Job; reach those models
through the Plural gateway or another OpenAI-compatible endpoint.

`Client` is a separate application inference API with provider adapters for
OpenAI, Anthropic, Google, Azure, Bedrock, and OpenAI-compatible services.
Actual access depends on credentials, endpoint configuration, region, account
entitlements, and current provider availability.

The CLI uses the bundled catalog; `plural models list` shows it, filtered by your organization's model policy when you are signed in (see the [Agents guide](../project/agents.md#find-a-model)). Signed in, the service enforces that policy for runs, reruns, and gateway calls, whatever the local catalog says. For a private endpoint, add a catalog entry in Python as shown in the [Python SDK guide](../sdk/evaluation.md#load-project-resources), pass the catalog to `Job(..., catalog=...)` or `Workspace(project, catalog=...)`, then verify connectivity with a small Job.

## Route after evaluation

Use Benchmark results to choose which agent configuration should handle each kind of work. First set the quality requirement for that workflow, then compare cost and latency among the candidates that meet it.

For example, choose a model for routine support requests only after it meets your support Benchmark's quality threshold. Evaluate difficult or high-risk requests separately before choosing their route.

Plural does not automatically turn Job scores into a learned router. Your application selects the approved candidates and routing policy. `Client` supports model selection, ordered fallbacks, and cost or latency policies. A fallback handles a failed request; it does not judge whether a successful response is correct.

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

- `local`: a trusted subprocess on your machine, not a sandbox; no isolation.
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

Or declare an entry point:

```toml
[project.entry-points."plural.sandbox_providers"]
partner = "my_partner:PartnerProvider"
```

The base preflight compares `SandboxRequirements.required_capabilities()` with
the provider's declaration. Provider-specific preflight must also reject image
forms, network policy, compute controls, stdin, persistence, compose, or
filesystem behavior it cannot enforce. Never silently broaden network,
filesystem, or credential access.

The provider must also support the Environment's execution target and fit any
hosted project policy. Registering a provider does not make it available to
hosted runs.

## Plural Intel, CI, and OpenTelemetry

`plural run` is local. `plural run ... --hosted` submits to Plural Intel using
revisions already pushed with `plural <kind> push`, and refuses to start when any
input differs from its pushed revision. Hosted runs also need Runtime providers
configured for the project. See
[Push and pull resources](../guides/studio-sync.md).

In CI, run `validate` on the resources and `plural run ... --dry-run` on the same
inputs, then execute only when credentials and costs are intentional. Use an API
key limited to the one project CI needs; store it with
`plural auth login --api-key-stdin` or set `PLURAL_API_KEY`.

Install `plural[otel]` to export tracing-SDK spans to an existing collector.
OpenTelemetry is an observability sink, not the Job's artifact store or a
replacement for Trial receipts.
