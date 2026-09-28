---
route: /docs/sdk/client
title: "Model calls, routing, and responses"
order: 460
description: "Send a prompt to any catalog model from Python with one Plural API key, stream the answer, ask for structured JSON, choose models, and handle errors."
audience: all
nav: false
---
# Model calls, routing, and responses

Sometimes you just want to ask a model a question from your own code, without setting
up an Environment or a Task. `Client` does that. It sends your message to any model in
the [catalog](https://pluralintel.com/models) and hands back the answer, using one
Plural API key for every provider.

This page is for Python developers. Complete [authentication](../getting-started.md)
first. These examples make live model calls, which cost money; use model IDs
supported by your configured endpoint.

## Make and inspect a call

The smallest useful call sends one message and prints the reply:

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

`response.text` is the answer. `response.model` and `response.usage` tell you which
model answered and how many tokens it used. `tags` label the call so you can find it
later.

More detail for power users:

- Messages may also be dictionaries.
- `ChatResponse` exposes choices, normalized usage, text, and the provider's raw
  response. Prefer the normalized fields when you work across providers.
- `Client` is also exported as `Plural`.
- The context manager closes clients and flushes traces. For a long-lived service,
  reuse a client and call `close()` on shutdown; `flush()` drains trace writes
  without closing it.
- Content capture is off by default. Use `capture_content=True` only when you intend
  to retain prompt and response content.

## Stream an answer

Streaming prints the answer as it is written, instead of waiting for all of it:

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

In async code, use `achat` and `astream`:

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
`asyncio.run(main())`. Hosted object helpers are synchronous even when used alongside
`achat`.

## Tools and structured answers

> **Good to know:** A raw `client.chat(..., tools=...)` call declares tools; it does
> **not** execute their implementations.

The model can ask for a tool, but your code has to run it. Use the
[support queue tutorial](../tutorials/support-queue.md) for an automatic tool loop, or
dispatch returned tool calls yourself and append tool-result messages with matching
call IDs.

To get a typed JSON answer instead of free text, pass a JSON Schema:

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

Provider translations, tool-call stream assembly, and reasoning fields are explained
in [providers and integrations](../reference/integrations.md). Supported combinations
vary; a normalized API does not make unsupported model features available.

## Choose models and routing behavior

To see which models exist and what they cost, read the bundled catalog:

```python
from plural import ModelCatalog

catalog = ModelCatalog()
print("Snapshot:", catalog.updated_at)
for model in catalog.models()[:5]:
    print(model.id, model.context_length)
```

The catalog is bundled metadata, not a live list of the models your account can use.
`catalog.get(id)` returns an entry or `None`. `estimate_cost(usage, spec)` uses that
entry's pricing and is an estimate, not a provider invoice.

**Routing** means letting Plural pick which model or host answers a call:

- For availability-oriented application traffic, `models=[...]` supplies fallback
  candidates alongside the primary `model`.
- `Client(policy=LeastCost())`, with `LeastCost` imported from `plural.routing`,
  chooses by the routing policy.
- See [providers and integrations](../reference/integrations.md) for ordered
  fallbacks, custom policies, and host selection.

> **Tip:** For a strict model evaluation, avoid fallback chains. A fallback measures a
> routing configuration rather than a single model. Inspect actual model and attempt
> information when comparing results.

`Client(max_retries=...)` configures request retries. `max_cost_usd` is the router's
estimated per-request cost guard, not a benchmark-wide spending account or an
independent meter for external harnesses. Package limits are documented
[separately](../reference/definitions.md).

## Handle errors

A failed model call raises a subclass of `PluralError`, such as
`AuthenticationError` or `RateLimitError`. `is_retryable` tells you whether trying
again could help:

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

Do not blindly retry authentication, schema, or permission errors. For custom
providers, Azure, Bedrock, and OpenTelemetry, continue through the
[feature guide](../reference/feature-map.md).
