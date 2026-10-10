---
route: /docs/concepts/actions
title: Actions
order: 130
description: Actions are the moves an Agent can make, like guess in Wordle or an MCP server's tools. Each App declares its actions and runs them, and what an action returns is what the Agent sees next.
audience: all
nav: false
---
# Actions

An **action** is a move the Agent can make. In Wordle, `guess` is an action. At a
support desk, `lookup_order` or `refund` might be. Every action belongs to an
[App](apps.md): an MCP App offers its server's tools, whether you wrote the server with
FastMCP or connected an existing one, an OpenAPI App offers its operations, and a Python
App declares its actions with `@action`.

## Why it matters

Because Apps own the actions, every Agent gets exactly the same moves, whichever model
or Harness it uses. That keeps comparisons fair. It also keeps the system in control:
the Agent only ever learns what an action returns.

## How it works

Each time the Agent takes an action:

1. Plural sends the call to the App that owns it. The action can change the App's
   hidden **State**.
2. Whatever the action returns is the **observation**, the one thing the Agent is
   shown next.
3. If the Environment has an `on_step` hook, it runs, and may call other Apps. The
   Agent doesn't see that.

## In Python

Mark each method with `@action`. The docstring is the description the Agent reads,
and the typed parameters become the action's arguments:

```python
from plural import App, State, action


class Orders(State):
    lookups: int = 0


class OrderDesk(App[Orders]):
    @action(read_only=True)
    def lookup_order(self, order_id: str) -> str:
        """Look up an order by id."""
        self.state.lookups += 1
        return f"Order {order_id} has shipped."
```

Here, `lookup_order` counts the lookup in the hidden State, which the Agent never
sees, and returns the order's status, which it does.

What an action may return:

- **A string** is shown as is.
- **A dict, list, or Pydantic model** is shown as JSON.
- **An `Observation`** is shown through its `render()` method, so you control the
  text exactly.
- **`None`** shows nothing.

`@action` takes two options:

- `read_only=True` says the action never changes state. Verifiers may only `query`
  read-only actions, and a `live` App with only read-only actions can still be used
  in a Benchmark.
- `timeout_seconds` limits how long one call may run. The default is 30.

## Errors

When an action raises `ValueError`, the Agent sees `Error: ` followed by the message,
and the episode continues. Use it for feedback the Agent can act on:

```python
from plural import App, State, action


class Game(State):
    secret: str = "crane"


class Wordle(App[Game]):
    @action
    def guess(self, word: str) -> str:
        """Guess one five-letter word."""
        if len(word) != 5:
            raise ValueError("Guess exactly five letters.")
        return "solved" if word == self.state.secret else "not yet"
```

Any other exception is treated as a bug in the App and fails the Trial.

## The episode

- At the start, Plural calls each App's `reset(initial_state)`. Whatever `reset`
  returns is the Agent's first observation, along with the Task's instructions.
  `reset` is not an action.
- Each action is one `environment.step` on the Trial, with the App, the action, the
  arguments, and the observation.
- The episode ends when an App's `terminated()` returns true, when a limit in the
  Environment's `limits` is reached, or when the Agent replies without calling an
  action. Each has its own stop reason on the Trial.

Under the hood, a step returns `observation, reward, terminated, truncated, info`.
Only the observation reaches the Agent. Rewards are recorded for training and never
contribute to a score.

## Actions and Harness tools

Every Harness receives the Environment's actions. Plural's native loop offers them to
the model as tools, plus a `finish` tool. Each tool has the action's name, such as
`guess`, made safe for every model provider. Only when two Apps offer the same name is
it prefixed with the App, such as `orders__search`. See
[What the Agent sees](apps.md#what-the-agent-sees).

A Harness may add tools of its own, such as web search. The Environment can deny
those but never adds them. A denied Harness tool returns an error to the model and
the Trial continues. Nothing a Harness reports can add a score, a reward, or new
actions.

See [Harness and Environment policy](harness-policy.md) and
[Trials and trajectories](../running/trials.md).
