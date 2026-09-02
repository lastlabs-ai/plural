# Benchmark models

Start with the two runnable offline examples:

```bash
uv run python examples/benchmarking/01_compare_models.py
uv run python examples/benchmarking/02_compare_policies.py
```

- [Compare model IDs](https://github.com/lastlabs-ai/plural/blob/main/examples/benchmarking/01_compare_models.py)
- [Compare arbitrary policies](https://github.com/lastlabs-ai/plural/blob/main/examples/benchmarking/02_compare_policies.py)
- [Benchmarking example guide](https://github.com/lastlabs-ai/plural/tree/main/examples/benchmarking)

Create and save a versioned task input first. Its hash includes hidden `expected` labels and metadata:

```python
from plural import TaskData, TaskDataset

dataset = TaskDataset(
    name="support-suite",
    version="2026.08",
    tasks=[
        TaskData(
            task_id="refund-001",
            input="I need a refund.",
            expected="refund",
            metadata={"seed": 1},
        ),
    ],
)
dataset.save("data/support-tasks.jsonl")
```

`content_hash` is the saved snapshot identity. If tasks are mutated later, `current_content_hash` changes while `content_hash` stays fixed until the next `save()`. Benchmarking rejects that stale `TaskDataset`; task order is part of the hash.

Run each model on the same `(task_id, repeat)` slots:

```python
from pathlib import Path
from plural import Benchmark

report = Benchmark(
    env,
    models=[
        "openai/gpt-4o-mini",
        "anthropic/claude-sonnet-4",
        "google/gemini-2.5-flash",
    ],
    client=client,
    repeats=3,
    concurrency=8,
).run(dataset=dataset)

Path("report.md").write_text(report.to_markdown())
Path("report.json").write_text(report.to_json())
client.push(report)
```

Inspect `report.cases` for per-case trace ids, stop state, rewards, episode-total cost/latency, and failures. New reports have a manifest containing actual worker environment identity, runtime fingerprints, and an order-sensitive task-set hash for `TaskDataset`, explicit-task, or environment-task sources. `Report.manifest` remains optional when loading legacy reports. `report.models` includes failure buckets and reward uncertainty fields; `report.win_rate_pairs` includes paired comparison and exclusion counts.

Win rates compare only matching `(task_id, repeat)` cases. A failed or unscored case is excluded from that pair, and a tie counts as half a win.

## Compare arbitrary policies

`Benchmark.from_policies` accepts target names mapped to factories:

```python
from plural import ScriptedPolicy

benchmark = Benchmark.from_policies(
    env,
    {
        "rules": lambda: RulesPolicy(),
        "scripted": lambda: ScriptedPolicy(script()),
    },
    repeats=3,
    concurrency=4,
)
report = benchmark.run(dataset=dataset)
```

The factory is invoked once per job. Return a fresh synchronous policy every time; do not share mutable policy instances across concurrent cases.

`env.spawn()` also creates a fresh environment per job. For required constructors or stateful dynamic closures that it cannot safely reconstruct, pass `environment_factory=lambda: MyEnv(...)`. Pass `runtime_factory=` when each case needs a fresh synchronous sandbox, remote executor, or custom runtime.

`Benchmark.from_policies()` does not own a client writer. Without `trace_writer=`, case trace ids refer only to in-memory results. To make successful and failed episode traces durable, pass a caller-owned `TraceWriter`, then flush or close it yourself:

```python
from plural import JSONLSink, TraceWriter

writer = TraceWriter(JSONLSink("policy-episodes.jsonl"))
try:
    report = Benchmark.from_policies(
        env,
        {"rules": lambda: RulesPolicy()},
        trace_writer=writer,
    ).run(dataset=dataset)
finally:
    writer.close()
```

## CI regression tolerance

```python
from plural import Report

baseline = Report.model_validate_json(Path("baseline.json").read_text())
comparison = report.compare(baseline, tolerance=0.02)
assert not comparison["regressions"], comparison
```

Comparison validates available environment/runtime/task provenance, ordered task ids, and repeats by default. Use `allow_incompatible=True` only for an intentional mismatch. `tolerance` is a non-negative absolute reward decrease. Reward intervals are descriptive normal approximations, not significance tests, so choose CI gates based on the scale and stability of your scorer.
