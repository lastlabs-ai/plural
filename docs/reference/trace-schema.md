# Trace JSON schema

Canonical schema version: **1.0.0**

The source of truth is the serialization schema generated from the Python Pydantic model `plural.tracing.schema.Trace`. Do not hand-edit any `trace.v1.json` file.

Generate all mirrors:

```bash
uv run python scripts/generate_trace_schema.py
```

Check them without writing:

```bash
uv run python scripts/generate_trace_schema.py --check
```

The generator writes identical content to three locations:

- `src/plural/schemas/trace.v1.json` — packaged runtime resource.
- `schemas/trace.v1.json` — repository integration mirror.
- [`docs/schemas/trace.v1.json`](../schemas/trace.v1.json) — documentation mirror.

Load the installed package's canonical generated artifact without relying on a repository path:

```python
from plural.tracing import trace_json_schema

schema = trace_json_schema()
```

## Identity, lineage, and stop fields

- `trace_kind` is `production`, `episode`, or `llm_call`.
- `parent_trace_id` links a child call to its direct episode parent.
- `episode_trace_id` groups the episode and its optional child calls.
- `stop_reason` records an environment stop (`terminated`, `truncated`, `policy_stop`, or `failure`) or an LLM finish reason where applicable.

An episode trace sets `episode_trace_id == trace_id`. Linked child LLM traces set both lineage fields to that episode id.

A `Decision` includes `decision_id` and zero-based `index` in addition to observation, model context/output, parsed actions, tool calls, reward events, and timestamp. Valid step variants remain `decision`, `llm`, `tool`, and `event`.

Stability policy:

- Additive fields may appear in `1.x` without a major bump.
- Removing or renaming fields requires a major version.
- Consumers should ignore unknown fields.
