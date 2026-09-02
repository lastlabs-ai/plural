# Capture traces from an existing app

Swap your provider client for plural — about ten lines.

```python
from plural import Client, Message

client = Client(
    providers={"openai": os.environ["OPENAI_API_KEY"]},
    capture_content=True,
    tags={"service": "checkout-bot"},
)

def ask(prompt: str) -> str:
    resp = client.chat(
        model="openai/gpt-4o-mini",
        messages=[Message(role="user", content=prompt)],
    )
    return resp.text or ""
```

Later, when a human rates the answer:

```python
client.label(trace_id, reward=1.0, feedback="helpful")
```

`trace_id` is on `response.raw["plural_trace_id"]`.

To store a local episode or production `Trace` on the hosted project:

```python
client.create(trace)
```

See [Create and update hosted objects](push-to-plural.md).
