---
route: /docs/concepts/benchmark
title: "Benchmark"
order: 190
description: "BenchmarkDefinition is a revisioned, ordered selection of complete Task revisions plus a primary metric, description, and metadata."
audience: all
---
# Benchmark

`BenchmarkDefinition` is a revisioned, ordered selection of complete Task
revisions plus a primary metric, description, and metadata.

```python
from plural import BenchmarkDefinition

benchmark = BenchmarkDefinition(
    name="support-suite",
    revision="1.0.0",
    tasks=(billing_task, shipping_task),
    primary_metric="reward",
)
```

Each Task pins its own exact Environment revision and weighted Verifier
revisions. Consequently, a Benchmark may span different Environments,
runtimes, placements, and network policies. The scheduler routes every Trial
to the runtime owned by that Trial's Task Environment.

## Jobs and planning

```python
from plural import AgentBinding, BenchmarkJobSource, JobSpec

spec = JobSpec(
    source=BenchmarkJobSource(benchmark=benchmark),
    agents=(AgentBinding(agent=agent),),
    mode="eval",
    attempts=2,
    concurrency=8,
    per_runtime_concurrency=2,
)
plan = spec.plan()
```

Planning order is deterministic:

`Agents × Benchmark Tasks × attempts`

Attempts create independent Trials. `RetryPolicy` creates TrialExecutions under
an existing Trial and therefore never changes Trial count or identity.

## Verification and modes

All final Verifiers run in eval and train. Multiple successful Verifier rewards
aggregate deterministically by normalized declared weight. A human Verifier
holds the Trial in `awaiting_review`.

Eval mode disables Environment Rewarders and TITO capture. Train mode enables
Rewarders and requires exact artifact-backed TITO support at preflight. TITO
records are stored as hashed artifacts, not embedded trace payloads.

## Monitoring

Jobs append durable `ProgressEvent` records while scheduling, provisioning,
running, retrying, verifying, and awaiting review:

```bash
plural run benchmark.yaml --agent agent.yaml --mode eval
plural job watch JOB_ID --hosted --json
```

The run synchronizes the canonical graph and follows hosted events by default.
Use `--offline` when the Job and its durable event log must remain local.

See [package execution](execution.md) and
[Python Job execution](../sdk/package-jobs.md).
