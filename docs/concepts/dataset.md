# Dataset

Plural has two dataset roles with intentionally different payloads.

## TaskDataset: benchmark inputs

`TaskDataset` is a named, versioned collection of `TaskData`:

```python
from plural import TaskData, TaskDataset

tasks = TaskDataset(
    name="refund-suite",
    version="2026.08",
    tasks=[
        TaskData(
            task_id="refund-001",
            input="Please refund order A123.",
            expected={"intent": "refund"},
            metadata={"seed": 7},
        )
    ],
)
tasks.save("data/refund-tasks.jsonl")
```

It is the input accepted by `Benchmark.run(dataset=tasks)`. `expected` is evaluator-only and may contain sensitive labels: it is stored and hashed in the task dataset for reproducibility, but it is not sent to policies or copied into episode trace metadata.

Task ids must be unique. `TaskDataset.load(...)` requires the sidecar manifest and verifies its dataset kind, schema/hash versions, record count, and content hash.

## Dataset / TraceDataset: observed traces

`Dataset` is a named, versioned collection of complete `Trace` records from rollouts or production. `TraceDataset` is an alias for `Dataset`.

```python
from plural import Dataset, TraceFilter

rollouts = Dataset.from_traces(
    "refund-rollouts",
    [rollout.trace for rollout in completed],
    version="2026.08",
)

production = Dataset.from_sink(
    ".plural/traces.jsonl",
    "production-refunds",
    filter=TraceFilter(
        trace_kind="production",
        model="openai/gpt-4o-mini",
    ),
)
production.save("data/production-refunds.jsonl")
```

`TraceFilter` can match `trace_kind`, environment name/fingerprint, model, `terminated`, and `truncated`. `from_sink` also accepts a `where=` predicate.

Trace datasets are rollout/production outputs for analysis, export, and training workflows. They are not benchmark task inputs: `Benchmark.run(dataset=...)` consumes a `TaskDataset`, while the benchmark's per-case episode traces are result provenance and can later be collected into a `Dataset`.

## Full content hashes and manifests

Both dataset types use SHA-256 over deterministic, canonical serialization of the complete records:

- `TaskDataset` hashes full tasks, including `input`, `expected`, metadata, and task order.
- `Dataset` hash version 2 hashes full trace serialization, not only ids and outcomes.

`content_hash` is snapshot identity: it is captured at construction/load/save time and does not silently change if you mutate a task or trace in memory. `current_content_hash` recomputes the current contents without changing that stored identity:

```python
original = tasks.content_hash
tasks.tasks[0].input = "updated"
assert tasks.content_hash == original
assert tasks.current_content_hash != original
```

`save()` recomputes and refreshes `content_hash`, then writes JSONL plus a versioned `.manifest.json` sidecar containing identity, hash algorithm/version, count, and metadata. `Benchmark.run(dataset=tasks)` rejects a `TaskDataset` whose current content no longer matches its stored snapshot; save it to deliberately establish the new identity. `TaskDataset.load()` requires and integrity-checks its manifest. `Dataset.load()` verifies the recorded hash when a manifest is present and retains compatibility with legacy trace datasets.

`Dataset.from_traces()` also records the set of environment fingerprints in dataset metadata when available.
