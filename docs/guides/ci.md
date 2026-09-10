---
route: /docs/guides/ci
title: "Run evaluations in CI"
order: 310
description: "Start with a working local SDK evaluation or package job. Commit the source, task definitions, and intended package references. Keep credentials in your CI system's secret settings and store results as CI artifacts."
audience: all
---
# Run evaluations in CI

Start with a working local [SDK evaluation](../tutorials/sdk-walkthrough.md) or
[package job](../tutorials/cli-walkthrough.md). Commit the source, task definitions,
and intended package references. Keep credentials in your CI system's secret
settings and store results as CI artifacts.

## SDK regression checks

Keep reviewed Task, Verifier, Environment, Agent, and Benchmark revisions.
Compare only results from compatible revision graphs. Use fixed attempts and
inspect failed or awaiting-review Trials as well as aggregate reward.

## Package execution checks

Inject `PLURAL_API_KEY`, `PLURAL_GATEWAY_URL`, and, for hosted sync,
`PLURAL_PROJECT`. Start with validation:

```bash
plural env validate environment
plural harness validate harness
plural verifier validate verifier.yaml
plural task validate task.yaml
plural benchmark validate benchmark.yaml
plural run job.yaml --dry-run --format json > plan.json
```

Run the reviewed package using a Docker-capable runner:

```bash
plural run job.yaml --offline --format json > result.json
```

Each Task's Environment selects its runtime. For release evaluations, use
digest-pinned Harness sources; follow [harness packaging](harnesses.md).

To submit the reviewed graph to hosted workers instead, omit `--offline`.
`plural run` synchronizes the graph and follows events by default; use
`--no-watch` for asynchronous CI submission and provide a release-specific
`--idempotency-key` when the stable Job ID should not reuse a prior submission.

Persist `.plural/jobs`, `plan.json`, and `result.json` even on failure. These
files can contain task data and artifacts; apply the same retention and access
rules as your inputs. Avoid putting generated reports inside the hashed
source package directories.

## Exit status is not a score gate

Exit `0` means the command completed; dry runs and successful unscored runs
also return zero. Exit `1` means at least one trial did not succeed. Exit `2`
means a usage/configuration/handled error; interrupted execution returns `130`.

For scored jobs, add your own reward threshold check over the stored report.
Use `JobStore.load_spec`, `read_job_result`, and `Job.report` from the
[Python job guide](../sdk/package-jobs.md), then inspect case failures and
rewards or compare with a compatible baseline. Missing scores should fail a
quality gate that requires scoring.

## Upload without losing local evidence

When publishing to a schema-v2-compatible hosted service, verify the hosted
revision graph, Job source, TrialExecution history, event sequence, and artifact
digests. Do not edit a stored lock to make a changed Task set resume.
See [job recovery](jobs.md) and [sync](studio-sync.md).
