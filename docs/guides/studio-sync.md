# Sync packages and results with Plural Intel

For hosted reads and object edits, start with the [object walkthrough](push-to-plural.md).
The source module is named `studio`; it connects to Plural Intel.

The existing SDK can create/update hosted `Environment` revisions, agent
templates, instances, Benchmark reports/runs, and Traces:

```python
from plural import Client, Environment

with Client(project="project-id") as client:
    env = Environment(name="support", version="0.7.4")
    created = client.create(env)
    template = client.agents.templates.create(
        name="support-agent",
        model="openai/gpt-4o-mini",
        environment_id=str(created["environment_id"]),
    )
```

Project-scoped keys already identify a project. Account-scoped keys require
`project=` or `PLURAL_PROJECT`. SDK requests use `/api/v1` derived from the
gateway base URL and send the project as `X-Project-Id` when supplied.

Environment sync sends description/readme plus a revision payload containing
instructions, fingerprint, package version, max turns, action/scorer definitions,
skills, hooks, observation/state schemas, guardrails, and context policy.
Benchmark sync stores a report and then best-effort uploads case traces with a
run-group ID. Trace upload failures in that final best-effort loop are currently
suppressed, so callers needing delivery guarantees should upload and verify
traces explicitly.

## v1 package and Job sync

The CLI can publish an `EnvironmentManifest` with `plural env push`, register a
client-orchestrated Job, append self-reported Trial results, and finalize its
Benchmark report. Local execution is still authoritative: receipts and
artifacts remain under `.plural/jobs`.

External writes are opt-in. `plural run job.yaml` runs locally without hosted
registration. Pass `--sync` to request best-effort registration and incremental
result upload; `--no-sync` is the explicit equivalent of the safe default.
Sync failure does not discard local results. Replay a completed result with:

```bash
plural job upload <job_id> --store .plural/jobs
```

The hosted API stores package metadata, locks, receipts, and report linkage; it
does not execute the sandbox workload. Receipts remain self-reported rather
than remote attestations. Organization/project listing and `plural agent list`
retain their separately documented local/backend limitations.

See [`examples/jobs/06_studio_sync.py`](https://github.com/lastlabs-ai/plural/blob/main/examples/jobs/06_studio_sync.py)
for offline payload construction and an explicitly credential-gated live call.
