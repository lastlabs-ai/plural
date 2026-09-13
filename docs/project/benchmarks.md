---
route: /docs/project/benchmarks
title: "Benchmarks"
order: 70
description: "Version and pin an ordered Task set, compare versions, and export the complete dependency graph."
audience: all
nav: true
nav_group: Project
outcome: You can create, diff, inspect, and export a Benchmark.
---
# Benchmarks

A Benchmark is an explicitly versioned, ordered list of Tasks.

```python
from plural import Benchmark

benchmark = Benchmark(
    name="support",
    version="1.0.0",
    tasks=[ticket_1, ticket_2],
)
```

Each Task is pinned by name, version, and content hash. Additions, removals,
updates, reordering, and configuration changes are reported by
`benchmark.diff(other)`.

```bash
plural benchmarks show benchmark.py:benchmark
plural benchmarks diff old.yaml new.yaml
plural benchmarks export benchmark.yaml --output graph.yaml
```

`Benchmark.export()` is the same complete dependency graph used by the CLI.
