---
route: /docs/guides/jobs
title: Build and run a job
order: 270
description: "After your first run: check a Job before it starts, choose where its Trials run, size how many run at once, record it in your hosted project, and rerun or review it."
audience: all
nav: false
---
# Build and run a job

This guide picks up after your first run. It covers checking a Job before it
starts, choosing where its Trials run (on your machine, in Docker, or in a remote
sandbox), how many run at once, and how to record, rerun, and review Jobs.

If you haven't run anything yet, start with the
[complete CLI walkthrough](../tutorials/cli-walkthrough.md). It creates the files
used here, configures model credentials, and grants the Harness its secret. Add a
[Verifier](../project/verifiers.md) before treating a Job as a scored evaluation.

## Validate and preview

Check everything before spending anything:

```bash
plural env validate support-queue
plural verifier validate correct-category
plural task validate ticket-1
plural benchmark validate support-triage
plural agent show careful
plural run -b support-triage -a careful --dry-run
```

Each `validate` command also checks everything the resource depends on.
`--dry-run` resolves every input, prints the version and content hash of each one
and the number of Trials, and starts nothing. It needs no model credential, which
makes it a safe preflight for CI.

## Local runs

```bash
plural run -b support-triage -a careful
plural run -t ticket-1 -m openai/gpt-5.6-luna
```

Every run is a new Job. A local run is recorded under `.plural/jobs/<job_id>/`
in the project, with a `run.json` that pins the version and content hash of every
input. Before running, Plural copies each input's source into `.plural/packages/`,
so later edits to your working files do not change what a recorded Job used.

Where a Trial runs is decided by its Environment, not by the command. An
Environment picks a Runtime with `provider:` under `runtime:` in its
`environment.yaml`. Verifiers declare their Runtime independently.

> **Good to know:** The `local` Runtime provider is a trusted subprocess, not a
> sandbox. It runs resource code as child processes under your user account and
> cannot enforce network, resource, or filesystem boundaries, or a read-only root.
> Use it only for code you trust.

## Docker

Docker runs each Trial in a sealed container on your machine. Install Docker and
make sure the daemon is healthy. Then set `provider: docker` in the Environment's
`runtime:` and run as usual:

```bash
plural run -b support-triage -a careful --concurrency 4
```

Without `image`, the `docker` preset uses `python:3.12-slim`. Set `runtime.image`
to a pinned image reference, or set `dockerfile` (and optionally `build_context`,
which defaults to the Environment directory) to build one. Container, network,
and compute settings live on the Environment; the Job does not override them.

- `network: no-network` is the strongest Docker network policy. Docker does not
  enforce an `allowlist` of hosts.
- Docker supports CPU, memory, and process-count limits, not per-container disk
  limits.
- Plural records the image ID in the receipt.

The Docker daemon is a privileged trust boundary. A hardened container reduces
what the code inside can do, but it does not make an untrusted daemon or host
safe.

## Daytona

Daytona runs each Trial in a remote sandbox, so nothing heavy runs on your
machine.

```bash
pip install "plural[daytona]"
export DAYTONA_API_KEY='...'
plural run -b support-triage -a careful
```

Set `provider: daytona` on each Environment's `runtime:`, with an image or
snapshot the provider can reach; without one it uses `python:3.12-slim`. Daytona
supports CPU and memory limits and all three network modes: `public`,
`no-network`, and `allowlist` with a non-empty `allowed_hosts`. It cannot build
from a local Dockerfile, and it does not support process-count or disk limits,
persistent workspaces, compose, or a read-only root.

## Attempts and concurrency

```bash
plural run -b support-triage -a careful --attempts 3 --concurrency 8
```

`--attempts` plans independent Trials per Task, and `--concurrency` (or `-n`)
bounds how many run at once. Ten Tasks with three attempts plan thirty Trials. A
run uses one Agent or model; to compare several, run each one and compare the
Jobs. Retry policy may add executions to a Trial but does not add Trials.

`--concurrency` defaults to `auto`, which sizes it before the run and prints the
number and the reason:

```text
Running benchmark/wordle@1.0.0 with word-list (openai/gpt-5.6-luna) locally: 3 trial(s), 3 at a time (auto: every Trial at once).
```

A Trial spends most of its time waiting on the model, so `auto` takes the lowest
of these limits:

| Limit | Value |
| --- | --- |
| Trials in the Job | All of them |
| `local` Runtime | 4 per CPU, and 256 MB each from half this machine's memory |
| `docker` Runtime | 2 containers per CPU the Environment requests (default 1), and its `memory` (default 512 MB) from half this machine's memory |
| Remote Runtime, such as `daytona` | `PLURAL_MAX_SANDBOXES`, default 10 |
| A model served on this machine | 1, when `OPENAI_BASE_URL` or `ANTHROPIC_BASE_URL` is a loopback address and no Plural key routes through the gateway |
| `PLURAL_MODEL_CONCURRENCY` | Your provider's rate limit, when you set it |
| Ceiling | 64 |

