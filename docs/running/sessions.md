---
route: /docs/running/sessions
title: Sessions
order: 86
description: Stop an agent instance and redeploy it later from a portable session bundle.
audience: all
nav: true
nav_group: Run
---
# Sessions

A session snapshot captures everything needed to stop an agent instance and
redeploy it later as a separate instance: the agent revision, the environment
revision, the accumulated environment state, data references, and provenance
pointing back at the source job or trial.

Snapshots travel as plain directory bundles so they stay inspectable without
new formats to learn.

```text
support-session/
├── agent.yaml
├── environment.yaml
├── state.json
├── data/            # optional bundled files
└── manifest.json
```

There is deliberately no backend table and no Studio surface yet: snapshots
move as files until a Sessions home exists.

## Export from a hosted trial

Snapshot the agent, environment, and latest state of a finished trial. State
is best-effort: the newest trace's state payload when traces recorded one,
otherwise an empty object.

```bash
plural session export --trial <trial-id> --out sessions/support
```

The bundle manifest records the source job and trial ids, the export time,
and the package version, so you can always trace a redeployed instance back
to the run it came from.

## Export from local files

Bundle definitions you already have on disk. Pass `--data-dir` to copy files
into the bundle's `data/` folder.

```bash
plural session export \
  --agent agent.yaml \
  --environment environment.yaml \
  --state state.json \
  --data data/ticket.json \
  --data-dir ./data \
  --name support-session \
  --out sessions/support
```

## Redeploy as a separate instance

Import copies the bundle to a new timestamped instance directory and records
the import in `instance.json`. The original bundle is never modified, so each
import is a distinct instance you can start, stop, and diff independently.

```bash
plural session import sessions/support --dest sessions/instances
```

## Python API

```python
from plural import SessionSnapshot
from plural.sessions import export_from_parts, export_from_trial, import_bundle

snapshot = export_from_parts(
    "support",
    agent={"name": "Solver", "model": "openai/gpt-5.6-luna"},
    environment={"name": "Support"},
    state={"ticket": 42},
    data=["data/ticket.json"],
)
bundle = snapshot.save("sessions/support")

loaded = SessionSnapshot.load(bundle)
instance = import_bundle(bundle, "sessions/instances")
```
