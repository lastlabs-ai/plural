---
route: /docs/running/trials
title: Trials and trajectories
order: 85
description: Understand Trial identity, independent attempts, retry executions, normalized trajectories, status, and inspection.
audience: all
nav: true
nav_group: Run
---
# Trials and trajectories

A Trial is one Agent completing one Task once. For example, two Agents evaluated on three Tasks create six Trials. A second planned attempt doubles that to twelve.

A Trial’s ID is stable across
Runtime retries. A Trial execution is one actual attempt to run that Trial and
uses a zero-based `execution_id`.

```text
Job
└── Trial (attempt=1)
    ├── execution 0  failed: timeout
    └── execution 1  succeeded and selected
```

This distinction prevents a transient provider failure from being counted as a
new statistical sample.

## Status and inspection

Trials move through planned, queued, provisioning, running, verifying,
awaiting_review, and terminal states. Inspect local records with:

```bash
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID
plural job show JOB_ID
```

Progress events are append-only and sanitized. They are for monitoring, not a
replacement for the receipt and artifacts.

## Trajectories

A trajectory records behavior such as messages, reasoning when supplied,
actions, tool results, observations, per-step rewards, cost, and timing.
Harnesses may emit different native formats. Plural preserves the original and
writes `trajectory.normalized.json` when it can normalize a captured trajectory.

```python
from pathlib import Path
from plural import normalize_trajectory

trajectory = normalize_trajectory(Path("trajectory.jsonl"))
for event in trajectory.events:
    print(event.sequence, event.kind)
```

Normalization is tolerant and does not manufacture absent data. A normalized
trajectory is not necessarily a full tracing-SDK `Trace`, and a `trace_id`
alone does not upload local files.

## How the episode ended

Alongside the score, each Trial records why the episode stopped: a
`stop_reason`, whether the Environment `terminated` or `truncated` the run, and
the total per-step reward. A truncated Trial still has a trajectory and Verifier
results, so read the stop reason before concluding an agent failed the work.

`stop_reason` distinguishes a world that declared the Task over
(`environment_terminated`), an agent that chose to stop (`agent_finished`,
`agent_response`), and a budget that cut the run short (`max_turns`,
`max_seconds`, `max_cost`). See
[How an episode ends](../project/environments.md#how-an-episode-ends).

## Interpret results

Separate execution completeness from quality:

1. Confirm the execution succeeded and the expected artifacts exist.
2. Confirm receipt pins and actual model endpoint.
3. Read actions, tool errors, observations, and stop reason.
4. Read each Verifier's score, criterion scores, evidence, and feedback.
5. Compare score, cost, and latency only across compatible Benchmark pins.

Rerunning a stochastic model creates new behavior. Stored trajectories support
inspection and import; they do not promise deterministic replay.
