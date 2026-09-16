---
route: /docs/concepts/native-actions
title: Native actions
order: 130
description: A native action is owned by the environment. It acts in the environment and returns an observation from the environment. Only the environment declares them.
audience: all
nav: false
---
# Native actions

A native action is owned by the environment. It acts in the environment and
returns an observation from the environment. Only the environment declares
them.

## In Python

```python
from plural import Environment
from plural.environments import action

class SupportEnv(Environment):
    name = "support-triage"
    version = "0.1.0"

    @action
    def lookup_order(self, order_id: str) -> dict[str, str]:
        """Look up an order by id."""
        return {"order_id": order_id, "status": "shipped"}
```

`Environment.reset()` starts the episode after the Environment is attached
to a Task. `Environment.step()` applies one Agent action and returns
observation, reward, terminated, truncated, and info. Each invoked `@action`
becomes an `ActionStep` with `source="environment_native"` and the return
value stored as `observation`. Nested `@action` calls become `children`.
`reset` is not an `@action`.

A model response with no tool calls is normalized to
`ParsedAction(name="respond", source="model_text")`.

## On a Job

`Environment` discovers each decorated action's name, description, parameters,
observation shape, mutation flag, and timeout. A Job runs those methods from
the class directory. You do not write an adapter.

```bash
plural validate environment.py:environment
plural inspect environment.py:environment
```

## Native versus harness-wrapped execution

Environment actions are always present on `HarnessRunRequest.environment`.
The native runner exposes them as tools named after the action (`guess`,
`categorize`). OpenAI-compatible function names cannot contain `.`.
A harness may add `harness.<tool>` tools; the Environment may only subtract
those. Restricted harness tools are soft-denied. A harness event may not
smuggle scores, rewards, or an `actions` key back in.

See [Harness and Environment policy](harness-policy.md) and
[traces](../running/traces.md).
