---
route: /docs/tutorials/sdk-walkthrough
title: "Build and run a schema-v2 graph in Python"
order: 40
description: "This walkthrough uses the same typed models as the CLI."
audience: all
---
# Build and run a schema-v2 graph in Python

This walkthrough uses the same typed models as the CLI.

```python
from plural import (
    AgentBinding,
    AgentDefinition,
    BenchmarkDefinition,
    BenchmarkJobSource,
    DeterministicVerifier,
    EnvironmentDefinition,
    EnvironmentRuntime,
    JobSpec,
    NetworkMode,
    TaskDefinition,
    VerifierRuntime,
    WeightedVerifier,
)

environment = EnvironmentDefinition(
    name="support",
    revision="1.0.0",
    overview="A network-isolated order support runtime.",
    runtime=EnvironmentRuntime(
        provider="docker",
        image="python:3.12-slim",
        network=NetworkMode.NONE,
    ),
)

verifier = DeterministicVerifier(
    name="correct",
    revision="1.0.0",
    command=("python", "verify.py"),
    runtime=VerifierRuntime(provider="docker", network=NetworkMode.NONE),
)

task = TaskDefinition(
    task_id="order-a100",
    revision="1.0.0",
    instructions="Return the status of the order.",
    info={"order_id": "A100"},
    environment=environment,
    verifiers=(WeightedVerifier(verifier=verifier, weight=1),),
)

agent = AgentDefinition(
    name="candidate",
    revision="1.0.0",
    model="openai/gpt-4.1-mini",
    instructions="Be concise.",
)

benchmark = BenchmarkDefinition(
    name="support-suite",
    tasks=(task,),
)

spec = JobSpec(
    source=BenchmarkJobSource(benchmark=benchmark),
    agents=(AgentBinding(agent=agent),),
    mode="eval",
    attempts=2,
    concurrency=4,
)
print(spec.plan())
```

Environment owns runtime placement, network, resources, secrets, actions, and
typed hidden/observable schemas. Task pins the Environment and weighted
Verifier revisions. AgentDefinition is not Environment-bound. A Benchmark can
select Tasks from multiple Environments.

## Execute and watch

```python
import asyncio
from pathlib import Path

from plural import Job, JobStore

store = JobStore(Path(".plural/jobs"))
result = asyncio.run(Job(spec, store=store).run())

for event in store.events(result.job_id, after=0, follow=False):
    print(event.sequence, event.status, event.trial_id)
```

Attempts are independent Trials. A retry is a TrialExecution beneath the same
Trial. Progress events are append-only and durable.

Human Verifiers produce `awaiting_review`. Submit rubric scores through
`Job.submit_review(...)` or `plural review submit`.

## Eval versus train

Eval disables Rewarders and TITO capture while still running every final
Verifier. Train enables Environment Rewarders and fails preflight unless the
Harness can emit exact TITO.

TITO records validate aligned token IDs, output log probabilities/top log
probabilities, output text, assistant message, and input/output/observation
lengths. The records are immutable hashed artifacts, not embedded Trace JSON.

See [Python package Jobs](../sdk/package-jobs.md) and the
[CLI walkthrough](cli-walkthrough.md).
