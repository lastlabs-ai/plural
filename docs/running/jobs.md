---
route: /docs/running/jobs
title: "Jobs"
order: 80
description: "Plan and run Agents against a Task or Benchmark locally by default, with explicit hosted submission."
audience: all
nav: true
nav_group: Running
outcome: You can dry-run, execute, and inspect a reproducible Job.
---
# Jobs

A Job owns a Task or Benchmark source, Agents, mode, attempts, concurrency, and
retry policy.

```python
from plural import Job

job = Job(benchmark, agents=[agent], attempts=2)
print(job.plan.trial_count)
result = job.run()
```

The CLI loads the same Job:

```bash
plural validate job.py:job
plural run job.py:job --dry-run
plural run job.yaml
```

Local execution is the default beginner path. Hosted synchronization and
submission require `--hosted`.

Eval mode runs final Verifiers. Train mode may additionally run Environment
Rewarders and capture exact training artifacts. Every Trial receipt records the
pinned Task, Benchmark, Agent, model endpoint, Environment, Verifiers, and
artifacts.
