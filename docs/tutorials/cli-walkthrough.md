# Run your first package job

This walkthrough uses the installed `plural` command. You will create a small
support-answer package, inspect its plan, run a model, and find its saved result.
No Python package source changes are required. Commands assume you are in the
project folder from [setup](../getting-started/setup.md).

**Before you start:** configure `PLURAL_API_KEY` and `PLURAL_GATEWAY_URL` for
model execution. Scaffolding and dry runs do not need credentials. Actual runs
make paid model calls. This first job has no verifier, so completion is not a
quality score; the next tutorial adds verification.

## 1. Create an environment and edit its task

```bash
plural env init environment --name support
```

This creates four files:

- `environment.yaml`: instructions, commands, limits, and package settings.
- `tasks.jsonl`: one JSON task per line.
- `environment.py`: a starting Python subclass, not automatically executed by
  the package runner.
- `Dockerfile`: a starting runtime image for container jobs.

Replace `environment/tasks.jsonl` with:

```json
{"task_id":"order-a100","input":"Order A100 has shipped. Reply with a short customer-friendly status update."}
```

You can add another public task from the terminal:

```bash
plural env task add --environment environment --id order-a200 \
  --input 'Order A200 is processing. Reply with a short customer-friendly status update.'
plural env task list --environment environment
plural env validate environment
```

Leave `tasks: []` in the YAML to use `tasks.jsonl`. A nonempty inline `tasks`
array takes precedence. Task listing is for authors: it is not a sanitized
agent-facing payload and may include `verifier_input` if you add it later.

## 2. Create and allow the harness

```bash
plural harness init harness --name support-loop
plural harness validate harness
plural harness inspect harness
plural harness add harness --environment environment
plural env harness list --environment environment
```

The generated `chat.v1` harness asks the model for a response and writes
`result.json` and `trajectory.jsonl`. It is a working model-backed scaffold,
not an offline fake. `harness add` records the exact allowed revision in the
environment. `plural env harness add harness --environment environment` is
another local-package spelling of the same operation.

## 3. Bind an agent and choose the tasks

```bash
plural benchmark init benchmark.yaml --name support-smoke --environment environment
plural agent init agent.yaml --name candidate --model openai/gpt-4o-mini \
  --environment environment --harness harness --secret PLURAL_API_KEY
plural benchmark validate benchmark.yaml --environment environment
plural benchmark show benchmark.yaml
plural agent show agent.yaml
```

`benchmark.yaml` selects the current task IDs in order. `agent.yaml` binds the
model, environment identity, and harness identity. `--secret` grants a named
secret from your shell; it does not store its value in the agent file.

For direct provider access, change the secret grant and model identifier as
explained in [setup](../getting-started/setup.md). Changing only the model name
does not configure a different endpoint.

## 4. Make and inspect a job

```bash
plural job init job.yaml --environment environment \
  --benchmark benchmark.yaml --agent agent.yaml
plural run job.yaml --dry-run --format json
plural run job.yaml --print-config --format yaml
plural trial list job.yaml
```

The dry run should show two trials and print their IDs plus a `job_id`. It checks
configuration and computes the execution lock, but does not call the model or
start a sandbox. It is not a runtime health check; use `runtime doctor` next.

Paths in `job.yaml` resolve relative to that file. Keep these generated files
at the same project level for this tutorial.

## 5. Run locally or in Docker

For this trusted, unverified development example:

```bash
plural runtime doctor local
plural run job.yaml --runtime local --unsafe-local --format json
```

The local provider executes code with your user account's access. The explicit
flag acknowledges that it is not a sandbox. A job with an isolated verifier
cannot run on this provider.

If Docker is installed and running:

```bash
plural runtime list
plural runtime show docker
plural runtime doctor docker
plural run job.yaml --runtime docker --unsafe-local --format json
```

Here `--unsafe-local` also permits the mutable local harness source used by the
scaffold. It does not change Docker into the local provider. For an immutable
release, build an archive and bind its digest using the [harness guide](../guides/harnesses.md).
The CLI uses the environment directory as the default Docker build context.

The final result is JSON on stdout; progress goes to stderr. The run stores its
configuration, lock, results, receipts, logs, and artifacts in `.plural/jobs`.
Do not expect a reward from this job: no verifier has been configured.

## 6. Inspect a completed run

Replace `JOB_ID` and `TRIAL_ID` with values printed by your run:

```bash
plural job list
plural job show JOB_ID
plural trial list JOB_ID
plural trial show TRIAL_ID --job JOB_ID
```

Use the **job ID**, rather than `job.yaml`, to inspect persisted trial results.
A file path shows the plan. Follow artifact paths under that job's store to read
`result.json` and `trajectory.jsonl`; receipts identify recorded hashes and
runtime controls. `status: succeeded` means execution completed successfully.

## 7. Compare another model

```bash
plural agent init agent-b.yaml --name candidate-b --model anthropic/claude-sonnet-4 \
  --environment environment --harness harness --secret PLURAL_API_KEY
plural run job.yaml --agent agent.yaml --agent agent-b.yaml \
  --n-attempts 2 --concurrency 2 --dry-run
```

The plan now has eight trials. Remove `--dry-run` and add the runtime flags
from step 5 to execute. Your gateway must support both model IDs. Add a verifier
before using this as a scored model comparison.

## 8. Change the environment deliberately

Edit instructions or tasks first, then recreate references to the new identity:

```bash
plural env validate environment
plural benchmark init benchmark.yaml --name support-smoke --environment environment --force
plural agent init agent.yaml --name candidate --model openai/gpt-4o-mini \
  --environment environment --harness harness --secret PLURAL_API_KEY --force
plural run job.yaml --dry-run
```

`--force` replaces the named scaffold file; preserve custom edits before using
it. Recreate `agent-b.yaml` too before including it in another sweep. For a
harness source change, re-add its new binding **before** recreating benchmark
and agent files. The path-based job file still points to those filenames.
An updated package starts a new comparison; it does not rewrite an old job lock.

## 9. Publish when ready

```bash
plural env push environment
plural run job.yaml --runtime docker --unsafe-local --sync
```

These commands write to your Plural Intel project. Without `--sync`, execution
results remain local. If upload fails, the local results remain available:

```bash
plural job upload JOB_ID
```

Sync registers and uploads a locally executed job; it does not ask Plural Intel
to run the workload. For hosted reads and metadata updates, use the
[SDK object walkthrough](../guides/push-to-plural.md). There is no general CLI
`pull` command; `plural agent list` lists local `agent.yaml` files, not hosted agents.

## Next

[Add tools and an isolated verifier](package-tools.md), then explore
[retries, resume, cancellation, and Daytona](../guides/jobs.md).
The [CLI reference](../reference/cli-commands.md) documents every command option.
