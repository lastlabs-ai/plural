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

Mark each action with `@action`. The method changes State, updates the
Observation, and returns it:

```python
from plural import Environment, Observation, State, action


class OrderObservation(Observation):
    order_status: str = ""


class OrderState(State):
    lookups: int = 0


class SupportEnv(Environment[OrderObservation, OrderState]):
    @action
    def lookup_order(self, order_id: str) -> OrderObservation:
        """Look up an order by id."""
        self.state.lookups += 1
        self.observation.order_status = f"Order {order_id} has shipped."
        return self.observation
```

After every action, the agent sees the Environment's current `self.observation`
and nothing else. The value an action returns is passed to reward signals as
`result`, but it is never shown to the agent, so always put what the agent
should see on the Observation.

`Environment.reset()` starts the episode, and `reset` is not an action.
`Environment.step()` applies one action and returns `observation, reward,
terminated, truncated, info`; only the observation reaches the agent. When an
action raises `ValueError`, the agent sees the error message and the episode
continues. In Plural's native loop, a model reply that calls no action ends the
episode with the `agent_response` stop reason.

## In a Job

Plural reads each action's name, docstring, typed parameters, and timeout from
the class, and runs the methods from the Environment's directory. You do not
write an adapter or declare the actions anywhere else.

The `python:` key in `environment.yaml` names the class, for example
`environment.py:SupportEnv`. Validation imports it and fails if the import or
the class is broken:

```bash
plural env validate support-triage
```

## Actions and Harness tools

Every Harness receives the Environment's actions. Plural's native loop offers
them to the model as tools named after each action, such as `guess` or
`categorize`, plus a `finish` tool. A Harness may add tools of its own, such as
web search; the Environment can deny those but never adds them. A denied Harness
tool returns an error to the model and the Trial continues. Nothing a Harness
reports can add a score, a reward, or new actions.

See [Harness and Environment policy](harness-policy.md) and
[Trials and trajectories](../running/trials.md).
