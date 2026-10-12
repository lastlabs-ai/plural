---
route: /docs/concepts/apps
title: Apps
order: 25
description: An App is one system an Agent works with, such as an MCP server you write with FastMCP, a hosted MCP server like a CRM's, an HTTP API, or a game. An Environment is a set of Apps.
audience: all
nav: true
nav_group: Build
---
# Apps

An **App** is one system an Agent works with. Wordle is an App with one action,
`guess`. A CRM reached through its MCP server is an App whose tools are its actions.
An [Environment](../project/environments.md) is a set of Apps plus the Runtime they
run in, so a support desk might combine a CRM, an orders API, and the support policy.

Every App does the same three things, whatever kind it is:

- **Offers actions.** Each action has a name, a description the Agent reads, and typed
  parameters. What an action returns is what the Agent sees next.
- **Keeps state the Agent never sees.** A Verifier reads it at the end to check the
  work. The Agent only sees what actions return.
- **Declares the credentials it needs,** such as `CRM_TOKEN`. The Agent that runs
  supplies the values, so it acts as its own user with its own scopes. They reach only
  the App, never the model or its Harness.

## Kinds of App

Most Apps are MCP servers. Pick the row that matches what you have:

| You have | Kind | Start with |
| --- | --- | --- |
| Nothing yet; you want to write the system | `mcp`, a server you write with FastMCP | `plural env init` |
| A hosted MCP server, such as your CRM's | `mcp`, reached by URL | `plural env add ENV --mcp URL`, or **Add system** on the Environment's Apps tab |
| Files: documents, CSV, JSON, or SQLite | `mcp`, Plural's files server | `server: plural.mcp.files:server` |
| An HTTP API with an OpenAPI document | `openapi` | `plural env add ENV --openapi SPEC` |
| Recorded traces of an agent at work | `replay` | `plural env add ENV --traces FILE` |
| A simulation you'd rather write as a class, such as a game | Python, a subclass of `App` | `plural env init --python` |

