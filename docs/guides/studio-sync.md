---
route: /docs/guides/studio-sync
title: "Sync revision graphs and results"
order: 300
description: "Synchronize a complete canonical schema-v2 revision graph for hosted execution, or explicitly retain execution and durable evidence on the local machine."
audience: all
---
# Sync revision graphs and results

An authenticated `plural run` validates and synchronizes the complete
schema-v2 graph before submitting a hosted Job. An explicit offline/private
run instead retains the resolved source, Agent bindings, revision lock, Trials,
TrialExecutions, append-only progress events, receipts, and artifacts in its
local Job store.

Hosted publication requires a backend that supports the same schema-v2 graph:

- Environment revisions with runtime placement, network, resources, and secrets;
- independent AgentDefinition, Task, Verifier, Harness, and Benchmark revisions;
- Task-or-Benchmark Jobs and their planned Trials;
- append-only TrialExecution and ProgressEvent records;
- human `awaiting_review` state and review submissions;
- immutable hashed artifacts, including train-only TITO.

Never flatten a cross-Environment Benchmark into one Job-level Environment.
Never move runtime policy onto a Job. Publish each pinned revision and preserve
the Task edges that define the graph.

## Hosted synchronization

```bash
plural run benchmark.yaml --agent agent.yaml --mode eval
plural run benchmark.yaml --agent agent.yaml --no-watch \
  --idempotency-key release-42
plural job watch JOB_ID --hosted --json
```

Before the first write, the CLI validates the complete graph. It then publishes
Harnesses; Environments and Verifiers; Tasks; the Benchmark when present;
Agents; and finally the Job. Shared dependencies are reused once. The Job
submission contains only the exact hosted source and Agent revision IDs
returned by that pass. Its default idempotency key is the stable local Job ID.

## Local durability

```bash
plural run benchmark.yaml --agent agent.yaml --mode eval --offline
plural job show JOB_ID
plural job watch JOB_ID --json
plural trial watch TRIAL_ID --job JOB_ID --json
```

Use `--private` for the same behavior.

Events are sanitized; secret values, hidden Environment state, and giant TITO
payloads are excluded. Artifact references include digest, media type, and size.

## Hosted compatibility

Hosted endpoints evolve independently from the package. Confirm that your
deployment advertises schema-v2 revision and event APIs before writing. A
deployment that only accepts an Environment-bound Agent or an embedded Task
list cannot represent this graph without losing
identity and must be upgraded.

Project-scoped keys already identify a project. Account-scoped keys require
`project=` or `PLURAL_PROJECT`. Use `plural job submit` only for the advanced
workflow where exact hosted revision IDs are already available; it does not
synchronize local dependencies.

See [hosted advanced workflows](../sdk/hosted-advanced.md) and
[Python Jobs](../sdk/package-jobs.md).
