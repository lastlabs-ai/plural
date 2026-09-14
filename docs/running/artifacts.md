---
route: /docs/running/artifacts
title: Artifacts and evidence
order: 88
description: Inspect immutable receipts, logs, manifests, state, observations, renderings, trajectories, verifier evidence, and imported output.
audience: all
nav: true
nav_group: Run
---
# Artifacts and evidence

An authored `Resource` is an Environment or Task input descriptor. A run
artifact is an output file captured from one execution. They have different
lifecycles and should not both be called “resources.”

## Local layout

```text
.plural/jobs/JOB_ID/
  config.json
  lock.json
  events.jsonl
  result.json
  trials/TRIAL_ID/
    selected.json
    result.json
    executions/0/
      receipt.json
      result.json
      logs/
      artifacts/
        manifest.json
        trajectory.jsonl
        trajectory.normalized.json
        state.json
        observation.json
        view.json
        verifier-results.json
```

Only files actually produced or captured are present. The manifest records
each artifact's path, SHA-256, media type, byte size, and optional role.
Receipts bind those hashes to the exact Task, Benchmark, model endpoint,
Environment, Verifiers, Agent, Harness, mode, Runtime, timing, and cost.

Execution receipts, logs, manifests, and artifact bytes are immutable. A retry
appends a directory; it does not overwrite the failed execution. A Human
review advances selected execution, Trial, and Job result projections while
leaving that captured evidence unchanged.

## Episode scoring

A Verifier function receives the completed Episode: final Observation, full
State, trajectory, artifacts, and usage. Command Verifiers currently receive
all captured artifacts in their scoring workspace. Isolate untrusted scoring
code with its own `VerifierRuntime`.

## Logs, secrets, and trust

Plural redacts exact Agent-granted Harness credential values from managed
Harness logs and exact model API-key values from managed Verifier logs. Event
redaction applies only when the writer is given secret values. Plural cannot
prevent transformed exfiltration or guarantee redaction in custom artifacts,
external systems, or arbitrary persisted content. Hidden State is not a secret
store.

Receipts are unsigned and currently report `self_reported` trust. Hashes detect
content changes; they do not independently prove that a custom Harness recorded
truthful behavior.

## Import and derive

Normalize a JSON/JSONL trajectory with `normalize_trajectory(...)` without
changing the source. The bundled Mercor adapter can import a Mercor Trial
directory:

```python
from pathlib import Path
from plural.importers import import_mercor_trial

record = import_mercor_trial(
    Path("mercor-trial"),
    destination=Path("imported-trial"),
)
print(record.provenance)
```

Imported receipts are marked `imported_unverified`; import does not upgrade
their trust. There is no general CLI command that imports arbitrary run
directories.

Write analyses and exports as new derived files. Never edit a captured
artifact and retain its old manifest or receipt.
