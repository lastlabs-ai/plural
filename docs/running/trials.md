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
awaiting_review, and terminal states. Inspect them with:

```bash
plural job show JOB_ID
plural trial show TRIAL_ID
plural trial show TRIAL_ID --follow
```

`plural job show` lists each Trial's Task, status, and score. `plural trial show`
prints one Trial's result, each Verifier's score and feedback, and the paths of
its artifacts and logs. Both look for a local record first and then ask the
hosted project. `--follow` streams progress until the Trial finishes.

Progress events are append-only status updates, written to the Job's
`events.jsonl`. They carry status changes, not model inputs or outputs, and are
for monitoring, not a replacement for the receipt and artifacts.

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

Normalization is tolerant and does not invent missing data. A normalized
trajectory is not a full [`Trace`](traces.md), and a `trace_id` alone does not
upload local files.

## The episode record

When a Harness runs through `HarnessAgent` and `HarnessEnvironment`, Plural
itself records the episode in `episode.jsonl`, whatever the Harness writes. Each
line is one record with `schema: "plural.episode/v1"`, a `sequence` that orders
the episode, a `turn`, `started_at`, `ended_at`, and `duration_ms`. There are
three kinds:

- `environment.reset` has the first `observation`, `info`, and `view`.
- `environment.step` has the `action` and its `arguments`, the `observation`
  returned to the Harness, and the `reward`, `terminated`, `truncated`, `info`,
  and `view` of the transition.
- `model.call` has the `model`, the request `messages`, the offered `tools`,
  and the response `text`, `tool_calls`, `finish_reason`, and `usage`. Only
  messages that are new since the previous call are stored; `messages_offset`
  gives their position in the full request.

A model call opens a turn, and the steps it causes belong to that turn. A
Harness that never calls a model gets one turn per step. A failed call or step
is recorded with its `error`.

Of a step's fields, only the observation went to the Harness and therefore
possibly to the model. The reward, the episode flags, `info`, and the view are
for scoring, training, and display. The hosted run viewer labels each field
this way.

## Usage, cost, and timing

`usage` on a model call follows one shape for every provider. `input_tokens`
counts all prompt tokens, including cached ones, and `cached_input_tokens` is
the part served from a cache. It is never added to the input count. Anthropic
cache reads and writes are folded into `input_tokens` to match. A count or a
cost the provider did not report is `null`, not zero, and totals record how
many calls left each one out.

The receipt's `phases` list the measured phases of an execution:
`agent_setup`, `environment_setup`, `agent_execution`, `artifact_collection`,
`verification`, and `cleanup`, each with `started_at` and `completed_at`.
Phases can repeat and overlap, so their sum is the work done, not the wall
clock time. Each Verifier result also carries its own `started_at` and
`completed_at`.

## Publish a local run to a hosted Job

`plural job push` and `plural run --track` do this for you. From Python,
`plural.execution.report.publish_job` reports each execution of a local Job to
a hosted Job planned from the same pushed resources. It matches Trials by Task,
Agent name, and attempt, and replays each execution through the hosted worker
API: the episode as progress events, logs, artifacts, usage, phases, and
Verifier results. Failed executions are published too, so the hosted Trial keeps
their retries and cost.

```python
from pathlib import Path

from plural.execution.report import publish_job
from plural.execution.store import JobStore
from plural.studio import Studio

studio = Studio(api_root="https://pluralintel.com/api/v1", token=TOKEN, project=PROJECT_ID)
publish_job(studio, JobStore(Path(".plural/jobs")), LOCAL_JOB_ID, HOSTED_JOB_ID)
```

Publishing is idempotent: running it again records nothing new, including for
executions a `HostedTracker` already reported while the Job ran. It refuses an
execution whose Environment or Verifier content hash differs from the hosted
pins.

## How the episode ended

Alongside the score, each Trial records why the episode stopped: a
`stop_reason`, whether the Environment `terminated` or `truncated` the run, and
the total per-step reward, which a hosted Trial shows as `step_reward_total`.
The reward total is recorded for training and never contributes to the score. A
truncated Trial still has a trajectory and Verifier results, so read the stop
reason before concluding an agent failed the work.

`stop_reason` takes one of the values in `plural.STOP_REASONS`. It distinguishes
a world that declared the Task over (`environment_terminated`) or could not
continue (`environment_truncated`), an agent that chose to stop
(`agent_finished`, `agent_response`), a budget that cut the run short
(`max_turns`, `max_seconds`, `max_cost`), and a run that failed (`error`). See
[How an episode ends](../project/environments.md#how-an-episode-ends).

Plural's native loop always reports these values. A custom Harness reports them
by returning `HarnessResult(metadata={"stop_reason": ..., "terminated": ...,
"truncated": ..., "turns": ..., "total_reward": ...})`; without them, its Trials
have no stop reason, and a value not in `plural.STOP_REASONS` is treated as
unreported.

## Interpret results

Separate execution completeness from quality:

1. Confirm the execution succeeded and the expected artifacts exist.
2. Confirm receipt pins and actual model endpoint.
3. Read actions, tool errors, observations, and stop reason.
4. Read each Verifier's score, criterion scores, evidence, and feedback.
5. Compare score, cost, and latency only across compatible Benchmark pins.

`plural trial rerun TRIAL_ID` runs one Trial again with its pinned inputs as a
new one-Trial Job. Rerunning a stochastic model creates new behavior. Stored
trajectories support inspection and import; they do not promise deterministic
replay.
