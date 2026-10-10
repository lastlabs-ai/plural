---
route: /docs/concepts/apps
title: Apps
order: 25
description: An App is one system an Agent works with, such as a game, a CRM behind an MCP server, an HTTP API, or a table of data. An Environment is a set of Apps.
audience: all
nav: true
nav_group: Build
---
# Apps

An **App** is one system an Agent works with. Wordle is an App with one action,
`guess`. A CRM reached through its MCP server is an App whose tools are its actions.
An [Environment](../project/environments.md) is a set of Apps plus the Runtime they
run in, so a support desk might combine a CRM, an orders API, and a policy database.

Every App does the same three things, whatever kind it is:

- **Offers actions.** Each action has a name, a description the Agent reads, and typed
  parameters. What an action returns is what the Agent sees next.
- **Keeps state the Agent never sees.** A Verifier reads it at the end to check the
  work. The Agent only sees what actions return.
- **Declares the secrets it needs,** such as `CRM_TOKEN`. A Job supplies the values,
  and they reach only the App, never the Agent or its Harness.

## Kinds of App

Pick the kind that matches what you already have:

| You have | Kind | In Python | Start with |
| --- | --- | --- | --- |
| Nothing yet; you want to write the system | Python | a subclass of `App` | `plural env init` |
| An MCP server | `mcp` | `App.mcp(...)` | `plural env from-mcp` |
| An HTTP API with an OpenAPI document | `openapi` | `App.openapi(...)` | `plural env from-openapi` |
| Data in files or SQLite, with no API | `data` | `App.data(...)` | `plural env from-data` |
| Recorded traces of an agent at work | `replay` | `App.replay(...)` | `plural env from-traces` |

A Python App is a class. Mark each action with `@action`; its docstring is what the
Agent reads:

```python
from plural import App, State, action, initial


class Game(State):
    secret: str = initial("crane", description="The hidden word.")
    solved: bool = False


class Wordle(App[Game]):
    """Guess a hidden five-letter word."""

    @action
    def guess(self, word: str) -> str:
        """Guess one five-letter word."""
        self.state.solved = word == self.state.secret
        return "solved" if self.state.solved else "not yet"

    def terminated(self) -> bool:
        return self.state.solved
```

`self.state` is the App's private state. Fields marked `initial()` are the ones a Task
may set. The other kinds connect a system that already exists:

```python
from plural import App

crm = App.mcp(
    "crm",
    url="https://mcp.example.com/v1",
    headers={"Authorization": "Bearer ${CRM_TOKEN}"},
    secrets=["CRM_TOKEN"],
)
orders = App.openapi("orders", spec="orders.json", base_url="https://sandbox.example.com")
policies = App.data("policies", tables={"refunds": "data/refunds.csv"}, read_only=True)
```

Paths in an App's settings, such as `spec` and `tables`, are relative to the file that
defines the Environment. [Connect an MCP server](../guides/connect-mcp-server.md)
walks through the MCP kind step by step.

## Compose Apps into an Environment

An Environment lists its Apps:

```python
from plural import Environment, Runtime

environment = Environment(name="support-desk", apps=[crm, orders, policies], runtime=Runtime.local())
```

Or, in `environment.yaml`:

```yaml
name: support-desk
apps:
  - python: apps/crm.py:CRM
  - name: orders
    openapi:
      spec: orders.json
      base_url: https://sandbox.example.com
  - name: policies
    data:
      tables:
        refunds: data/refunds.csv
      read_only: true
runtime:
  provider: local
```

With one App, the Agent sees its actions under their own names, such as `guess`. With
several, each name is prefixed with its App and two underscores, such as
`crm__get_record` and `orders__getOrder`, so two Apps can both have a `search` action.

Apps never call each other. When one App's action should affect another, such as a
refund in the orders API closing the ticket in the CRM, subclass `Environment` and
override `on_step`. It runs after every action and can call any App:

```python
from plural import Environment


class SupportDesk(Environment):
    def on_step(self, call, result, apps):
        if call.app == "orders" and call.action == "refund":
            apps["crm"].call("close_ticket", id=call.arguments["ticket"])
        return None
```

