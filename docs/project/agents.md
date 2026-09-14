---
route: /docs/project/agents
title: "Agents"
order: 60
description: "Create catalog-backed Agents with instructions, provider validation, and an optional custom Harness."
audience: all
nav: true
nav_group: Build
outcome: You can create bundled and project-catalog Agents without global registration.
---
# Agents

An Agent owns a catalog model ID, instructions, optional provider preference,
and at most one optional Harness. It does not own a Task or Environment.

```python
from plural import Agent

agent = Agent(
    model="openai/gpt-5.6-luna",
    name="careful",
    version="1.0.0",
    instructions="Use the available actions and be concise.",
    secret_names=("OPENAI_API_KEY",),
)
```

`name` defaults to the final segment of `model`; `version` defaults to `0.1.0`.
Optional fields include `provider`, `fallback_models`, `temperature`,
`max_tokens`, `auth_mode`, `secret_names`, `metadata`, and `harness`.
Every `secret_names` grant must be declared by the selected Harness; execution
fails closed before forwarding an undeclared name.

Models are stable IDs in the effective `ModelCatalog`. Bundled models and
provider preferences validate at construction. Project entries use an explicit
context:

```python
from plural import CatalogContext, ModelCatalog, ModelSpec
from plural.catalog import ModelEndpoint

catalog = ModelCatalog(
    entries=[
        ModelSpec(
            id="project/support-model",
            endpoints=[
                ModelEndpoint(
                    provider="project-gateway",
                    upstream_id="support-model-v2",
                )
            ],
        )
    ]
)
context = CatalogContext(catalog)
agent = context.agent(
    model="project/support-model",
    provider="project-gateway",
)
```

Register custom models and at least one reachable endpoint explicitly; do not
copy an invented model ID into a Job. CLI commands accept `--catalog PATH`.
Planning records both the catalog ID and resolved upstream ID in the lock and
Trial receipt. A package Job reaches that endpoint through
`OPENAI_BASE_URL` or `PLURAL_GATEWAY_URL`; the endpoint must implement
OpenAI-compatible `POST /chat/completions`.

With Plural Gateway, the native runner sends the catalog ID. With a direct
`OPENAI_BASE_URL` or default OpenAI call, it sends the resolved `upstream_id`.
The model-specific adapters used by `Client` are a separate API. Job does not
directly execute Anthropic, Google, Bedrock, or Azure native protocols.

A fallback chain evaluates a routing configuration, not one model. Avoid
fallbacks when comparing individual models. After a trustworthy evaluation,
quality, cost, and latency evidence can inform application routing through
`Client`; keep the actual model resolution visible.

For a custom interaction loop, attach one plain Harness:

```python
from plural import Agent, Harness

harness = Harness(
    name="support-loop",
    command=["python", "harness.py"],
    source="harness",
)
agent = Agent(model="openai/gpt-5.6-luna", harness=harness)
```

Changing model, instructions, routing fields, secret grants, metadata, Harness,
or Harness source digest changes the Agent hash. Publish a new version instead
of rewriting an Agent already used in a Job.

See [Harnesses](harnesses.md) for capability grants, outputs, artifacts, and
TITO.
