---
route: /docs/concepts/native-actions
title: "Native actions"
order: 130
description: "A native action is owned by the environment. It acts in the environment and returns an observation from the environment. Only the environment declares them."
audience: all
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

`Environment.step()` records one `Turn`. Each invoked action becomes an
`ActionStep` with `source="environment_native"` and the return value stored
as `observation`. Nested `@action` calls become `children`.

A model response with no tool calls is normalized to
`ParsedAction(name="respond", source="model_text")`.

## In a package

`EnvironmentManifest.actions` is a tuple of `NativeAction` values: name,
description, `kind` (`command` or `python`), argv, JSON parameters,
observation schema, `mutates_state`, and timeout.

```bash
plural env validate environment
plural env show environment
```

## Native versus stamped execution

On the **native path** (`AgentDefinition.harness is None`) those actions are
converted to model tool definitions and executed by `native.actions.v1`.

On the **stamped path** native actions are omitted from
`HarnessRunRequest.environment`. The harness brings its own actions. A
harness event may not smuggle an `actions` key back in.

See [harness stamping](harness-stamping.md) and
[observability](observability.md).
