# Build and run a job

Start with the [complete CLI walkthrough](../tutorials/cli-walkthrough.md) to
create the files used here, configure model credentials, and grant the harness
secret. Add a [verifier](../tutorials/package-tools.md) before treating a job as
a scored evaluation. This page covers operations after your first run.

## Validate and inspect

```bash
plural env validate environment
plural env action list --environment environment
plural env capabilities --environment environment
plural env task list --environment environment
plural env harness list --environment environment
plural env harness capabilities --environment environment
plural runtime doctor --env environment
plural benchmark validate benchmark.yaml --environment environment
plural agent template show agent.yaml
plural run job.yaml --print-config --format yaml
```

`--dry-run` computes the job ID, complete lock, trial IDs, and count without
starting a sandbox. It is the safest release/CI preflight.

## Local development

```bash
plural run job.yaml --runtime local --unsafe-local
```

The local provider is not a sandbox. It executes package commands as child
processes under your user account and cannot enforce network, resources,
filesystem boundaries, or a read-only root. Because verifiers always require
no-network enforcement, a Job with a verifier cannot run on `local`. Use it
only for trusted, unverified development runs.

## Docker

Examples include `--unsafe-local` to permit the tutorial's mutable local harness
source. With a digest-pinned archive binding, this source opt-in is unnecessary.

Install Docker and make sure `plural runtime doctor docker` reports healthy.
Then:

```bash
plural run job.yaml --runtime docker --unsafe-local --concurrency 4 --retry 2
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
plural runtime doctor daytona
plural run job.yaml --runtime daytona --unsafe-local
```

In `job.yaml`, set an image, snapshot, or declarative image. Daytona supports
CPU/memory and `none`, `full`, or non-empty restricted network allowlists in the
current adapter. Local Docker build contexts, pid/disk limits, persistence,
compose, read-only root, and stdin execution are unavailable. The harness runner
works around stdin by uploading its request first. Live tests require explicit
credentials and the `daytona` marker.

## Sweeps and independent attempts

```bash
plural run job.yaml --agent agent-a.yaml --agent agent-b.yaml \
  --n-attempts 3 --concurrency 8
```

Set `per_agent_concurrency` in `job.yaml` to cap one Agent independently of the
global limit. Three Agents, ten selected tasks, and two attempts plan sixty
Trials. `--retry 2` may execute an individual Trial up to three times but does
not add Trials.

## Resume, retry, cancel, and regrade

The run prints its `job_id` and stores state under `.plural/jobs`.

```bash
plural job list
plural job show JOB_ID
plural trial list JOB_ID
plural job resume JOB_ID
plural job retry JOB_ID
plural job cancel JOB_ID
plural job regrade JOB_ID
plural trial show TRIAL_ID --job JOB_ID
```

Resume and retry currently perform the same locked resume operation: successful
Trials are skipped and all other Trials execute under the configured retry
policy. Cancellation writes a marker checked before launches; an in-process
`Job.cancel()` also force-cancels active sandboxes. The CLI cancellation command
cannot reach active processes owned by another already-running CLI process.

Regrade requires a configured verifier and a successful stored result for every
Trial. It reruns the verifier over immutable stored artifacts, does not rerun
the harness, and links the new receipt with `source_receipt_hash`.

Runnable offline counterparts are in
[`examples/jobs`](https://github.com/lastlabs-ai/plural/tree/main/examples/jobs).
