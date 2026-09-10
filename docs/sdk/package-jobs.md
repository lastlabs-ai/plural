---
route: /docs/sdk/package-jobs
title: "Run package jobs from Python"
order: 90
description: "The Python SDK and CLI use the same schema-v2 graph and durable event store."
audience: all
---
# Run package jobs from Python

The Python SDK and CLI use the same schema-v2 graph and durable event store.

## Load, plan, and run

```python
import asyncio
from pathlib import Path

from plural import Job, JobStore
from plural.cli.scaffold import load_job

async def main():
    spec = load_job(Path("job.yaml"))
    plan = spec.plan()
    print(plan.job_id, plan.trial_count)

    store = JobStore(Path(".plural/jobs"))
    result = await Job(spec, store=store).run()
    print(result.status)

asyncio.run(main())
```

Planning expands Agent × selected Task × attempt. A Benchmark may select Tasks
from different Environments; the scheduler sends each Trial to the provider and
placement declared by that Task's Environment.

## Construct a Task Job

```python
from plural import AgentBinding, AgentDefinition, JobSpec, TaskJobSource
from plural.cli.scaffold import load_task

task = load_task(Path("task.yaml"))
agent = AgentDefinition(name="candidate", model="openai/gpt-4.1-mini")
spec = JobSpec(
    source=TaskJobSource(task=task),
    agents=(AgentBinding(agent=agent),),
    mode="eval",
    attempts=2,
    concurrency=2,
)
```

Use `BenchmarkJobSource(benchmark=...)` for cross-Environment suites. Agents do
not carry Environment identities. Harness compatibility is resolved and pinned
on each planned Trial.

## Modes, retries, and monitoring

Eval mode disables Rewarders and TITO capture while still executing every final
Verifier. Train mode enables Environment Rewarders and requires the Harness to
produce validated exact TITO JSONL. TITO bytes are stored under the immutable
TrialExecution artifact directory; receipts contain only hash, media type, and
size.

`await Job(spec, store=store).run(resume=True)` skips successful Trials. Retry
executions append under the same Trial identity. `await job.cancel()` writes a
durable cancellation marker and stops active sandboxes.

```python
for event in store.events(plan.job_id, after=0, follow=False):
    print(event.sequence, event.status, event.trial_id)
```

Progress events are monotonic and sanitized. Hidden state, verifier-only input,
secret values, and private reasoning are not event payloads.
