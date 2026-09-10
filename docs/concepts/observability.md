# Observability

A trial produces one episode `Trace` at schema version **2.0.0**. There is
no v1 migration.

## Turns

Each `Turn` is one model step: the observation the policy saw, optional
reasoning blocks, parsed actions, `ActionStep` rows, reward events, and
`started_at` / `ended_at`.

`ActionStep.source` is `environment_native`, `harness`, or `model_text`.
The value the environment returned is `observation`.

The trace also records `harness`, `granted_capabilities`,
`denied_capabilities`, `capability_denials`, `agent_template_id`,
`agent_instance_id`, `job_id`, and `trial_id`.

```python
for turn in trace.turns():
    for action in turn.actions:
        print(action.source, action.name, action.observation)
```

`trace.turn_rewards(source=...)` and `trace.returns(gamma=...)` flatten
turns for training. Sources are `outcome`, `events`, or `both`.

## Hosted view

Plural Intel `/trials/[id]` renders the turn timeline, a latency waterfall,
inline capability denials, and a direct `usage_event` lookup.
