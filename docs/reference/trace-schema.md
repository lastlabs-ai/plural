# Trace JSON schema

Canonical schema version: **2.0.0**

The source of truth is the serialization schema generated from
`plural.tracing.schema.Trace`. Do not hand-edit any `trace.v2.json` file.

```bash
uv run python scripts/generate_trace_schema.py
uv run python scripts/generate_trace_schema.py --check
```

The generator writes identical content to:

- `src/plural/schemas/trace.v2.json` — packaged runtime resource
- `schemas/trace.v2.json` — repository integration mirror
- [`docs/schemas/trace.v2.json`](../schemas/trace.v2.json) — documentation mirror

```python
from plural.tracing import trace_json_schema

schema = trace_json_schema()
```

## Identity and lineage

- `trace_kind` is `production`, `episode`, or `llm_call`.
- `parent_trace_id` links a child call to its episode parent.
- `episode_trace_id` groups the episode and optional child calls.
- `stop_reason` records an environment stop or an LLM finish reason.

A `Turn` includes `turn_id`, zero-based `turn`, `reasoning`, `actions`,
reward events, and `started_at` / `ended_at`. Valid step variants are
`turn`, `llm`, `action`, and `event`.

Stability policy:

- Additive fields may appear in `2.x` without a major bump.
- Removing or renaming fields requires a major version.
- Consumers should ignore unknown fields.
- There is no v1 reader.
