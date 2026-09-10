---
route: /docs/guides/push-to-plural
title: "Publish schema-v2 revisions"
order: 240
description: "Local package authoring and execution do not require a hosted write. To publish, use a deployment that supports the same schema-v2 revision graph."
audience: all
---
# Publish schema-v2 revisions

Local package authoring and execution do not require a hosted write. To publish,
use a deployment that supports the same schema-v2 revision graph.

## Serialize canonically

Load authoring files through the SDK before sending them:

```python
from pathlib import Path

from plural.cli.scaffold import load_job

spec = load_job(Path("job.yaml"))
payload = spec.model_dump(mode="json", exclude_none=True)
print(spec.content_hash)
```

This resolves the discriminated Task-or-Benchmark source, AgentDefinition
revisions, Task Environment pins, weighted Verifier revisions, and Harness
packages into one canonical graph.

## Publish dependencies first

Publish immutable revisions in dependency order:

1. Environments and Harnesses.
2. Verifiers.
3. Tasks.
4. AgentDefinitions.
5. Benchmarks.
6. Jobs and their Trials.

An Agent is not Environment-bound. Each Task pins one Environment. A Benchmark
may select Tasks across Environments. Each Trial uses its Task Environment's
runtime placement, and Harness compatibility is stamped per Trial.

## Preserve execution identity

Planning expands Agent × Task × attempts. Attempts are Trials; retries append
TrialExecutions. Mirror the local append-only `ProgressEvent` sequence rather
than replacing state snapshots.

Human Verifiers create `awaiting_review` records. Review submission should
append durable review state and new events.

## Upload artifacts

Create the hosted Trace without an object-store key, then upload its TITO bytes
through the project-scoped API:

```python
trace = client.traces.create(canonical_trace, trial_id=trial_id)
artifact = client.traces.upload_tito(
    trace["id"],
    Path("tito.ndjson").read_bytes(),
)
print(artifact["tito_metadata"]["digest"])
```

The server validates every TITO record and media type, computes the SHA-256
digest, byte size, and record count, and writes to a project-and-Trace-scoped
object prefix. Repeating the upload is idempotent only when the bytes are
identical; different bytes conflict because the artifact is immutable.

In train mode TITO JSONL contains token IDs, output log probabilities and top
log probabilities, output text, assistant message, and validated input/output/
observation lengths. Eval Trials reject TITO. Do not embed TITO in Trace JSON
or send an arbitrary object key. A Trace may reuse a TrialExecution artifact
only when it links that Trial in the same project and supplies the exact key
and digest already recorded by the server.

## Compatibility check

A hosted API that requires an Environment on an Agent, stores Tasks inside an
Environment, or stores runtime on a Job cannot represent schema v2. Upgrade the
deployment rather than flattening or dropping revision edges.

Project-scoped keys already identify their project. Account-scoped keys require
an explicit project. Use idempotency keys for writes and verify returned
revision IDs, event sequence, TrialExecution count, and artifact digests.

See [hosted workflows](../sdk/hosted-advanced.md) and
[sync boundaries](studio-sync.md).
