---
route: /docs/project/tasks
title: Tasks
order: 40
description: Combine instructions, one Environment, Verifiers, resources, and initial state into one versioned unit of work.
audience: all
nav: true
nav_group: Build
outcome: You can author a Task identically in Python or YAML.
---
# Tasks

A Task is one versioned unit of work. It supplies instructions and case data to
one Environment and attaches the Verifiers that define completion quality.

```python
from plural import Task

task = Task(
    name="ticket-1",
    version="1.0.0",
    instructions="Inspect, categorize, answer, and resolve the ticket.",
    goals=("Follow the support policy.", "Leave the ticket resolved."),
    info={"ticket_id": "ticket-1"},
    environment=environment,
    verifiers=[correct],
    metadata={"split": "evaluation"},
)
```

Important fields:

- `instructions`: direct Agent-facing work request.
- `goals`: explicit outcomes, not a replacement for executable Verifiers.
- `info`: public case data included in the Agent payload.
- `environment`: one resolved Environment.
- `verifiers`: one or more deterministic, Agent, or Human Verifiers.
- `resources`: Task-specific resource descriptors.
- `initial_state`: schema-checked fields injected before reset.
- `reset_options`: Environment setup options.
- `metadata`: splits, owners, labels, and other non-secret indexing data.

## Author good Tasks

Keep one coherent case per Task. Put reusable world behavior and policy in the
Environment; put case-specific facts in `info`, `initial_state`, or Task
resources. State what “done” means and tell the Agent when to stop.

Avoid leaking expected answers through `instructions`, `info`, observations,
or broadly readable files. Keep evaluator-only truth in hidden State or
isolated Verifier data. Never put credentials in Task fields.

Task content identity includes the resolved Environment and Verifier hashes.
Changing any field, Environment source/runtime, or Verifier changes the Task
hash. A published Task version must not be overwritten; create a new semantic
version and repin its Benchmark.

Use metadata such as `{"split": "evaluation"}` to label a split, but enforce
train/evaluation separation in the consuming data pipeline.
