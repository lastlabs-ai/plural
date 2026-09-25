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

With three Tasks, two Agents, and two attempts, this Job creates twelve Trials. `client=Client()` sends model calls through the Plural gateway with your Plural API key, stored with `plural auth login --api-key-stdin` or set as `PLURAL_API_KEY`. A browser login alone is not accepted for model calls.

Defaults are `mode="eval"`, `attempts=1`, `concurrency=1`, `priority=0`, and no
retries. `per_runtime_concurrency` defaults to `concurrency`, so Trials that share
one Environment Runtime run in parallel too; set it lower to cap one Runtime.
`concurrency="auto"` sizes the Job from this machine, its Runtimes, and where the
model runs, and `job.concurrency_reason` says which limit set it; see
[Attempts and concurrency](../guides/jobs.md#attempts-and-concurrency). Retry backoff starts
at 0.25 seconds, caps at 10 seconds, and doubles for rate limits, provider
unavailability, timeouts, and Runtime unavailability.

`attempts` creates independent Trials. `max_retries` creates additional
executions of a failed Trial. Do not use retries to hide configuration,
evidence, or policy errors.

## Plan, run, resume

From the CLI, a run selects one Task or Benchmark and one Agent or model:

```bash
plural run -b wordle -a word-list --dry-run
plural run -b wordle -a word-list
plural job list
plural job show JOB_ID
plural job rerun JOB_ID
```

Every run is a new Job. A local run is recorded under `.plural/jobs/<job_id>/`:
`config.json` and `lock.json` hold the resolved Job and its lock, `events.jsonl`
the progress events, `trials/` the Trial records, and `run.json` the pinned
version and content hash of every input. `plural job rerun` runs a recorded Job
again with those exact inputs and creates a new Job linked to it through
`rerun_of_job_id`; `plural trial rerun TRIAL_ID` does the same for one Trial as a
new one-Trial Job linked through `rerun_of_trial_id`.

From Python, load the same project resources with a `Workspace`:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
benchmark = workspace.get("benchmark", "wordle")
agent = workspace.get("agent", "word-list")
result = Job(benchmark, agents=[agent]).run()
```

That Job runs locally and is not recorded under `.plural/jobs`. Pass
`client=Client()` to send model calls through the Plural gateway with your API
key.

`job.plan` fixes everything the Job will use before it starts: the Task and
Benchmark versions, the model endpoint each model resolves to, the content
hashes of every Environment, Verifier, Agent, and Harness, the Runtime
provider, the mode, and the list of Trials (one per Agent, Task, and attempt).

`job.run(resume=True)` keeps the Trials that already succeeded and runs new
executions for the rest. It refuses to resume when any planned input has
changed.

Use `await job.run_async()` inside an existing event loop.

## Local, tracked, and hosted

`plural run` orchestrates the Job from this machine and records it only under
`.plural/jobs`. Each Environment's `runtime.provider` decides where its Trials
execute: in a local process, in Docker, or in a remote Daytona sandbox. The
Runtime is part of the Environment, so the same command runs a Benchmark locally
or remotely depending on how its Environments are declared.

To keep a Job in the hosted project as well:

| Command | What it does |
| --- | --- |
| `plural job push JOB_ID` | Records a finished local Job in the hosted project. |
| `plural run ... --track` | Records the Job in the hosted project while it runs. |
| `plural run ... --hosted` | Submits the Job for hosted infrastructure to run. |

`job push` and `--track` create the same hosted Job, marked as run by a client,
so pushing a tracked Job again records nothing twice. A tracked run opens each
hosted execution as it starts, reports liveness while it runs, and publishes the
trajectory, usage, and Verifier results when it ends. If the hosted service
cannot be reached mid-run, the local Job still finishes and `plural job push`
fills in what was missed.

Both require every input to be pushed first, and refuse when any input differs
from its pushed revision. `--follow` streams hosted progress for `--hosted`
Jobs. See [Push and pull resources](../guides/studio-sync.md).

Hosted execution also needs credentials and Runtime providers that fit the
project's policy. A successful local run does not imply the same inputs can run
hosted.

## Evaluate before routing or training

Eval mode, the default, runs the Verifiers at the end of each episode and
records the score, cost, latency, trajectory, and whether each Trial completed.
Compare results only across the same Agent and Benchmark versions. Use those
records to [choose a routing policy](../reference/integrations.md#route-after-evaluation) for application traffic.

Train mode (`mode=JobMode.TRAIN`) also runs the Verifiers, and additionally
requires the Harness to record the exact tokens in and tokens out of every model
call. A Trial whose Harness does not support that capture fails with a
`tito_unsupported` error. Train mode also streams each step's reward as a progress
event; see [Training and RL](training.md).
