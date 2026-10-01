---
route: /docs/running/trials
title: Trials and trajectories
order: 85
description: One Trial is one Agent's attempt at one Task. See how it went, step by step, what it cost, why it stopped, and why it scored what it did.
audience: all
nav: true
nav_group: Run
---
# Trials and trajectories

A **Trial** is one attempt: one Agent, one Task, one try. In Wordle, it is one
contestant playing one game once. Every Trial keeps a full record of that attempt,
so you can see what the Agent did, what it cost, why it stopped, and why it scored
what it did.

Trials add up fast. Two Agents evaluated on three Tasks create six Trials. A second
planned attempt doubles that to twelve.

## Attempts and executions

Sometimes an attempt fails for a reason that has nothing to do with the Agent, such
as the model provider timing out. Plural can retry it. The retry is another
**execution** of the same Trial, not a new Trial:

```text
Job
└── Trial (attempt=1)
    ├── execution 0  failed: timeout
    └── execution 1  succeeded and selected
```

This keeps your results honest: a passing provider failure is never counted as an
extra sample. A Trial's ID stays the same across retries, and executions are
numbered from zero with an `execution_id`.

## Status and inspection

To see how a run went, start with the Job, then open one Trial:

```bash
plural job show JOB_ID
plural trial show TRIAL_ID
plural trial show TRIAL_ID --follow
```

`plural job show` lists each Trial's Task, status, and score. `plural trial show`
prints one Trial's result, each Verifier's score and feedback, and the paths of
its artifacts and logs. Both look for a local record first and then ask the
hosted project. `--follow` streams progress until the Trial finishes. For a
tracked or hosted Job, you can see the same Trials in the web app under Jobs.

A Trial moves through these states: planned, queued, provisioning, running,
verifying, awaiting_review, and then a terminal state. It waits in
`awaiting_review` only when a person needs to grade it; see [Reviews](reviews.md).

Progress events are append-only status updates, written to the Job's
`events.jsonl`. They carry status changes, not model inputs or outputs, and are
for monitoring, not a replacement for the receipt and artifacts.

## Interpret results

A low score can mean the Agent did poor work, or that the run itself broke. Check
them separately, in this order:

1. Confirm the execution succeeded and the expected artifacts exist.
2. Confirm the receipt's pins and the model endpoint that actually ran.
3. Read the actions, tool errors, observations, and stop reason.
4. Read each Verifier's score, criterion scores, evidence, and feedback.
5. Compare score, cost, and latency only across compatible Benchmark pins.

`plural trial rerun TRIAL_ID` runs one Trial again with its pinned inputs as a
new one-Trial Job. Rerunning a stochastic model creates new behavior. Stored
trajectories support inspection and import; they do not promise deterministic
replay.

## How the episode ended

Alongside the score, each Trial records why the attempt stopped. Did the game end,
did the Agent decide it was done, or did it run out of turns, time, or money? That
is the `stop_reason`. Read it before concluding an Agent failed the work: a
truncated Trial still has a trajectory and Verifier results, but it may have
been cut short.

`stop_reason` takes one of the values in `plural.STOP_REASONS`:

| Value | Meaning |
| --- | --- |
| `environment_terminated` | The world declared the Task over. |
| `environment_truncated` | The world could not continue. |
| `agent_finished`, `agent_response` | The Agent chose to stop. |
| `max_turns`, `max_seconds`, `max_cost` | A budget cut the run short. |
| `error` | The run failed. |

The Trial also records whether the Environment `terminated` or `truncated` the
run, and the total per-step reward, which a hosted Trial shows as
`step_reward_total`. The reward total is recorded for training and never
contributes to the score. See
[How an episode ends](../project/environments.md#how-an-episode-ends).

Plural's native loop always reports these values. A custom Harness reports them
by returning `HarnessResult(metadata={"stop_reason": ..., "terminated": ...,
"truncated": ..., "turns": ..., "total_reward": ...})`; without them, its Trials
have no stop reason, and a value not in `plural.STOP_REASONS` is treated as
unreported.

## Trajectories

A **trajectory** is the step-by-step story of an attempt: the messages, reasoning
when the model supplies it, the actions, tool results, observations, per-step
rewards, cost, and timing. It is where you look to understand *why* a Trial scored
what it did.

Harnesses may emit different native formats. Plural preserves the original and
derives `atif-trajectory.json`, an ATIF document of the Agent's turns, from the
[episode record](#the-episode-record). `normalize_trajectory` reads any of these
formats into one event list:

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

This section and the ones after it are for readers who want the exact record
formats.

When a Harness runs through `HarnessAgent` and `HarnessEnvironment`, Plural
itself records the episode in `episode.jsonl`, whatever the Harness writes. Each
line is one record with a `schema` field, a `sequence` that orders the episode, a
`turn`, `started_at`, `ended_at`, and `duration_ms`. There are three kinds:

- `environment.reset` has the first `observation`, `info`, and `view`.
- `environment.step` has the `action` and its `arguments`, the `observation`
  returned to the Harness, and the `reward`, `terminated`, `truncated`, `info`,
  and `view` of the transition.
- `model.call` has the `model`, the request `messages`, the offered `tools`,
  and the response `text`, `tool_calls`, `finish_reason`, and `usage`. Only
  messages that are new since the previous call are stored; `messages_offset`
  gives their position in the full request.

The `schema` value is `"plural.episode/v1"`. A model call opens a turn, and the
steps it causes belong to that turn. A Harness that never calls a model gets one
turn per step. A failed call or step is recorded with its `error`.

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
