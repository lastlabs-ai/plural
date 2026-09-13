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

The Environment's Python actions become executable through:

```python
environment = SupportQueue(runtime=runtime).package(
    ("python", "commands.py"),
    source=ROOT / "environment",
)
```

No scaffold-specific Pydantic file types participate in loading or execution.
