---
route: /docs/concepts/native-actions
title: Native actions
order: 130
description: Native actions are the moves an Agent can make in an Environment, like guess in Wordle. The Environment declares them, runs them, and decides what the Agent sees next.
audience: all
nav: false
---
# Native actions

A **native action** is a move the Agent can make in the world. In Wordle, `guess` is
a native action. At a support desk, `lookup_order` or `refund` might be.

Native actions belong to the Environment. Only the Environment declares them, it
carries them out, and it decides what the Agent sees afterwards.

## Why it matters

Because the Environment owns its actions, every Agent gets exactly the same moves,
whichever model or Harness it uses. That keeps comparisons fair. It also keeps the
world in control: the Agent only ever learns what the Environment chooses to show it.

## How it works

Each time the Agent takes an action:

1. The Environment runs it. The action can change the hidden **State**, the full
   truth about the world.
2. The Environment updates the **Observation**, the part of the world the Agent is
   allowed to see.
3. The Agent is shown the new Observation, and nothing else.

## In Python

Mark each action with `@action`. The method changes State, updates the Observation,
and returns it:

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

Here, `lookup_order` counts the lookup in the hidden State, which the Agent never
sees, and writes the order's status on the Observation, which it does.

> **Important:** After every action, the Agent sees the Environment's current
> `self.observation` and nothing else. Always put what the Agent should see on the
> Observation.

The value an action returns is passed to reward signals as `result`, but it is never
shown to the Agent.

### Going deeper: the episode

- `Environment.reset()` starts the episode. `reset` is not an action.
- `Environment.step()` applies one action and returns `observation, reward,
  terminated, truncated, info`. Only the observation reaches the Agent.
- When an action raises `ValueError`, the Agent sees the error message and the
  episode continues.
- In Plural's native loop, a model reply that calls no action ends the episode with
  the `agent_response` stop reason.

## In a Job

Plural reads each action's name, docstring, typed parameters, and timeout from the
class, and runs the methods from the Environment's folder. You do not write an
adapter or declare the actions anywhere else.

The `python:` key in `environment.yaml` names the class, for example
`environment.py:SupportEnv`. Validation imports it and fails if the import or the
class is broken:

```bash
plural env validate support-triage
```

## Actions and Harness tools

Every Harness receives the Environment's actions. Plural's native loop offers them to
the model as tools named after each action, such as `guess` or `categorize`, plus a
`finish` tool.

A Harness may add tools of its own, such as web search. The Environment can deny
those but never adds them. A denied Harness tool returns an error to the model and
the Trial continues. Nothing a Harness reports can add a score, a reward, or new
actions.

See [Harness and Environment policy](harness-policy.md) and
[Trials and trajectories](../running/trials.md).
