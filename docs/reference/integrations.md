---
route: /docs/reference/integrations
title: Providers and integrations
order: 230
description: How Plural reaches AI models and where it runs your code, plus how to use your results to pick a model for each kind of work in your own app.
audience: all
nav: true
nav_group: Operations
---
# Providers and integrations

Every evaluation needs two things from the outside world: **a model to answer**, and
**a place to run the code**. Plural keeps these separate, so you can change one
without touching the other.

- A **model provider** answers model requests. You reach every model through the
  Plural gateway with one Plural API key.
- A **Runtime provider** (in code, a `SandboxProvider`) creates the Runtime, the place
  where the Environment, Harness, and Verifier code runs. It might be your own
  machine, a Docker container, or a remote service.

Once your results are in, this page also covers the step after evaluation: using
those scores to decide which model handles which work in your own application.

## Model endpoints

Agents and Agent Verifiers name models by stable IDs from a `ModelCatalog`, the list
of models Plural knows about. You can browse it in the web app's model Catalog. A
catalog entry says which upstream model an ID resolves to; it does not by itself give
you access to that model.

A Job makes every model call as an OpenAI-compatible `POST /chat/completions` to
the Plural gateway at `PLURAL_GATEWAY_URL`, naming the catalog ID. The gateway
routes the call, bills it at the exact provider cost, and returns that cost and a
`plural_request_id` that links the call to its Trial. Anthropic, Google, Bedrock,
and Azure native APIs are not directly executed by Job; those models are reached
through the gateway.

`Client` is a separate application inference API with provider adapters for
OpenAI, Anthropic, Google, Azure, Bedrock, and OpenAI-compatible services.
Actual access depends on credentials, endpoint configuration, region, account
entitlements, and current provider availability.

The CLI uses the bundled catalog; `plural models list` shows it, filtered by your
organization's model policy when you are signed in (see the
[Agents guide](../project/agents.md#find-a-model)). Signed in, the service enforces
that policy for runs, reruns, and gateway calls, whatever the local catalog says.

For a private endpoint:

1. Add a catalog entry in Python as shown in the
   [Python SDK guide](../sdk/evaluation.md#load-project-resources).
2. Pass the catalog to `Job(..., catalog=...)` or `Workspace(project, catalog=...)`.
3. Verify connectivity with a small Job.

## Route after evaluation

Routing means sending each kind of work to the model that handles it best for the
price. Your Benchmark results tell you which one that is.

1. Set the quality bar for the workflow.
2. Keep only the candidates that clear it.
3. Among those, compare cost and latency.

For example, choose a model for routine support requests only after it meets your
support Benchmark's quality threshold. Evaluate difficult or high-risk requests
separately before choosing their route.

Plural does not automatically turn Job scores into a learned router. Your application
selects the approved candidates and routing policy. `Client` supports model selection,
ordered fallbacks, and cost or latency policies. A fallback handles a failed request;
it does not judge whether a successful response is correct.

Given the model ID you selected from your evaluation and your application's messages:

```python
from plural import Client

client = Client()
response = client.chat(
    model=selected_model_id,
    messages=messages,
)
```

Configure Client authentication before making the request. `selected_model_id` and
`messages` are application values, not automatic outputs wired from a Benchmark.

> **Good to know:** `Client.chat` routes model calls only. Your application must keep
> the instructions, tools, and Harness behavior you evaluated. It does not launch an
> evaluated Agent's custom Harness for you.

Track the model actually used, along with quality, cost, and latency. Re-evaluate
when Tasks, models, or Harnesses change. If the available candidates miss your
quality target, inspect the failures and consider [training](../running/training.md).

## Built-in Runtime providers

Plural ships with three places to run code:

- `local`: a trusted subprocess on your machine, not a sandbox; no isolation.
- `docker`: local containers with the capability limits documented in
  [Runtime](../project/environments.md#runtime).
- `daytona`: optional remote adapter installed through `plural[daytona]`.

Additional Runtime providers can be added through the extension interface below.

## Sandbox provider extensions

This section is for platform teams connecting Plural to their own sandbox service.

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
pushed revisions. It first pushes any input the hosted project does not hold yet,
as a new numbered revision of any resource whose files changed, and stops before
uploading anything if someone else changed that resource in the hosted project
since your checkout synced it. Hosted runs also need Runtime providers configured
for the project. See
[Push and pull resources](../guides/studio-sync.md).

In CI (automated checks that run on every change):

1. Run `validate` on the resources.
2. Run `plural run ... --dry-run` on the same inputs.
3. Execute only when credentials and costs are intentional.

Use an API key limited to the one project CI needs; store it with
`plural auth login --api-key-stdin` or set `PLURAL_API_KEY`.

Install `plural[otel]` to export tracing-SDK spans to an existing collector.
OpenTelemetry is an observability sink, not the Job's artifact store or a
replacement for Trial receipts.
