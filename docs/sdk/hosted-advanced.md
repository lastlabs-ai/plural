# Hosted revisions and execution records

Start with [fetching and updating objects](../guides/push-to-plural.md).
This page covers advanced hosted APIs for package revisions and job records.
All calls require Plural Intel credentials and a compatible backend. Prefer the
CLI's `--sync` workflow unless you need to integrate registration yourself.

## Publish and resolve a harness revision

This example uses the files from the CLI tutorial and creates hosted records:

```python
from pathlib import Path
from plural import Client
from plural.cli.scaffold import load_harness

package = load_harness(Path("harness"))
with Client() as client:
    hosted = client.harnesses.create(name="support-loop")
    revision = client.harnesses.create_revision(hosted["id"], package)
    print(revision)
    print(client.harnesses.revisions(hosted["id"]))
    resolved = client.harnesses.resolve_revision(
        name="support-loop", digest=package.source.digest,
    )
    print(resolved["id"])
```

If the harness already exists, use `client.harnesses.get("support-loop")`
instead of `create`. `list()`, `get(ref)`, `update(ref, **fields)`, and
`delete(ref)` manage the parent record. `create_revision` publishes a validated
manifest/source description; it does not upload local source bytes to a registry.
Local source URIs are sanitized in harness revision publication.

Stamp exact hosted revisions with:

```python
from plural import Client

with Client() as client:
    client.environments.stamp_harness(
        "ENVIRONMENT_ID", "ENVIRONMENT_REVISION_ID", "HARNESS_REVISION_ID",
    )
    print(client.environments.list_stamps("ENVIRONMENT_ID", "ENVIRONMENT_REVISION_ID"))
```

Replace all three placeholders with returned hosted IDs. These are separate
from local content digests. When creating a packaged hosted template,
`client.agents.templates.create(...)` accepts `environment_revision_id`,
`harness_revision_id`, `routing`, and `package_spec` in addition to name/model.
Keep the supplied package's stamp consistent with those revisions. A declared
harness can be stamped and shown in the capability matrix; it cannot run.

## Version a benchmark definition

A benchmark revision chooses task IDs from an exact environment revision:

```python
from plural import Client

with Client() as client:
    revision = client.benchmarks.create_revision(
        "order-support-smoke",
        environment_revision_id="ENVIRONMENT_REVISION_ID",
        task_ids=["order-a100"],
        primary_metric="reward",
        description="Checks the A100 support response.",
        methodology="One fixed task and the environment's verifier.",
    )
    print(revision)
```

This creates **and promotes** the revision. Use actual task IDs belonging to
that environment revision. `package_definition=` optionally stores the exact
local `BenchmarkDefinition`; its identity must agree with the selected revision.
`revisions(ref)` lists revision records, `get_revision(ref, revision_id)` reads
one, and `promote_revision(ref, revision_id)` deliberately restores a previous
revision as current. Promoting does not rerun old results or update local files.

## Read hosted jobs and trials

```python
from plural import Client

with Client() as client:
    for job in client.jobs.list():
        print(job.get("id"), job.get("status"))
    # Replace with an ID from the list:
    job = client.jobs.get("HOSTED_JOB_ID")
    trials = client.jobs.trials("HOSTED_JOB_ID")
    print(job, trials)
```

Local `job_id` and hosted job IDs can differ; use the sync mapping/output to
associate them. `client.trials.get("HOSTED_TRIAL_ID")` reads one trial and its
append-only execution history. The CLI's `plural job show` and `trial show`
read local records, not these hosted endpoints.

## Register and upload from an integration

The lifecycle is:

1. Publish/resolve exact environment, harness, agent, and benchmark revisions.
2. Call `client.jobs.preflight(benchmark_revision_id=..., agent_revision_ids=...,
   n_attempts=..., job_spec=spec)` to check hosted compatibility.
3. Call `client.jobs.create(...)` with the same bindings, `job_spec`, and a
   stable `idempotency_key`; optionally include the local plan's `spec_hash`.
4. Read `client.jobs.trials(hosted_job_id)` and map hosted trial keys to the
   local agent/task/attempt slots. Do not substitute local trial IDs blindly.
5. Execute the local `Job`. Call `client.jobs.upload_results(hosted_job_id,
   trial_keys=..., results=...)` with matching ordered sequences. It batches
   validated results and receipts; `batch(...)` is the lower-level append API.
6. Call `client.jobs.finalize(hosted_job_id, job.report(result))` to attach the
   final report to its benchmark run.

Registration never launches hosted execution. Reuse the same idempotency key
only for the same logical registration; retain local state so interrupted
uploads can be replayed. The SDK does not automatically orchestrate these calls
when `Job.run()` executes. The CLI does so with `--sync` and `job upload`.

`client.jobs.fail(id, error_code=..., error_message=...)` marks a hosted failure.
`client.jobs.cancel(id)` and `client.trials.cancel(id)` update hosted cancellation
records; they are not remote control over arbitrary local processes. Use
`await job.cancel()` for active sandboxes owned by your in-process runner.

## Hosted traces

`client.traces.list(**params)` and `get(trace_id)` return dictionaries.
`client.traces.create(payload, ...)` ingests a serialized trace with optional
links. For a local `Trace` object, use the simpler `client.create(trace, ...)`.
See the [trace walkthrough](../tutorials/traces-and-datasets.md) for examples.

## Verify delivery

A local successful run does not prove that every hosted write completed.
Read the hosted job, trial count, and benchmark run history after syncing.
Legacy benchmark helpers upload individual case traces best-effort and suppress
those individual failures. Upload important traces explicitly when you need to
observe failures. Receipts remain self-reported integrity records, not execution
attestations. See [sync](../guides/studio-sync.md) and [limitations](../reference/limitations.md).
