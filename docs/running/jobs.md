---
route: /docs/running/jobs
title: "Jobs"
order: 80
description: Start a run of your Agents against a Task or Benchmark, see how many attempts it will make, and read how it went, what it cost, and how it scored.
audience: all
nav: true
nav_group: Run
outcome: You can dry-run, execute, and inspect a reproducible Job.
---
# Jobs

A **Job** is one run you start: "run these Agents on this Task" or "run these
Agents on this Benchmark". It makes the attempts, grades each one, and keeps a
complete record, so afterwards you can see how every Agent did, what it cost, and
why it scored what it did.

Think of a Job as one sitting of the exam. Each attempt by one Agent at one Task
is a [Trial](trials.md), and a Job is the set of Trials it planned.

## Why it matters

A Job is repeatable. Before it starts, it pins the exact version of every Task,
Agent, Environment, and Verifier it uses. You can rerun it months later with
`plural job rerun` and get the same experiment, even if you have edited your files
since.

## Run one from the command line

A run picks one Task (`-t`) or Benchmark (`-b`) and one Agent (`-a`) or model
(`-m`). Preview it first with `--dry-run`, then run it for real:

```bash
plural run -b wordle -a word-list --dry-run
plural run -b wordle -a word-list
plural job list
plural job show JOB_ID
plural job rerun JOB_ID
```

The dry run shows what the Job will use and how many Trials it will make, and
starts nothing. `plural job list` lists your Jobs, newest first. `plural job show`
lists each Trial's Task, status, and score. To dig into one attempt, see
[Trials and trajectories](trials.md).

Every run is a new Job. `plural job rerun` runs a recorded Job again with its
exact inputs, as a new Job linked to the original. `plural trial rerun TRIAL_ID`
does the same for a single Trial, as a new one-Trial Job.

> **Good to know:** A real run calls models through the Plural gateway, so it
> needs a Plural API key. Store one with `plural auth login --api-key-stdin` or
> set `PLURAL_API_KEY`. A browser login alone is not accepted for model calls.

## Run one from Python

The Python `Job` does the same thing and can compare several Agents in one run.
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

With three Tasks, two Agents, and two attempts, this Job creates twelve Trials.
`client=Client()` sends model calls through the Plural gateway with your Plural
API key.

To use the resources in your project folder, load them with a `Workspace`:

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
key. Use `await job.run_async()` inside an existing event loop.

## Attempts, concurrency, and retries

Three settings shape a Job:

- **Attempts** is how many independent tries each Agent gets at each Task. Each
  attempt is its own Trial and counts in the results.
- **Concurrency** is how many Trials run at the same time.
- **Retries** rerun a Trial that failed for a passing reason, such as a timeout.
  A retry is another *execution* of the same Trial, not a new Trial, so it never
  inflates your sample size.

The defaults are `mode="eval"`, `attempts=1`, `concurrency=1`, `priority=0`, and no
retries. `per_runtime_concurrency` defaults to `concurrency`, so Trials that share
one Environment Runtime run in parallel too; set it lower to cap one Runtime.
`concurrency="auto"` sizes the Job from this machine, its Runtimes, and where the
model runs, and `job.concurrency_reason` says which limit set it; see
[Attempts and concurrency](../guides/jobs.md#attempts-and-concurrency).

Only rate limits, provider unavailability, timeouts, and Runtime unavailability
are retried. The wait before a retry starts at 0.25 seconds and doubles each time,
up to 10 seconds.

> **Tip:** Do not use retries to hide configuration, evidence, or policy errors.
> Fix those instead.

## Local, tracked, and hosted

By default, `plural run` runs the Job from this machine and records it only under
`.plural/jobs`. Each Environment's `runtime.provider` decides where its Trials
execute: in a local process, in Docker, or in a remote Daytona sandbox. The
Runtime is part of the Environment, so the same command runs a Benchmark locally
or remotely depending on how its Environments are declared.

To keep a Job in your private hosted project as well, so your team can see it in
the web app under Jobs:

| Command | What it does |
| --- | --- |
| `plural job push JOB_ID` | Records a finished local Job in the hosted project. |
| `plural run ... --track` | Records the Job in the hosted project while it runs here. |
| `plural run ... --hosted` | Submits the Job for hosted infrastructure to run. |

`job push` and `--track` create the same hosted Job, marked as run by a client,
so pushing a tracked Job again records nothing twice. A tracked run opens each
hosted execution as it starts, reports liveness while it runs, and publishes the
trajectory, usage, and Verifier results when it ends. If the hosted service
cannot be reached mid-run, the local Job still finishes and `plural job push`
fills in what was missed.

A hosted Job pins pushed revisions. `plural job push` needs the revisions the
local Job ran to be pushed already. `--track` and `--hosted` push whatever the
hosted project lacks first, giving a resource whose files changed under the same
version the next patch version. `--follow` streams hosted progress for `--hosted`
Jobs. See [Push and pull resources](../guides/studio-sync.md).

Hosted execution also needs credentials and Runtime providers that fit the
project's policy. A successful local run does not imply the same inputs can run
hosted.

## Evaluate before routing or training

Eval mode, the default, runs the Verifiers at the end of each episode and
records the score, cost, latency, trajectory, and whether each Trial completed.
Compare results only across the same Agent and Benchmark versions. Use those
records to [choose a routing policy](../reference/integrations.md#route-after-evaluation)
for application traffic.

Train mode (`mode=JobMode.TRAIN`) also runs the Verifiers, and additionally
requires the Harness to record the exact tokens in and tokens out of every model
call. A Trial whose Harness does not support that capture fails with a
`tito_unsupported` error. Train mode also streams each step's reward as a progress
event. Rewards are for training and never count toward the score; see
[Training and RL](training.md).

## Going deeper

This section is for readers who want to know exactly what a Job records and how
resuming works.

**What the plan pins.** `job.plan` fixes everything the Job will use before it
starts: the Task and Benchmark versions, the model endpoint each model resolves
to, the content hashes of every Environment, Verifier, Agent, and Harness, the
Runtime provider, the mode, and the list of Trials (one per Agent, Task, and
attempt).

**What a local run writes.** A local `plural run` is recorded under
`.plural/jobs/<job_id>/`: `config.json` and `lock.json` hold the resolved Job and
its lock, `events.jsonl` the progress events, `trials/` the Trial records, and
`run.json` the pinned version and content hash of every input. See
[Artifacts and evidence](artifacts.md) for the full layout.

**How reruns link.** `plural job rerun` creates a new Job linked to the original
through `rerun_of_job_id`. `plural trial rerun` creates a one-Trial Job linked
through `rerun_of_trial_id`.

**Resuming.** `job.run(resume=True)` keeps the Trials that already succeeded and
runs new executions for the rest. It refuses to resume when any planned input has
changed.
