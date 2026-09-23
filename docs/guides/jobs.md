---
route: /docs/guides/jobs
title: Build and run a job
order: 270
description: Start with the complete CLI walkthrough to create the files used here, configure model credentials, and grant the harness secret. Add a verifier before treating a job as a scored evaluation. This page covers operations after your first run.
audience: all
nav: false
---
# Build and run a job

Start with the [complete CLI walkthrough](../tutorials/cli-walkthrough.md) to
create the files used here, configure model credentials, and grant the harness
secret. Add a [verifier](../project/verifiers.md) before treating a job as
a scored evaluation. This page covers operations after your first run.

## Validate and preview

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

The `local` Runtime provider is a trusted subprocess, not a sandbox. It runs
resource code as child processes under your user account and cannot enforce network, resource, or
filesystem boundaries, or a read-only root. An Environment selects it with
`provider: local` under `runtime:` in its `environment.yaml`. Verifiers declare
their Runtime independently.

## Docker

Install Docker and make sure the daemon is healthy. Then set `provider: docker`
in the Environment's `runtime:` and run as usual:

```bash
plural run -b support-triage -a careful --concurrency 4
```

Without `image`, the `docker` preset uses `python:3.12-slim`. Set `runtime.image`
to a pinned image reference, or set `dockerfile` (and optionally `build_context`,
which defaults to the Environment directory) to build one. Container, network,
and compute settings live on the Environment; the Job does not override them.
`network: no-network` is the strongest Docker network policy; Docker does not
enforce an `allowlist` of hosts. Docker supports CPU, memory, and process-count
limits, not per-container disk limits. Plural records the image ID in the
receipt.

The Docker daemon is a privileged trust boundary. A hardened container reduces
what the code inside can do, but it does not make an untrusted daemon or host
safe.

## Daytona

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

`--attempts` plans independent Trials per Task, and `--concurrency` bounds how
many run at once. Ten Tasks with three attempts plan thirty Trials. A run uses
one Agent or model; to compare several, run each one and compare the Jobs. Retry
policy may append executions to a Trial but does not add Trials.

The Python `Job` also accepts several Agents and a `per_runtime_concurrency`
limit for each Environment Runtime; see [Jobs](../running/jobs.md).

## Hosted execution

```bash
plural project init support-eval --push
plural benchmark push support-triage --with-deps
plural agent push careful
plural run -b support-triage -a careful --hosted --follow
```

`--hosted` runs on hosted infrastructure using revisions you have already pushed,
and refuses to start when any input differs from its pushed revision. `--follow`
streams progress until the Job finishes; without it, the command returns once
the Job is submitted, and `plural job show JOB_ID --follow` reconnects later. See
[Push and pull resources](studio-sync.md).

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
submission completes only a Trial that is waiting at `awaiting_review`.

Runnable offline Python examples are in
[`examples/jobs`](https://github.com/lastlabs-ai/plural/tree/main/examples/jobs).
