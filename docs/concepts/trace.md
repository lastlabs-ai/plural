---
route: /docs/concepts/trace
title: "Trace"
order: 200
description: "Canonical schema version: 3.0.0. It adds pinned revision provenance, Verifier/review outcomes, Job mode, and hashed artifact references."
audience: all
---
# Trace

Canonical schema version: **3.0.0**. It adds pinned revision provenance,
Verifier/review outcomes, Job mode, and hashed artifact references.

`Environment.rollout(...)` persists one `episode` trace. Model requests and
outputs live inside `Turn` steps. Set `record_llm_traces=True` only when
separate model-call records are needed (`trace_kind="llm_call"`).

| Field | Meaning |
| --- | --- |
| `steps` | `Turn`, `LLMCall`, `ActionStep`, or `Event` |
| `schema_version` | `3.0.0` |
| `harness` / `granted_capabilities` | stamp in force for the trial |
| `capability_denials` | what the environment or policy removed |
| `agent_revision_digest` / `task_revision_digest` | pinned Agent and Task revisions |
| `job_id` / `trial_id` | Job and independent-attempt identity |
| `verifier_results` | deterministic, agent, or human outcomes |
| `artifacts` | hashed references, including train-only exact TITO |

One `Turn` is one policy step and may contain several actions. It includes
observation, reasoning, model context/output, parsed actions, action
results with observations, reward events, and timing.

```python
trace.transitions(source="events")
trace.turn_rewards(source="both")
trace.returns(gamma=0.9)
```

See [observability](observability.md) and the
[trace schema reference](../reference/trace-schema.md).