A hosted model API is not bounded by this machine, so a Benchmark against it
usually runs every Trial at once, up to the ceiling. When your provider
rate-limits, set `PLURAL_MODEL_CONCURRENCY` to its concurrent-request allowance.
A model on your own GPU is the opposite case: raise `PLURAL_MODEL_CONCURRENCY`
only as far as its server batches requests. A number passed to `--concurrency`
is used as it is. With `--hosted`, `auto` uses the Trial count and the ceiling,
because this machine does not run the Trials.

Each Trial prints when it finishes, with the Job's standing so far:

```text
  [2/3] trl_0cba547518e8343e731ddaf3  slate  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
```

Trials finish out of order. The running mean is a plain mean of the scores so
far; the final result applies the Benchmark's own scoring to every Trial, in plan
order. `plural job show JOB_ID` on a Job that is still running shows its
progress and the Benchmark aggregate over the Trials that have finished, with
the share of Tasks they cover.

The Python `Job` takes `concurrency="auto"` too, and also accepts several Agents
and a `per_runtime_concurrency` limit for each Environment Runtime; see
[Jobs](../running/jobs.md).

## Plural inside Docker and remote sandboxes

An Environment written as a Python class, and a Python Harness, run Plural's own
runners inside the sandbox, so the sandbox needs the `plural` package. `plural
run` provides it before the Harness starts. You do not need to install it in the
image yourself.

- `docker` builds your Environment's image once with Plural added and reuses it
  for later Trials and Jobs. The image is tagged `plural-runtime:<hash>` from
  the base image and the exact Plural code.
- Other providers, such as `daytona`, install Plural into each sandbox as it
  starts. This takes a few seconds and needs the sandbox's network.

By default the sandbox gets the same Plural code as the CLI that planned the
Job, so an unreleased build works too. `--plural-version 0.18.0` or
`--plural-version latest` installs a published release instead. From Python, set
`PLURAL_RUNTIME_VERSION` in the Job's environment. An image that already has the
selected version is used as it is. A `no-network` sandbox on a remote provider
needs an image with it preinstalled:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir plural==0.18.0
```

Inside a Docker container, `localhost` is the container. Plural rewrites a
loopback model URL, such as a gateway at `http://localhost:8005/v1`, to
`host.docker.internal`, so a local API server stays reachable. On Linux, bind
that server to an address the Docker bridge can reach, not only `127.0.0.1`.

## Record a Job in the hosted project

A local Job stays on this machine until you push it. Recording it in your private
hosted project lets your team see it in the web app under Jobs. First bind the
checkout and push its resources:

```bash
plural project init support-eval --push
plural project push
```

Then either push a Job after it finishes, or track it while it runs:

```bash
plural run -b support-triage -a careful
plural job push JOB_ID

plural run -b support-triage -a careful --track
```

Both record the same hosted Job, marked as run by a client, with every
execution's trajectory, usage, phases, and Verifier results. `--track` opens
each execution as it starts, so the hosted project shows the Job running. A
reporting failure never fails the local run; the command prints what could not
be recorded, and `plural job push JOB_ID` fills it in. `plural job rerun` and
`plural trial rerun` accept `--track` too.

Where the Trials execute is set by each Environment's `runtime.provider`, not by
these flags. A tracked Job against a `daytona` Environment runs its Trials in
remote sandboxes while this machine orchestrates and records them.

## Hosted execution

```bash
plural run -b support-triage -a careful --hosted --follow
```

`--hosted` submits the Job for hosted infrastructure to run, using pushed
revisions. It first pushes any input the hosted project lacks, as `--track` does,
and stops before uploading anything if someone changed a resource in the hosted
project since this checkout last synced it. `--follow` streams progress until the
Job finishes; without it, the command returns once the Job is submitted, and
`plural job show JOB_ID --follow` reconnects later. See
[Push and pull resources](studio-sync.md#run-pushed-resources).

## Inspect, rerun, and review

```bash
plural job list
plural job show JOB_ID
plural trial show TRIAL_ID
plural job rerun JOB_ID
plural trial rerun TRIAL_ID
plural review list
plural review submit TRIAL_ID --verifier human-review --score 1
```

`job rerun` runs a Job again with the exact inputs it pinned and creates a new
Job whose `rerun_of_job_id` points at the original. `trial rerun` creates a new
one-Trial Job whose `rerun_of_trial_id` points at the Trial. A hosted rerun is
refused when the model catalog would now resolve the model differently.

Each Job's `events.jsonl` is an append-only record of planning, provisioning,
execution, verification, retries, human review, and the final status. A retry is
a new execution inside the same Trial, not a new attempt. From Python,
`job.run(resume=True)` keeps the Trials that already succeeded. A review
submission completes only a Trial that is waiting at `awaiting_review`; see
[Reviews](../running/reviews.md).

Runnable offline Python examples are in
[`examples/jobs`](https://github.com/lastlabs-ai/plural/tree/main/examples/jobs).
