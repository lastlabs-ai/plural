# Quickstart

Get a multi-provider chat call in under a minute.

## Install

```bash
pip install plural
```

## Set your API key

```bash
export PLURAL_API_KEY=plural-...
```

## Primary: one plural API key

Looks like the OpenAI SDK — construct a client, call `chat`, close when done.
`Client()` reads `PLURAL_API_KEY` from the environment automatically:

```python
from plural import Client, Message

client = Client()
assert client.is_authenticated()

response = client.chat(
    model="openai/gpt-4o-mini",
    messages=[Message(role="user", content="Summarize plural in one sentence.")],
    models=["anthropic/claude-sonnet-4"],  # optional fallback chain
)
print(response.text)
print(response.usage.cost)
client.close()
```

Traces append to `.plural/traces.jsonl` by default.

## Tracing style

Use a context manager when you want explicit lifecycle + content capture:

```python
from plural import Client, Message
from plural.tracing import JSONLSink

with Client(sink=JSONLSink(".plural/traces.jsonl"), capture_content=True) as client:
    response = client.chat(
        model="anthropic/claude-sonnet-4",
        messages=[Message(role="user", content="Hello")],
    )
    print(response.text)
```

## Secondary: bring your own keys (BYOK)

Pass upstream keys explicitly — they are not loaded unless you ask:

```python
import os
from plural import Client

client = Client(
    providers={
        "openai": os.environ["OPENAI_API_KEY"],
        "anthropic": os.environ["ANTHROPIC_API_KEY"],
    },
)
```

Prefer the plural API key for product traffic. See [Routing examples](guides/routing-examples.md).

## Fallback and cost-aware routing

```python
from plural import Client
from plural.routing import LeastCost

client = Client(policy=LeastCost())
```

## Push local work to a hosted project

`client.push(x)` syncs an environment, trace, or benchmark report. Agents are
created on the host instead (`client.agents.create(...)`) because they need a
model and environment binding.

```python
from plural import Environment

env = Environment(name="refund-support", version="0.1.0")
client.push(env)          # primary
env.push(client)          # alias
```

A project-scoped API key already knows the project. An account-scoped key
must pass `project=` or `PLURAL_PROJECT`. See [Push to Plural](guides/push-to-plural.md).

## Next concepts

1. [Trace](concepts/trace.md) — what got recorded
2. [Environment](concepts/environment.md) — turn tasks into scored traces
3. [Benchmark](concepts/benchmark.md) — compare models on your environment
4. [Push to Plural](guides/push-to-plural.md) — sync env, trace, and report
