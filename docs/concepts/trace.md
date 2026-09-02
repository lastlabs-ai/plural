# Trace

A `Trace` is the canonical record for production LLM traffic and environment episodes. `trace_kind` identifies which record it is:

| `trace_kind` | Meaning |
| --- | --- |
| `production` | A normal client call with no supplied episode lineage |
| `episode` | One complete environment episode |
| `llm_call` | An optionally persisted model call linked to an episode |

`client.push(trace)` ingests a local `Trace` into the hosted project. Agents
are not pushed; they are created on the host. See [Push to Plural](../guides/push-to-plural.md).

## One episode trace by default

`Environment.rollout(...)` persists exactly one `episode` trace by default. Model requests and outputs live inside its `Decision` steps. Set `record_llm_traces=True` only when separate model-call records are needed; those additional traces use `trace_kind="llm_call"`.

Lineage is explicit:

- An episode sets `episode_trace_id` to its own `trace_id`.
- A child LLM trace sets both `parent_trace_id` and `episode_trace_id` to the episode trace id.
- `TraceContext` carries these ids into `client.chat`, `achat`, `stream`, and `astream`.

## Episode anatomy

| Field | Meaning |
| --- | --- |
| `trace_id`, `trace_kind` | Stable record identity and kind |
| `parent_trace_id`, `episode_trace_id` | Parent/episode lineage |
| `environment`, `environment_version`, `environment_fingerprint` | Environment compatibility identity |
| `task_id`, `model` | Task and policy target |
| `initial_state`, `final_state` | Explicitly trace-safe snapshots, or `null` |
| `steps` | `Decision`, `LLMCall`, `ToolCallStep`, or `Event` records |
| `outcome` | Scorer outputs, episode reward, labels, and feedback |
| `metrics` | Episode-total turns, decision/tool counts, model cost, and latency |
| `terminated`, `truncated`, `stop_reason` | Final stop state |
| `failed` | Whether policy, step, scoring, or an explicit failure stop failed the episode |
| `schema_version` | Serialization compatibility version |

`stop_reason` distinguishes `terminated`, `truncated`, `policy_stop`, and `failure` for environment traces. Production and child LLM traces may use provider finish reasons instead.

## Decisions

One `Decision` is one policy turn and may contain several tool calls. It includes:

- `decision_id`: a stable opaque id.
- `index`: the zero-based episode turn.
- `observation` and `model_context`: what the policy saw.
- `model_output` and `parsed_action`: what it chose.
- `tool_calls` and `reward_events`: execution results and step rewards.
- `timestamp`: when the decision was recorded.

Text-only model responses are represented as a parsed `respond` action, so they remain visible even when no tool was called.

## Rewards, transitions, and returns

Choose reward alignment explicitly when flattening an episode:

```python
trace.transitions(source="outcome")  # final scorer reward on the last decision
trace.transitions(source="events")   # Decision.reward_events only
trace.transitions(source="both")     # both sources
```

The same `source` values apply to `decision_rewards()` and `returns()`. The default is `source="outcome"`. `transitions()` aligns each decision with its observation, parsed actions, selected reward, next observation, and final `terminated` / `truncated` flags.

## Content capture and redaction

`Client(capture_content=False)` is the default. Its drop-content redactor covers:

- LLM request messages and response message content.
- Environment task `input` in `metadata["task"]`.
- `initial_state` and `final_state`.
- Decision `observation`, request messages in `model_context`, and response content in `model_output`.
- Text returned through `ParsedAction(name="respond", ...)`.

Tool arguments/results, arbitrary metadata, and custom nested strings can still contain sensitive data; add field or pattern rules as needed. Environment snapshots must be trace-safe before redaction. See [Redact PII](../guides/redact-pii.md).

Redaction metadata is also a replay boundary: deterministic replay rejects a trace marked as redacted rather than executing incomplete actions or state.

## Loading v0.4 traces

`Trace.model_validate(...)` and `Trace.model_validate_json(...)` migrate legacy v0.4/pre-1.0 records that do not have `trace_kind`. Environment fields or decision steps imply `trace_kind="episode"`; other records become `production`. Episode lineage is inferred from the trace id, and missing decision indexes and ids are generated deterministically from `(trace_id, decision position)`. Newly created decisions still receive fresh opaque ids.

## Canonical schema

The Python `Trace` Pydantic model is the source of truth. The generated Draft 2020-12 JSON Schema is packaged with plural and available through `trace_json_schema()`. See the [schema reference](../reference/trace-schema.md); do not hand-edit generated schema mirrors.

Traces land in a [Sink](sink.md). Collections of rollout or production traces become a [Dataset / TraceDataset](dataset.md); benchmark inputs are `TaskDataset` values.
