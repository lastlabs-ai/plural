---
route: /docs/tutorials/traces-and-datasets
title: "Inspect runs and build datasets"
order: 70
description: "A trace records what happened during a model call or environment episode. A task dataset contains work to evaluate. A trace dataset contains completed activity. Keep those roles separate when moving from debugging to evaluation."
audience: all
---
# Inspect runs and build datasets

A trace records what happened during a model call or environment episode.
A task dataset contains work to evaluate. A trace dataset contains completed
activity. Keep those roles separate when moving from debugging to evaluation.

## 1. Record and label a model call

This live example uses synthetic content and records it deliberately:

```python
from plural import Client, Message, SQLiteSink

with Client(sink=SQLiteSink("support-traces.db"), capture_content=True) as client:
    response = client.chat(
        model="openai/gpt-4o-mini",
        messages=[Message(role="user", content="Order A100 shipped. Write a status update.")],
        tags={"workflow": "order-support"},
    )
    trace_id = response.raw["plural_trace_id"]
    client.flush()
    # In real use, add this only after receiving the actual review.
    client.label(trace_id, reward=1.0, feedback="Reviewer accepted the status update.")
```

SQLite supports updating labels by trace ID. The default JSONL sink is
append-only and does not support persistent late-label updates. Select a sink
that fits your review workflow. Closing the client flushes queued writes.

## 2. Read episode traces

After the [SDK tutorial](sdk-walkthrough.md), load the JSONL trace file:

```python
from plural import Dataset, TraceFilter

traces = Dataset.from_sink(
    ".plural/traces.jsonl", name="support-episodes",
    filter=TraceFilter(trace_kind="episode"),
)
for trace in traces.traces:
    print(trace.trace_id, trace.stop_reason, trace.outcome)
    for turn in trace.turns():
        print(turn.turn, turn.parsed_action)
```

Inspect failed calls, action errors, stop reasons, and observations. A text
answer can finish an episode with `policy_stop`; `truncated` means the turn
budget was reached. A failed episode is not a successful low-scoring answer.

`rollout` records one episode trace by default. `record_llm_traces=True` adds
linked model-call child traces. When writing custom loops, pass lineage through
`trace_context` and avoid recording the same call twice. See [trace concepts](../concepts/trace.md).

## 3. Save traces for analysis

```python
from plural import Dataset, TraceFilter

traces = Dataset.from_sink(
    ".plural/traces.jsonl", name="support-episodes", version="1.0.0",
    filter=TraceFilter(trace_kind="episode"),
)
traces.save("data/support-episodes.jsonl")
restored = Dataset.load("data/support-episodes.jsonl")
print(len(restored), restored.content_hash)
```

`TraceDataset` is an alias for `Dataset`. You can also construct one with
`Dataset.from_traces(name, traces, version=...)`, or filter a sink with a
`where=` predicate. See [dataset integrity](../concepts/dataset.md) for hash and
manifest behavior.

## 4. Turn reviewed examples into Task revisions

Review and select useful inputs; do not use a Trace dataset as a Job source.
Build a first-class Task that pins an Environment and Verifier:

```python
from plural import TaskDefinition, WeightedVerifier

task = TaskDefinition(
    task_id="unknown-order",
    revision="1.0.0",
    instructions="Return the status for order A999.",
    info={"order_id": "A999"},
    environment=environment,
    verifiers=(WeightedVerifier(verifier=correctness),),
)
print(task.content_hash)
```

Do not treat the previous model's answer as ground truth without review. Keep
private labels in Verifier-controlled data or hidden Environment state, not
Task `info` or metadata.

## 5. Upload selected traces to Plural Intel

```python
from plural import Client, Dataset

traces = Dataset.load("data/support-episodes.jsonl")
with Client() as client:
    for trace in traces.traces:
        client.create(trace, environment_id="order-support")
```

The hosted environment must already exist. Trace writes upsert by `trace_id`;
optional linkage includes environment revision, agent, and run group IDs.
Local traces are not uploaded automatically. Read them with `client.traces.list(...)`
and `client.traces.get(trace_id)`; server filter support determines accepted
list parameters.

## Advanced: privacy, rewards, replay, and export

- Configure a [redactor](../guides/redact-pii.md) and `Sampler` before data reaches
  the sink. Sampling may omit traces you would otherwise expect in a dataset.
- Use [SQLite, JSONL, MultiSink, or OpenTelemetry](../concepts/sink.md) for storage.
  See [OTel export](../guides/export-otel.md) for collector configuration.
- `trace.credit(...)` adds late reward events. `transitions(source=...)`,
  `decision_rewards(...)`, and `returns(...)` support analysis of step and
  episode rewards. See [trace semantics](../concepts/trace.md).
- `plural.environments.export` contains Hugging Face-style row and verifier-row
  export helpers. Their exact formats are documented in the
  [API reference](../reference/api.md#datasets-and-export).
