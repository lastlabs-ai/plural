---
route: /docs/project/benchmarks
title: "Benchmarks"
order: 70
description: "Version and pin an ordered Task set, compare versions, and export the complete dependency graph."
audience: all
nav: true
nav_group: Build
outcome: You can create, diff, inspect, and export a Benchmark.
---
# Benchmarks

A Benchmark is an explicitly versioned, ordered list of Tasks. It is the stable
comparison unit: every Task is pinned by name, version, and content hash.

```python
from plural import Benchmark

benchmark = Benchmark(
    name="support",
    version="1.0.0",
    tasks=[ticket_1, ticket_2],
)
```

`version` is required. `primary_metric` defaults to `reward`; `description` and
`metadata` are optional. Nested Benchmarks, floating Task queries, and mutable
published versions are not supported.

Create a new Benchmark version when a Task is added, removed, updated, or
reordered, or when Benchmark configuration changes. Compare before publishing:

```python
change = benchmark_v1.diff(benchmark_v2)
assert change.changed
print(change.added, change.removed, change.updated, change.reordered)
```

```bash
plural benchmarks show benchmark.py:benchmark
plural benchmarks diff old.yaml new.yaml
plural benchmarks export benchmark.yaml --output graph.yaml
```

`Benchmark.export()` is the same complete dependency graph used by the CLI.
It includes Benchmark metadata, Task definitions, and deduplicated Environment
and Verifier dependencies in deterministic order.

Use immutable versions to compare Agents over time. Do not mix changed Tasks,
Verifier rubrics, or Runtime policy into the same Benchmark version and call
the scores comparable.
