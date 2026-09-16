---
route: /docs/sdk/client
title: "Model calls, routing, and responses"
order: 460
description: "Use Client when you need a model response without creating an environment. Complete authentication first. These examples make live model calls; use IDs supported by your configured endpoint."
audience: all
nav: false
---
# Model calls, routing, and responses

Use `Client` when you need a model response without creating an environment.
Complete [authentication](../getting-started.md) first. These examples
make live model calls; use IDs supported by your configured endpoint.

## Make and inspect a call

```python
from plural import Client, Message

with Client() as client:
    response = client.chat(
        model="openai/gpt-4o-mini",
        messages=[Message(role="user", content="Summarize: order A100 shipped today.")],
        temperature=0,
        max_tokens=100,
        tags={"workflow": "support-summary"},
    )
    print(response.text)
    print(response.model, response.usage)
    print(response.raw["plural_trace_id"])
```

Messages may also be dictionaries. `ChatResponse` exposes choices, normalized
usage, text, and the provider's raw response. Prefer normalized fields across
providers. `Client` is also exported as `Plural`.

The context manager closes clients and flushes traces. For a long-lived service,
reuse a client and call `close()` on shutdown; `flush()` drains trace writes
without closing it. Content capture is off by default. Use
`capture_content=True` only when you intend to retain prompt/response content.

## Stream an answer

```python
from plural import Client, Message

with Client() as client:
    for chunk in client.stream(
        model="openai/gpt-4o-mini",
        messages=[Message(role="user", content="Write a short shipping update.")],
    ):
        if chunk.delta.content:
            print(chunk.delta.content, end="", flush=True)
    print()
```

Consume the stream to completion to receive final usage and normal completion
handling. For an OpenAI-compatible downstream client, serialize with
`chunk.to_openai()` rather than forwarding host-native `chunk.raw`.

## Async calls and streams

```python
import asyncio
from plural import Client, Message

async def main():
    client = Client()
    try:
        response = await client.achat(
            model="openai/gpt-4o-mini",
            messages=[Message(role="user", content="Say hello.")],
        )
        print(response.text)
        async for chunk in client.astream(
            model="openai/gpt-4o-mini",
            messages=[Message(role="user", content="Say goodbye.")],
        ):
            print(chunk.delta.content or "", end="")
    finally:
        await client.aclose()

asyncio.run(main())
```

In a notebook that already has an event loop, use `await main()` instead of
`asyncio.run(main())`. Hosted object helpers are synchronous even when used
alongside `achat`.

## Tools and structured answers

A raw `client.chat(..., tools=...)` call declares tools; it does **not** execute
their implementations. Use the [environment walkthrough](../tutorials/sdk-walkthrough.md)
for an automatic tool loop, or dispatch returned tool calls yourself and append
tool-result messages with matching call IDs.

For a typed JSON response:

```python
import json
from plural import Client, Message
from plural.types import ResponseFormat

schema = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
}
with Client() as client:
    response = client.chat(
        model="openai/gpt-4o-mini",
        messages=[Message(role="user", content="Order A100 has shipped. Extract its status.")],
        response_format=ResponseFormat(
            type="json_schema", json_schema={"name": "order_status", "schema": schema},
        ),
    )
    print(json.loads(response.text))
```

Provider translations, tool-call stream assembly, and reasoning fields are
explained in [capabilities](../guides/capabilities.md). Supported combinations
vary; a normalized API does not make unsupported model features available.

## Choose models and routing behavior

```python
from plural import ModelCatalog

catalog = ModelCatalog()
print("Snapshot:", catalog.updated_at)
for model in catalog.models()[:5]:
    print(model.id, model.context_length)
```

The catalog is bundled metadata, not a live list of the models your account can
use. `catalog.get(id)` returns an entry or `None`; `estimate_cost(usage, spec)`
uses that entry's pricing and is an estimate, not a provider invoice.

For availability-oriented application traffic, `models=[...]` supplies fallback
candidates alongside the primary `model`. `Client(policy=LeastCost())`, with
`LeastCost` imported from `plural.routing`, chooses by the routing policy.
See [routing](../concepts/routing.md) and [provider examples](../guides/routing-examples.md)
for ordered fallbacks, custom policies, and host selection.

For a strict model evaluation, avoid fallback chains: a fallback measures a
routing configuration rather than a single model. Inspect actual model and
attempt information when comparing results.

`Client(max_retries=...)` configures request retries. `max_cost_usd` is the
router's estimated per-request cost guard, not a benchmark-wide spending account or an
independent meter for external harnesses. Package limits are documented
[separately](../reference/definitions.md).

## Handle errors

```python
from plural import AuthenticationError, Client, Message, PluralError, is_retryable

try:
    with Client() as client:
        client.chat(model="openai/gpt-4o-mini", messages=[Message(role="user", content="Hello")])
except AuthenticationError:
    print("Check the credential and endpoint for this provider.")
except PluralError as exc:
    print(type(exc).__name__, "retryable:", is_retryable(exc))
```

Do not blindly retry authentication, schema, or permission errors.
For custom providers, Azure, Bedrock, and OpenTelemetry, continue through the
[feature guide](../reference/feature-map.md).