What `on_step` does is not an Agent action and is never shown to the Agent. Returning
a number records an Environment reward for that step.

## Control levels

How far Plural can trust an App's state decides where you can use it. Plural derives
each App's **control level** from its kind and settings; `plural env validate` prints
it.

| Level | Meaning | Examples |
| --- | --- | --- |
| `owned` | The state lives inside the Runtime, so every Trial starts fresh. | A Python App, a data App, an MCP server started with `command`, an OpenAPI App with `local: true` |
| `sandboxed` | The system is remote, but a reset hook returns it to the Task's starting state. | A remote MCP server with a `reset` command that seeds a sandbox tenant |
| `live` | The system is remote and shared, and Plural can't reset it. | A remote MCP server or API with no reset hook |
| `replayed` | The App answers from recordings. Nothing real is called. | A replay App |

The rules that follow from it:

- A **Benchmark** refuses a `live` App with any action that changes state, because
  one attempt could change what the next one sees. A `live` App whose actions only
  read is allowed, and the Benchmark is then marked not reproducible.
- A **training** Job refuses every `live` App, because its episodes would not start
  from the Task's state.
- An action is treated as one that changes state unless it says otherwise: an MCP
  tool with the `readOnlyHint` annotation, an OpenAPI `GET`, `HEAD`, or `OPTIONS`, or
  a read in a data App.

To use a remote system in a Benchmark, point it at a sandbox and give it a reset hook,
which makes it `sandboxed`.

## State, snapshots, and Verifiers

At the start and end of each episode, Plural takes a **snapshot** of every App: a
Python App's `state`, a data App's tables, or whatever an MCP App's `snapshot`
command prints. A Verifier reads them from the episode:

```python
from plural import Episode, VerifierOutput


def refunded(episode: Episode) -> VerifierOutput:
    crm = episode.apps["crm"]
    ticket = crm.query("get_ticket", id="T-7")
    done = ticket["status"] == "closed" and crm.final is not None
    return VerifierOutput(score=float(done))
```

- `episode.apps[name].initial` and `.final` are the two snapshots, and `.control` is
  the App's control level.
- `episode.state` is a shortcut: with one App, its final snapshot; with several, a
  mapping from App name to final snapshot.
- `query` calls one of the App's read-only actions while the Trial's Runtime is still
  running, so a Verifier can check the real system instead of trusting what the
  Agent said. Plural refuses an action that changes state.

## Secrets

An App declares the names of the secrets it needs. In headers and server variables,
`${NAME}` stands for the value:

```python
crm = App.mcp(
    "crm",
    url="https://mcp.example.com/v1",
    headers={"Authorization": "Bearer ${CRM_TOKEN}"},
    secrets=["CRM_TOKEN"],
)
```

The Environment knows every App's secrets, so a Job can check them before it starts
anything. A missing secret fails the Job at once, naming the App and the secret. The
values travel only to the process that runs the Apps and to Verifier queries. They are
never written to the project, shown to the Agent, or given to its Harness. Run
`plural env validate` to see which secrets each App needs and whether each is set in
your shell.

Locally, export the value before `plural run`. A hosted run takes it from the hosted
project's secrets.

## Rewards on Apps

A `@rewarder` on an App gives per-step credit for training whenever one of its actions
changes its state. Like every reward, it is recorded in the Trial's reward ledger and
never reaches the Agent or a score. See [Training and RL](../running/training.md).

```python
from plural import App, rewarder


class Wordle(App[Game]):
    @rewarder
    def solved(self, previous_state, current_state, action, result) -> float:
        return 1.0 if current_state["solved"] and not previous_state["solved"] else 0.0
```

## Where to go next

- [Connect an MCP server](../guides/connect-mcp-server.md), step by step.
- [Environments](../project/environments.md): Runtimes, resources, limits, and how an
  episode ends.
- [Actions](actions.md): what the Agent sees when it acts.
- [Verifiers](../project/verifiers.md): score an episode from App state.
