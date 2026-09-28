---
route: /docs/running/sessions
title: Sessions
order: 86
description: Save where an Agent left off as a portable folder, then pick it up again later as a separate copy, with a record of the run it came from.
audience: all
nav: true
nav_group: Run
---
# Sessions

A **session** is a saved snapshot of an Agent at work: which Agent it was, which
world it was in, and how that world looked when you stopped. Think of it as saving
a game. You can stop an Agent instance and later start a fresh copy exactly where
it left off.

A session snapshot captures everything needed to redeploy it later as a separate
instance: the Agent revision, the Environment revision, the accumulated
Environment State, data references, and provenance pointing back at the Job or
Trial it came from.

## What a session looks like

A snapshot is an ordinary folder, so you can read it and compare two of them with
everyday tools:

```text
support-session/
├── agent.yaml
├── environment.yaml
├── state.json
├── data/            # optional bundled files
└── manifest.json
```

Sessions are files only. The hosted project does not store them and the web
app has no page for them yet, so keep bundles wherever you keep other project
files.

## Export from a hosted trial

Save the Agent, Environment, and latest State of a finished hosted Trial. This
needs `plural auth login` and the Trial's project selected with
`plural auth scope --project <name>`.

```bash
plural session export --trial <trial-id> --out sessions/support
```

The State is the one recorded by the Trial's newest trace, or an empty object
when no trace recorded one. The bundle's manifest records the source Job and
Trial IDs, the export time, and the package version, so you can always trace a
redeployed instance back to the run it came from.

## Export from local files

You can also bundle files you already have on disk, such as the manifests in your
project. `--data` records a data reference by name without copying it; pass
`--data-dir` to copy a directory into the bundle's `data/` folder.

```bash
plural session export \
  --agent agents/support-assistant/agent.yaml \
  --environment environments/support-queue/environment.yaml \
  --state state.json \
  --data data/ticket.json \
  --data-dir ./data \
  --name support-session \
  --out sessions/support
```

## Redeploy as a separate instance

Importing makes a new copy to work from. It copies the bundle to a new timestamped
instance folder, such as
`sessions/instances/support-session-20260923-202646/`, and records the import in
`instance.json`. The original bundle is never modified, so each import is a
distinct instance you can start, stop, and compare independently.

```bash
plural session import sessions/support --dest sessions/instances
```

## Python API

The same operations are available from Python:

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
