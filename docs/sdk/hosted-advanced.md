---
route: /docs/sdk/hosted-advanced
title: "Hosted schema-v2 revisions and execution records"
order: 100
description: "The Python package can always author, validate, plan, execute, and inspect the schema-v2 graph locally. Hosted writes require a compatible deployment; inspect its advertised API before integrating."
audience: all
---
# Hosted schema-v2 revisions and execution records

The Python package can always author, validate, plan, execute, and inspect the
schema-v2 graph locally. Hosted writes require a compatible deployment; inspect
its advertised API before integrating.

## Publish the revision graph

Publish immutable records in dependency order:

1. Harness and Environment revisions.
2. Deterministic, agent, or human Verifier revisions.
3. Task revisions, each pinning one Environment and weighted Verifiers.
4. Environment-independent AgentDefinition revisions.
5. Benchmark revisions selecting ordered Tasks across any Environments.
6. A Job whose discriminated source is one Task or Benchmark.

Preserve complete digests and server revision IDs. Harness compatibility and
the capability stamp are per Trial against the Task's Environment; do not store
an Environment binding on the Agent.

The resource APIs expose both stages explicitly:

```python
draft = client.environments.push(environment)
parent = client.environments.get("environment-slug")
published = client.environments.publish_revision(
    parent["id"], draft["id"]
)
```

Use the same `push(...)` then `publish_revision(parent_id, revision_id)` flow
for Tasks, Verifiers, Agents, Harnesses, and Benchmarks. Task push requires
`environment_revision_id` and aligned `verifier_revision_ids`; Benchmark push
requires aligned `task_revision_ids`.

## Submit a hosted Job

Use the canonical `JobSpec` plus hosted revision IDs:

```python
from pathlib import Path

from plural.cli.scaffold import load_job

spec = load_job(Path("job.yaml"))
job = client.jobs.submit(
    spec,
    source_revision_id="benchmark_revision_id",
    agent_revision_ids=["agent_revision_id"],
    idempotency_key="release-2026-09-10",
)
```

Planning expands Agent × Task × attempts. Each Trial carries its Task
Environment's runtime provider and placement. Global and per-runtime
concurrency are scheduling limits only. A retry appends a TrialExecution under
the same Trial instead of creating a new attempt.

## Stream durable events

```python
from pathlib import Path

from plural import JobStore

store = JobStore(Path(".plural/jobs"))
for event in store.events("JOB_ID", after=0, follow=False):
    print(event.model_dump_json(exclude_none=True))
```

When mirroring events to a hosted API, preserve sequence order and idempotency.
Human Verifiers produce `awaiting_review`; review submission appends new state
without rewriting prior events.

## Artifacts and modes

Eval mode runs final Verifiers but disables Rewarders and TITO. Train enables
Environment Rewarders and fails preflight unless exact TITO capture is
supported.

TITO records include token IDs, aligned output log probabilities and top log
probabilities, output text, assistant message, and validated input/output/
observation lengths. Upload the immutable artifact bytes and their SHA-256
reference. Do not embed these arrays into Trace or progress-event JSON.

## Delivery checks

A successful local Job does not prove hosted delivery. Verify the hosted Job,
Trial count, TrialExecution history, latest event sequence, human-review state,
and every artifact digest after upload. Receipts are integrity records, not
signed execution attestations.

See [sync boundaries](../guides/studio-sync.md) and
[package Job execution](package-jobs.md).
