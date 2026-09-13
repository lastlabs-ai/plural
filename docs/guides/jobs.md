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
secret. Add a [verifier](../tutorials/package-tools.md) before treating a job as
a scored evaluation. This page covers operations after your first run.

## Validate and inspect

```bash
plural env validate environment
plural verifier validate verifier.yaml
plural task validate task.yaml
plural benchmark validate benchmark.yaml
plural agent show agent.yaml
plural run job.yaml --dry-run --format yaml
```

`--dry-run` computes the job ID, complete lock, trial IDs, and count without
starting a sandbox. It is the safest release/CI preflight.

## Hosted execution

With `PLURAL_API_KEY` configured, `plural run` validates the complete graph,
publishes it in dependency order, submits a hosted Job using the exact returned
revision IDs, prints the Job, and follows hosted events:

```bash
plural run job.yaml
plural run job.yaml --json
plural run job.yaml --no-watch --idempotency-key release-42
```

The default idempotency key is the stable local Job ID. Identical shared
dependencies are published once per synchronization pass. `plural job submit`
remains the advanced workflow for callers that already have exact hosted source
and Agent revision IDs.

## Local development

```bash
plural run task.yaml --agent agent.yaml --mode eval --offline
```

`--private` is equivalent to `--offline`. Both keep the durable Job log under
`.plural/jobs`.

The local provider is not a sandbox. It executes package commands as child
processes under your user account and cannot enforce network, resources,
filesystem boundaries, or a read-only root. It is available only when the
Task's Environment declares provider `local`, `network: full`, and
`allow_unsafe_local: true`. Verifiers declare runtime and connectivity
independently.

## Docker

Install Docker and make sure the daemon is healthy. Then:

```bash
plural run benchmark.yaml --agent agent.yaml --concurrency 4 --offline
```

If no image/build context is configured, the CLI uses the Environment directory
as a Docker build context. You can instead set `environment.runtime.image` to a
pinned image reference. Container, network, and compute live on the environment;
the job only selects a requested target. `network: none` is the strongest
supported Docker network policy;
`restricted` domain/CIDR allowlists are not implemented by this provider.
Docker resource support covers CPU, memory, and process count, not per-container
disk limits. Plural records the inspected image ID in the receipt.

The Docker daemon is a privileged trust boundary. A hardened container reduces
guest capabilities but does not make an untrusted local daemon or host safe.
Opt-in daemon integration tests use the `docker` pytest marker.

## Daytona

```bash
pip install "plural[daytona]"
export DAYTONA_API_KEY='...'
plural run job.yaml --offline
```

Set the provider and image, snapshot, or declarative image on each Environment
revision. Daytona supports
CPU/memory and `none`, `full`, or non-empty restricted network allowlists in the
current adapter. Local Docker build contexts, pid/disk limits, persistence,
compose, read-only root, and stdin execution are unavailable. The harness runner
works around stdin by uploading its request first. Live tests require explicit
credentials and the `daytona` marker.

## Sweeps and independent attempts

```bash
plural run job.yaml --agent agent-a.yaml --agent agent-b.yaml \
  --attempts 3 --concurrency 8 --per-runtime-concurrency 4 --offline
```

`per_runtime_concurrency` bounds launches independently for each Environment
runtime while `concurrency` is the global ceiling. Three Agents, ten selected
Tasks, and two attempts plan sixty Trials. Retry policy may append multiple
TrialExecutions but does not add Trials.

## Resume, retry, cancel, and review

An offline/private run prints its `job_id` and stores state under
`.plural/jobs`.

```bash
plural job list
plural job show JOB_ID
plural trial list JOB_ID
plural job watch JOB_ID --json
plural trial watch TRIAL_ID --job JOB_ID --json
plural review list JOB_ID
plural review submit JOB_ID TRIAL_ID --verifier human-review --score 1
```

The append-only event stream records planning, provisioning, execution,
verification, retry, human-review, and terminal transitions. `TrialExecution`
distinguishes retries from independent Trial attempts. Use the Python
`Job.run(resume=True)` and `Job.cancel()` APIs for local lifecycle operations.
Human review submissions resolve Trials that are explicitly
`awaiting_review`.

For a hosted Job submitted with `--no-watch`, reconnect with:

```bash
plural job watch JOB_ID --hosted --json
```

Runnable offline counterparts are in
[`examples/jobs`](https://github.com/lastlabs-ai/plural/tree/main/examples/jobs).
