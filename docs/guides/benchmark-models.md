---
route: /docs/guides/benchmark-models
title: "Compare Agents on revisioned Tasks"
order: 260
description: "A schema-v2 Benchmark is an ordered list of Task revisions and may span Environments."
audience: all
---
# Compare Agents on revisioned Tasks

A schema-v2 Benchmark is an ordered list of Task revisions and may span
Environments.

```python
from plural import (
    AgentBinding,
    BenchmarkDefinition,
    BenchmarkJobSource,
    JobSpec,
)

benchmark = BenchmarkDefinition(
    name="support-suite",
    tasks=(billing_task, shipping_task),
    primary_metric="reward",
)
spec = JobSpec(
    source=BenchmarkJobSource(benchmark=benchmark),
    agents=(
        AgentBinding(agent=small_agent),
        AgentBinding(agent=large_agent),
    ),
    mode="eval",
    attempts=3,
    concurrency=8,
    per_runtime_concurrency=2,
)
```

The plan contains two Agents × two Tasks × three attempts. Task order is
stable. Every Task pins its own Environment and weighted Verifiers, so the
scheduler can dispatch the plan across multiple runtime placements.

AgentDefinition contains model, instructions, routing, and optional Harness,
but no Environment identity. Harness compatibility is stamped per Trial.

All final Verifiers run in eval mode. Successful weighted rewards aggregate
deterministically; a human Verifier leaves the Trial in `awaiting_review`.
Train mode additionally enables Environment Rewarders and exact artifact-backed
TITO capture.

```bash
plural benchmark validate benchmark.yaml
plural run benchmark.yaml \
  --agent small.yaml --agent large.yaml \
  --mode eval --attempts 3 --concurrency 8
plural job watch JOB_ID --hosted --json
```

The run publishes shared dependencies once, submits the Benchmark Job with
exact hosted revision IDs, and watches it by default. Add `--offline` to keep
execution and the durable event log local.

Retries are TrialExecutions and do not increase the attempt count. Compare
results only after accounting for failed and awaiting-review Trials.
