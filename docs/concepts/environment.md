# Environment

The environment is the primary object. It owns instructions, native
actions, observation and state schemas, guardrails, resources, harness
policy, and runtime.

## Python API

`Environment.step()` is framework-owned. It records one `Turn` and advances
the lifecycle. The default `apply_action` hook dispatches to `@action`
methods. A model response without tool calls becomes
`ParsedAction(name="respond", source="model_text")` and defaults to
`policy_stop`.

Do not call `record_turn()` or `finish_turn()` from `apply_action`. Custom
`ActionResult.info` merges into `StepResult.info` but cannot replace
canonical `turn`, `stop_reason`, or action-error values.

Step rewards become `Turn.reward_events`. End-of-episode scorers become
`trace.outcome.reward`. Late labels use `trace.credit(...)`.

```python
trace.transitions(source="events")  # Turn.reward_events only
```

## Package manifest

`EnvironmentManifest` carries `actions`, `observation_schema`,
`state_schema`, `guardrails`, `resources`, `runtime`, and
`harness_policy`. Container and network no longer live on `JobSpec`.

```bash
plural env capabilities ./env
plural env action list --environment ./env
plural env resource list --environment ./env
```

## Deterministic replay

`replay_actions()` and `verify_replay()` replay recorded native actions
against a compatible environment without calling a model. Replay checks
the environment fingerprint and recorded observations. Redacted traces
cannot be replayed if required content is missing.

See [native actions](native-actions.md),
[execution capabilities](execution-capabilities.md), and
[harness stamping](harness-stamping.md).