A server you write is an ordinary [FastMCP](https://gofastmcp.com) server. Every tool is
an action; its docstring is what the Agent reads, and what it returns is what the Agent
sees next:

```python
from fastmcp import FastMCP

import plural.mcp

mcp = FastMCP("desk")
TICKETS: list[dict] = []


@mcp.tool(annotations={"readOnlyHint": True})
def list_tickets() -> list[dict]:
    """List open tickets."""
    return [ticket for ticket in TICKETS if ticket["status"] == "open"]


@mcp.tool
def close_ticket(id: str) -> str:
    """Close one ticket."""
    ...


@plural.mcp.reset(mcp)
def start(initial_state: dict) -> None:
    TICKETS[:] = initial_state.get("tickets", [])


@plural.mcp.snapshot(mcp)
def state() -> dict:
    return {"tickets": TICKETS}
```

Name it in `environment.yaml` with `server: server.py:mcp`, and Plural starts a fresh
copy for every Trial. `@plural.mcp.reset` receives the Task's starting state and
`@plural.mcp.snapshot` reports state to Verifiers; the Agent sees neither as a tool.
[Build an MCP server](../guides/build-mcp-server.md) walks through it, including how a
server reads the Environment's and the Task's files.

The other kinds connect a system that already exists:

```python
from plural import App

crm = App.mcp(
    "crm",
    url="https://mcp.example.com/v1",
    headers={"Authorization": "Bearer ${CRM_TOKEN}"},
    credentials=["CRM_TOKEN"],
)
files = App.mcp("files", server="plural.mcp.files:server")
orders = App.openapi("orders", spec="orders.json", base_url="https://sandbox.example.com")
```

Paths in an App's settings, such as `server` and `spec`, are relative to the folder
that holds the Environment. [Connect an MCP server](../guides/connect-mcp-server.md)
walks through a hosted server step by step.

A Python App is a class instead of a server. Mark each action with `@action`:

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
may set.

## Compose Apps into an Environment

An Environment lists its Apps:

```python
from plural import Environment, Runtime

environment = Environment(name="support-desk", apps=[crm, files, orders], runtime=Runtime.local())
```

Or, in `environment.yaml`:

```yaml
name: support-desk
apps:
  - name: desk
    mcp:
      server: server.py:mcp
  - name: crm
    mcp:
      url: https://mcp.example.com/v1
      headers: {Authorization: "Bearer ${CRM_TOKEN}"}
      credentials: [CRM_TOKEN]
  - name: files
    mcp:
      server: plural.mcp.files:server
  - name: orders
    openapi:
      spec: orders.json
      base_url: https://sandbox.example.com
runtime:
  provider: local
```

### What the Agent sees

The Agent gets one flat list of tools, built from every App's actions. You don't
arrange it; it works the same with one App or ten:

- **Each tool keeps its own name,** such as `close_ticket` or `getOrder`. Adding an App
  never renames the tools of the others.
- **Only a clash is prefixed.** When two Apps both offer `search`, they become
  `crm__search` and `docs__search`. So does a tool named like the episode's own
  `reset`, `step`, or `finish`.
- **Every name works with every model provider.** Characters providers reject are
  replaced, so an MCP tool named `salesforce.query` is offered as `salesforce_query`,
  and long names are shortened to 64 characters. The App is still called with its
  own name.
- **Each description says which system it acts on** when there are several Apps, such
  as `[crm] Close one ticket.`, and every parameter schema is normalized to one that
  every provider accepts.
- **Plural's hooks are never tools.** `reset` and `snapshot` hooks, and a FastMCP
  server's `@plural.mcp.reset` and `@plural.mcp.snapshot`, never reach the Agent.

`plural env validate` prints the list exactly as the model receives it, and so does the
Environment's Apps tab. Offer fewer tools with `tools:` or `exclude:` on an App; a model
chooses better from a short list of well-described tools.

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

What `on_step` does is not an Agent action and is never shown to the Agent. It
changes the world and gives no reward: rewards come from the Task's
[Verifiers](../project/verifiers.md#reward-each-step).

## Control levels

How far Plural can trust an App's state decides where you can use it. Plural derives
each App's **control level** from its kind and settings; `plural env validate` prints
it.

| Level | Meaning | Examples |
| --- | --- | --- |
| `owned` | The state lives inside the Runtime, so every Trial starts fresh. | A FastMCP server named with `server`, Plural's files server, a Python App, an MCP server started with `command` that keeps its data in `${PLURAL_APP_DIR}`, an OpenAPI App with `local: true` |
| `sandboxed` | The system is remote, but a reset hook returns it to the Task's starting state. | A remote MCP server with a `reset` command that seeds a sandbox tenant; a server marked `remote: true` with a reset hook |
| `live` | The system is remote and shared, and Plural can't reset it. | A remote MCP server or API with no reset hook; a server marked `remote: true` without one |
| `replayed` | The App answers from recordings. Nothing real is called. | A replay App |

The rules that follow from it:

- A **Benchmark** refuses a `live` App with any action that changes state, because
  one attempt could change what the next one sees. A `live` App whose actions only
  read is allowed, and the Benchmark is then marked not reproducible.
- A **training** Job refuses every `live` App, because its episodes would not start
  from the Task's state.
- An action is treated as one that changes state unless it says otherwise: an MCP
  tool with the `readOnlyHint` annotation, an OpenAPI `GET`, `HEAD`, or `OPTIONS`, or
  a Python action marked `read_only`.

To use a remote system in a Benchmark, point it at a sandbox and give it a reset hook,
which makes it `sandboxed`.

## State, snapshots, and Verifiers

At the start and end of each episode, Plural takes a **snapshot** of every App: a
Python App's `state`, what a FastMCP server's `@plural.mcp.snapshot` returns, or
whatever an MCP App's `snapshot` command prints. A Verifier reads them from the episode:

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

A Verifier's `reward` function reads the same Apps after every action, through
`step.apps`, to reward each step. See
[Reward each step](../project/verifiers.md#reward-each-step).

## Credentials and secrets

An App never holds a credential's value. It declares the names it needs, and
`${NAME}` stands for the value in headers and server variables. There are two kinds:

- **Credentials** come from the Agent that runs. Use them for anything the Agent acts
  with, such as the Salesforce token of the user it works as. Each Agent carries its
  own token, so its scopes decide what it can do, and every Trial records which Agent's
  credential was used.
- **Secrets** come from the project. Use them only for setup: a `reset` or `snapshot`
  command's admin token, or a key a Verifier needs. Those commands never see an
  Agent's credentials.

```python
crm = App.mcp(
    "crm",
    url="https://mcp.example.com/v1",
    headers={"Authorization": "Bearer ${CRM_TOKEN}"},
    credentials=["CRM_TOKEN"],
    reset="python scripts/seed.py",
    secrets=["CRM_ADMIN_TOKEN"],
)
```

The Agent lists the credentials it carries in its `agent.yaml`, with the scopes each
one grants:

```yaml
name: sales-bot
model: openai/gpt-5.6
credentials:
  CRM_TOKEN:
    scopes: [read:accounts, write:opportunities]
```

Store each value with the Agent, then run it:

```bash
plural agent credential set sales-bot CRM_TOKEN
plural run --task close-deal --agent sales-bot
```

Before anything starts, the Job checks that the Agent carries every credential the
Apps need and has a value for each. A run with `--model` carries none, so it can't use
an App that needs one. For a local run you can export the value instead of storing it.

Values travel only to the process that runs the Apps and to Verifier queries made
through it. They are never written to the project or the Trial, shown to the model,
or given to its Harness. Each Trial records, for every credential: the App, the Agent
and its revision, the declared scopes, where the value came from, and a short
fingerprint of the value, so you can tell which token acted without storing it.
`plural trial show` prints this record, and so does the Trial page.

Plural doesn't enforce scopes. The system that issued the token does; Plural records
what you declared. Run `plural env validate` to see what each App needs, and
`plural agent validate` to see which credentials an Agent has values for.

## Apps hold facts, not rewards

An App reports what happened: its State, its snapshots, and what its actions return.
It doesn't judge any of it. Whether an action deserved credit depends on the Task, and
often on more than one App, so per-step rewards come from the Task's Verifiers, which
can read every App:

```python
from plural import Step


def solved(step: Step) -> float:
    return 1.0 if step.current_state["solved"] and not step.previous_state["solved"] else 0.0
```

Name it as the `reward` of a Verifier the Task lists. See
[Reward each step](../project/verifiers.md#reward-each-step).

## Where to go next

- [Build an MCP server](../guides/build-mcp-server.md) with FastMCP.
- [Connect an MCP server](../guides/connect-mcp-server.md) you already have, step by step.
- [Environments](../project/environments.md): Runtimes, resources, limits, and how an
  episode ends.
- [Actions](actions.md): what the Agent sees when it acts.
- [Verifiers](../project/verifiers.md): score an episode and reward each step from App
  state.
