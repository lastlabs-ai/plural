---
route: /docs/tutorials/first-project
title: "Build a first project"
order: 116
description: "Generate a support evaluation from public Python objects and run the equivalent YAML without a second schema layer."
audience: all
nav: false
---
# Build a first project

`examples/first-project/build.py` creates Environment, Runtime, Verifier, Task,
Agent, Benchmark, and Job objects, then writes them with `plural.project.dump`.

```bash
cd examples/first-project
python build.py
plural validate job.yaml
plural run job.yaml --dry-run
```

The generated YAML has the same field names, defaults, nested graph, plan, and
content hashes as Python. Use `plural inspect job.yaml` to view the resolved
graph.

The Environment is the class plus a Runtime:

```python
environment = SupportQueue(runtime=runtime)
```

Follow the [support queue tutorial](support-queue.md) to run the project, inspect its scores, and adapt it to your own tickets.
