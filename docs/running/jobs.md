---
route: /docs/running/jobs
title: "Jobs"
order: 80
description: Run selected agents against your Tasks, preview the Trial count, and inspect the results.
audience: all
nav: true
nav_group: Run
outcome: You can dry-run, execute, and inspect a reproducible Job.
---
# Jobs

A Job runs your chosen Agents against a Task or Benchmark and collects the results. It controls how many times each case is attempted and how many Trials run at once.

## Create a Job

Given a `benchmark` and two Agents, `careful` and `concise`:

```python
from plural import Client, Job, RetryPolicy

job = Job(
    benchmark,
    agents=[careful, concise],
    client=Client(),
    attempts=2,
    concurrency=4,
    per_runtime_concurrency=2,
    retry=RetryPolicy(max_retries=2),
)
print(job.plan.trial_count)
result = job.run()
```

With three Tasks, two Agents, and two attempts, this Job creates twelve Trials. Configure model authentication before calling `run`; the CLI can use `plural auth login`.

Defaults are `mode="eval"`, `attempts=1`, `concurrency=1`,
`per_runtime_concurrency=1`, `priority=0`, and no retries. Retry backoff starts
at 0.25 seconds, caps at 10 seconds, and doubles for rate limits, provider
unavailability, timeouts, and Runtime unavailability.

`attempts` creates independent Trials. `max_retries` creates additional
executions of a failed Trial. Do not use retries to hide configuration,
evidence, or policy errors.

## Plan, run, resume

```bash
plural validate job.py:job
plural run job.py:job --dry-run
plural run job.yaml
plural job list
plural job show JOB_ID
plural job watch JOB_ID --follow
```

`job.plan` freezes Task and Benchmark pins, model endpoint resolutions,
Environment/Verifier/Agent/Harness hashes, Runtime provider, mode, and the
Agent × Task × attempt Trial expansion.

`job.run(resume=True)` or the advanced resume command reuses only successful
locked Trials and appends new executions where needed. A changed lock is
rejected.

Use `await job.run_async()` inside an existing event loop.

## Local and hosted

`plural run` executes with local orchestration and a store beside the source
reference. The Environment can still select Docker or Daytona and call paid
model APIs. `--hosted` explicitly synchronizes the graph and submits it to
Plural Intel.

Hosted execution needs materializable source, supported revision APIs,
credentials, and policy-compatible Runtime providers. A successful local run
does not imply the same graph can run hosted.

## Evaluate before routing or training

Eval mode runs final Verifiers and records quality, cost, latency, trajectory,
and completeness evidence. Compare exact Agent and Benchmark pins. Use those records to [choose routing policy](../reference/integrations.md#route-after-evaluation) for application traffic.

Train mode keeps the final Verifiers and adds exact TITO and supported
Rewarders. It is intentionally stricter; see [Training and RL](training.md).
