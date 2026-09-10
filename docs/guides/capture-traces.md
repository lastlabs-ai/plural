---
route: /docs/guides/capture-traces
title: "Capture traces from an existing app"
order: 340
description: "Configure credentials using setup, then wrap the call your application already makes. This example uses synthetic data and SQLite so a later review can update the stored trace."
audience: all
---
# Capture traces from an existing app

Configure credentials using [setup](../getting-started/setup.md), then wrap the
call your application already makes. This example uses synthetic data and
SQLite so a later review can update the stored trace.

```python
from plural import Client, Message, SQLiteSink

client = Client(
    sink=SQLiteSink("app-traces.db"),
    capture_content=True,
    tags={"service": "checkout-bot"},
)

def ask(prompt: str):
    response = client.chat(
        model="openai/gpt-4o-mini",
        messages=[Message(role="user", content=prompt)],
    )
    return response.text or "", response.raw["plural_trace_id"]

try:
    answer, trace_id = ask("Write a one-sentence order confirmation.")
    print(answer)
    client.flush()
    # Add only after an actual reviewer supplies this assessment:
    client.label(trace_id, reward=1.0, feedback="helpful")
finally:
    client.close()
```

In a service, reuse the client and close it at application shutdown. Keep the
trace ID alongside the answer so human feedback can reference the right record.
Content capture is off by default; configure [redaction](redact-pii.md) before
retaining real customer data. JSONL is append-only and cannot update an existing
record in place when a late label arrives.

To store an existing local `Trace` on Plural Intel, call `client.create(trace)`.
That is an explicit hosted write, separate from local tracing. See the
[trace and dataset walkthrough](../tutorials/traces-and-datasets.md) for reading,
filtering, saving, and uploading traces.
