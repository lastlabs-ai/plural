---
route: /docs/running/traces
title: Traces and Trials
order: 90
description: Follow what an Agent did, step by step, back to its score and the exact run, and tell a broken run apart from poor work.
audience: all
nav: false
outcome: You can inspect a recorded episode and separate execution failures from performance failures.
---
# Traces and Trials

The score tells you *how* an Agent did. The trace tells you *why*.

A **Trial** is one Agent's attempt at one Task. A **Trace** is the record of what
happened during that attempt: the model calls, the actions, what the Agent saw
back, and other events captured by the Harness or a tracing integration.

The Trial result adds the score and a receipt of the exact inputs. Keep both.

## Inspect one local run

After the [quickstart](../getting-started.md), copy the Job and Trial IDs from its
result:

```bash
plural job show JOB_ID
plural trial show TRIAL_ID
```

A local run records its Job under `.plural/jobs/` at the project root, whichever
project directory you ran it from. `plural trial show` prints the paths of the
Trial's artifacts and logs. The main files are:

```text
.plural/jobs/JOB_ID/
  run.json                            pinned version and content hash of every input
  config.json                         resolved Job definition
  lock.json                           revision lock
  events.jsonl                        progress events
  result.json                         Job result
  trials/TRIAL_ID/
    result.json                       current Trial result
    selected.json                     selected successful execution, if any
    executions/0/
      receipt.json                    identities and artifact hashes
      result.json                     this execution's result
      logs/                           captured execution and verifier logs
      artifacts/
        manifest.json                 paths, hashes, media types, sizes, and roles
```

Execution folders are numbered from zero, and later retries add their own.
Planned attempt numbers in the Trial start at one; they are different from
execution numbers. See [Artifacts and evidence](artifacts.md) for every file.

## Read the support episode

In the selected execution's `artifacts/`, open `trajectory.json`. It shows the
native loop's turns: each model message, its tool calls, and the observation each
call returned, with token counts and cost. `result.json` records the final
response. Compare what the Agent saw after each action with the
`correct-category.correct_category` score in the Trial result's `scores`.

`episode.jsonl` is the underlying record, including the requests sent to the
model. It is a JSONL log of the interaction, not a full trace in the tracing SDK's
format, and its trace ID alone does not upload the record to Plural Intel. Check
what your Harness or tracing integration actually records.

`trajectory.json` is written as [ATIF](https://docs.harborframework.com/core-concepts/agents/atif),
Harbor's Agent Trajectory Interchange Format (`ATIF-v1.7`). That is the document
to share with other tools. Plural derives it from the episode record, so it has
every model call and step in order. Each step's `metrics.cost_usd` is the exact
amount the gateway billed for that call, and `metrics.extra.request_id` is the
gateway's ID for it; a cost the gateway did not return stays empty rather than
estimated. Rewards and Verifier scores stay beside the trajectory; neither
appears in a step.

When available, the final Environment State, Observation, rendering, trajectory,
and Verifier results are copied into the execution artifacts and listed in the
manifest. Missing runtime data remains absent. Preserve additional files
explicitly rather than assuming every runtime file survives teardown.

## Diagnose in order

A low score does not always mean poor work. Sometimes the run itself broke. Work
through these checks in order:

1. Check the execution status. If the process failed, inspect the runtime error before judging the Agent's reasoning.
2. Check the Task and revision identities. Confirm this is the world and scoring rule you intended to test.
3. Read the first observation and the actions that followed. Look for missing information, repeated tool errors, or a misunderstood response.
4. Check why the episode stopped. The Trial's `stop_reason` says whether the Environment ended it, the Agent finished, or a turn, time, or cost budget cut it short; see [Trials](trials.md#how-the-episode-ended).
5. Compare the final State and artifacts with the Verifier's feedback. A plausible answer may still leave the world in the wrong state.

A Verifier failure may mean evidence was missing rather than that the Agent
performed poorly. Keep execution completeness visible when summarizing a
Benchmark.

## Read hosted records

For a tracked or hosted Job, open it in the web app under Jobs, choose a Trial,
and follow its trace and artifact references. Hosted records depend on evidence
being uploaded or ingested; a local file path cannot be opened by another user's
browser.

Use the Trial receipt to identify the Environment, Task, Agent, Harness, and
Verifier revisions. A receipt's `trust` field says how the result was produced,
and a local run reports `self_reported`. Artifact hashes identify content, but do
not independently prove the truth of every event recorded by a custom Harness.

## Capture your own application

Plural's tracing SDK can record model calls and application events outside a Job.
This is useful when you want to turn real production behavior into a repeatable
evaluation. Export spans to an existing collector through
[OpenTelemetry](../reference/integrations.md#plural-intel-ci-and-opentelemetry),
and keep the [evaluation contract](../architecture/evaluation-contract.md) as the
record-format reference.

Capture useful evidence, not only final prose. Record tool inputs and outcomes,
relevant observations, model identity, errors, and the artifacts your scoring rule
needs. Fields such as usage and latency depend on the integration actually
recording them; do not infer them from an empty trace.

## Reuse evidence responsibly

Reading a stored episode does not rerun the model. Re-executing the Task creates
new behavior and may incur costs. Do not promise deterministic replay of remote
services or stochastic models because their earlier trace exists.

Selected traces can become datasets or training examples. Preserve their Task
provenance, scoring status, and data permissions. Ordinary message transcripts
cannot substitute for the exact token records required by train mode. See
[Training](training.md).

Treat captured files according to their contents. State fields hidden from the
Agent are not automatically removed from custom artifacts, logs, or anything your
code writes. The [verifiers guide](../project/verifiers.md) explains Episode
scoring boundaries.

If the episode needs a human score, continue to [Reviews](reviews.md).
