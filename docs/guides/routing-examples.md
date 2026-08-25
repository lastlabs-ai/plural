# Routing examples walkthrough

Cookbook-style scripts under [`examples/routing/`](https://github.com/lastlabs-ai/plural/tree/main/examples/routing).

```bash
export PLURAL_API_KEY=plural-...
```

## Layout

| Path | Purpose |
| --- | --- |
| `routing/quickstart/` | First call — `basic.py` and `with_tracing.py` |
| `routing/catalog/` | List available model ids |
| `routing/models/<provider>/` | OpenAI, Anthropic, Google, Fireworks |
| `routing/custom/` | Your own OpenAI-compatible endpoint |
| `routing/byok/` | Bring-your-own upstream keys (secondary) |

## Simple (default)

```python
from plural import Plural, Message

client = Plural()

response = client.chat(
    model="openai/gpt-4o-mini",
    messages=[Message(role="user", content="Hello")],
)
print(response.text)
client.close()
```

## Tracing

```python
from plural.tracing import JSONLSink

with Plural(
    sink=JSONLSink(".plural/examples/traces.jsonl"),
    capture_content=True,
) as client:
    response = client.chat(...)
```

## Walkthrough

```bash
export PLURAL_API_KEY=plural-...

uv run python examples/routing/quickstart/basic.py
uv run python examples/routing/quickstart/with_tracing.py

uv run python examples/routing/catalog/list_models.py

uv run python examples/routing/models/openai/basic.py
uv run python examples/routing/models/anthropic/basic.py
uv run python examples/routing/models/google/basic.py
uv run python examples/routing/models/fireworks/basic.py

export CUSTOM_BASE_URL=http://127.0.0.1:8000/v1
export CUSTOM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
uv run python examples/routing/custom/basic.py

export OPENAI_API_KEY=sk-...
uv run python examples/routing/byok/openai.py
```

## Next

- [Routing policy](../concepts/routing.md)
- [Capture traces](capture-traces.md)
