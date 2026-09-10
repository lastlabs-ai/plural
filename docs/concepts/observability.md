---
route: /docs/concepts/observability
title: "Observability"
order: 170
description: "A trial produces one episode Trace at schema version 3.0.0. There is no v1 migration."
audience: all
---
# Observability

A trial produces one episode `Trace` at schema version **3.0.0**. There is
no v1 migration.

## Turns

Each `Turn` is one model step: the observation the policy saw, optional
reasoning blocks, parsed actions, `ActionStep` rows, reward events, and
`started_at` / `ended_at`.

`ActionStep.source` is `environment_native`, `harness`, or `model_text`.
The value the environment returned is `observation`.

The trace also records `harness`, granted/denied capabilities,
`capability_denials`, Agent/Task/Environment revision digests, `job_id`,
`trial_id`, Verifier outcomes, and hashed artifact references.

```python
for turn in trace.turns():
    for action in turn.actions:
        print(action.source, action.name, action.observation)
```

`trace.turn_rewards(source=...)` and `trace.returns(gamma=...)` flatten
turns for analysis. Sources are `outcome`, `events`, or `both`. Environment
Rewarders and exact TITO capture run only in train mode. TITO token arrays,
log probabilities/top log probabilities, text, assistant message, and validated
lengths live in immutable artifacts rather than the Trace JSON.

## Live events

Jobs and TrialExecutions append sanitized `ProgressEvent` records for planning,
provisioning, model/action activity, verification, retries, human
`awaiting_review`, and terminal states. Replay or follow them with
`plural job watch` and `plural trial watch`.

## Hosted view

Plural Intel `/trials/[id]` renders the turn timeline, a latency waterfall,
inline capability denials, and a direct `usage_event` lookup.
