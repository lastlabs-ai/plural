---
route: /docs/guides/redact-pii
title: "Redact PII before anything hits disk"
order: 360
description: "Client(capturecontent=False) is the default. When no custom redactor is supplied, the client installs Redactor(dropcontent=True) before its sink."
audience: all
---
# Redact PII before anything hits disk

`Client(capture_content=False)` is the default. When no custom redactor is supplied, the client installs `Redactor(drop_content=True)` before its sink.

For environment episode traces, that default content drop covers:

- `metadata["task"]["input"]`;
- `initial_state` and `final_state`;
- each decision's `observation`;
- request message content in `model_context`;
- response message content in `model_output`;
- `arguments["text"]` on a decision's normalized `respond` action.

It also strips normal LLM request/response message content. Task `expected` is never copied into episode trace metadata in the first place.

Tool arguments, tool results, arbitrary metadata, tags, and other custom nested fields are not structurally removed by `drop_content`. They may need explicit field paths, regex patterns, or a callable redactor.

To retain content while scrubbing known patterns:

```python
from plural import Client, Redactor
from plural.tracing import JSONLSink

redactor = Redactor(
    fields={"metadata.email", "metadata.phone"},
    patterns=[
        r"\b\d{3}-\d{2}-\d{4}\b",          # SSN-like
        r"\b[\w.-]+@[\w.-]+\.\w+\b",     # emails in content
    ],
    drop_content=False,  # keep content but scrub patterns
)

client = Client(
    providers={"openai": "..."},
    sink=JSONLSink(".plural/traces.jsonl"),
    redactor=redactor,
    capture_content=True,
)
```

If you pass a custom redactor with `capture_content=False`, set `drop_content=True` on that redactor to preserve the default structural content drop for episode traces:

```python
redactor = Redactor(
    drop_content=True,
    fields={"metadata.customer_id"},
    patterns=[r"\b[\w.-]+@[\w.-]+\.\w+\b"],
)
client = Client(redactor=redactor, capture_content=False)
```

Redaction is defense in depth, not permission to serialize arbitrary state. `Environment.snapshot()` defaults to `None`; if you override it, return an explicitly trace-safe representation that excludes secrets and unnecessary personal data. Test the final redacted `Trace` shape before enabling persistence in production.

`replay_actions()` and `verify_replay()` reject traces marked as redacted. Replay requires the original actions, observations, task input, and relevant state rather than redacted substitutes.
