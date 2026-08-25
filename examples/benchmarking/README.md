# Benchmarking examples

Both scripts run offline, use a versioned `TaskDataset`, write Markdown and JSON
reports under `.plural/examples`, and persist episode traces.

## 1. Compare models

```bash
uv run python examples/benchmarking/01_compare_models.py
```

[`01_compare_models.py`](01_compare_models.py) compares two scripted provider
stand-ins through one `Plural` client. For a live benchmark, replace the
provider/client setup and keep the model IDs, dataset, and benchmark:

```python
client = Plural()
report = Benchmark(
    env,
    models=["openai/gpt-4o-mini", "anthropic/claude-sonnet-4"],
    client=client,
    environment_factory=make_env,
).run(dataset=dataset)
```

## 2. Compare arbitrary policies

```bash
uv run python examples/benchmarking/02_compare_policies.py
```

[`02_compare_policies.py`](02_compare_policies.py) uses
`Benchmark.from_policies` on the real Library environment. Each factory returns
a fresh policy for every concurrent job, and `environment_factory` does the
same for environments. A caller-owned `TraceWriter` persists traces and is
closed in `finally`.
