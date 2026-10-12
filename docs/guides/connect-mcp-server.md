---
route: /docs/guides/connect-mcp-server
title: Connect an MCP server
order: 32
description: Turn any MCP server into an App, so Agents can be evaluated and trained against it. Covers local and remote servers, Agent credentials and secrets, choosing tools, resetting a sandbox, and checking state in Verifiers.
audience: all
nav: true
nav_group: Build
---
# Connect an MCP server

Any MCP server can be an [App](../concepts/apps.md). Its tools become the Agent's
actions, and Plural handles the session, the credentials, and the record of every call.
This guide connects a server, then makes it safe to benchmark.

## 1. Add the server to an Environment

From inside a project, run `plural env add` with the command that starts the server:

```bash
plural env add memory --mcp "npx -y @modelcontextprotocol/server-memory"
```

```text
Created environment memory:
  environments/memory/environment.yaml
  environments/memory/README.md

App memory (mcp, owned) offers:
  create_entities
  create_relations
  add_observations
  delete_entities
  delete_observations
  delete_relations
  read_graph  [read-only]
  search_nodes  [read-only]
  open_nodes  [read-only]
```

Plural started the server, listed its tools, and wrote an ordinary
`environment.yaml`:

```yaml
name: memory
apps:
  - name: memory
    mcp:
      command: [npx, -y, "@modelcontextprotocol/server-memory"]
runtime:
  provider: local
limits:
  max_turns: 20
  max_seconds: 600
```

This server saves its graph to a file inside its own package, so every Trial would
see what earlier Trials stored. Point it at the episode's folder instead. Plural gives
each server started with `command` a new empty folder every episode, available as
`${PLURAL_APP_DIR}`, and deletes it when the episode ends:

```yaml
apps:
  - name: memory
    mcp:
      command: [npx, -y, "@modelcontextprotocol/server-memory"]
      env:
        MEMORY_FILE_PATH: ${PLURAL_APP_DIR}/memory.jsonl
```

Check the server's README for where it keeps data: a file path, a database URL, or a
cache folder. `TMPDIR` already points into the folder.

`[read-only]` marks tools whose `readOnlyHint` annotation says they change nothing.
Plural treats every other tool as one that changes state, which matters for
[control levels](#5-make-a-remote-server-safe-to-benchmark).

The App is named after the server's package, here `memory`; pass `--app NAME` to
choose. For a server reached over HTTP, pass its URL instead, with any headers it
needs:

```bash
plural env add crm \
  --mcp https://mcp.example.com/v1 --app crm \
  --header 'Authorization=Bearer ${CRM_TOKEN}'
```

Run `plural env add` again with another Environment's name to add the same way to it,
or with this one's name to add a second system beside the first.

Quote the header in single quotes so your shell leaves `${CRM_TOKEN}` alone; Plural
fills it in. Every `${NAME}` becomes a credential the running Agent supplies; see
[step 4](#4-supply-credentials). Export the token first (`export CRM_TOKEN=...`) so
Plural can reach the server to list its tools. Without it, the files are still written.

## 2. Check it

```bash
plural env validate memory
```

`validate` connects to the server and prints each App's kind, control level, actions,
credentials, and secrets, with where each secret comes from: your shell, the hosted
project, or nowhere yet. It never prints a value.
Run it after every change.

## 3. Choose the tools

An Agent does better with fewer, well-described tools. Offer only some:

```yaml
apps:
  - name: memory
    mcp:
      command: [npx, -y, "@modelcontextprotocol/server-memory"]
      tools: [create_entities, add_observations, search_nodes, open_nodes]
```

Or keep them all and drop a few with `exclude: [delete_entities]`. The command
equivalent is `--tool NAME`, repeated. If `tools` names one the server doesn't offer,
`validate` lists what it does offer.

The Agent reads each tool's description from the server, and each tool keeps its name.
Only a name another App also offers is prefixed with the App, such as `memory__search`;
see [What the Agent sees](../concepts/apps.md#what-the-agent-sees).

## 4. Supply credentials

A server's token belongs to the Agent that uses it, not to the App. Each Agent carries
its own, such as the token of the Salesforce user it acts as, so its scopes decide
what it can do and every Trial records which Agent's token acted. Reference the token as
`${NAME}` in `headers` (remote servers) or `env` (servers started with `command`), and
list its name under `credentials`:

```yaml
apps:
  - name: crm
    mcp:
      url: https://mcp.example.com/v1
      headers:
        Authorization: Bearer ${CRM_TOKEN}
      credentials: [CRM_TOKEN]
  - name: search
    mcp:
      command: [uvx, acme-search-mcp]
      env:
        ACME_API_KEY: ${ACME_API_KEY}
      credentials: [ACME_API_KEY]
```

Plural refuses an App that references a name it doesn't list, so nothing can be
forgotten. Then give the Agent its credentials. List each in its `agent.yaml`, with
the scopes the token grants, and store each value with the Agent:

```yaml
# agents/sales-bot/agent.yaml
name: sales-bot
model: openai/gpt-5.6
credentials:
  CRM_TOKEN:
    scopes: [read:accounts, write:opportunities]
  ACME_API_KEY: {}
```

```bash
plural agent credential set sales-bot CRM_TOKEN
plural agent credential set sales-bot ACME_API_KEY
plural run --task close-deal --agent sales-bot
```

`plural agent credential set` prompts for the value without echoing it, and
`plural agent credential list sales-bot` shows which are stored, never their values.
For a quick local run you can export the value instead.

A run stops before it starts when the Agent doesn't carry a credential an App needs, or
has no value for one, naming the App and the credential. A run with `--model` carries
no credentials, so it can't use an App that needs one; save an Agent instead.

The value goes only to the process that runs the Apps. It is never written to the
project or the Trial, shown to the model, or given to its Harness. Each Trial records
the Agent, its revision, the declared scopes, where the value came from, and a short
fingerprint of it; `plural trial show` prints that record. Plural doesn't enforce the
scopes; the system that issued the token does.

### Setup secrets

Some values belong to the project, not to any Agent: the admin token a `reset` command
uses to wipe a sandbox, or a key a Verifier needs. List those under `secrets`, and store
each once in the hosted project, or export it:

```bash
plural secret set CRM_ADMIN_TOKEN
```

`reset` and `snapshot` commands get the App's secrets and never an Agent's credentials.

## 5. Make a remote server safe to benchmark

A server started with `command` runs inside the Runtime, and Plural starts a new
process for every Trial, so it is `owned` and can be used anywhere. It starts fresh
only if it keeps its data in `${PLURAL_APP_DIR}`, as in [step 1](#1-add-the-server-to-an-environment).

A remote server is shared. If one Trial creates a record, the next Trial sees it, and
scores stop being comparable. With no way to reset it, the App is `live`:

- A **Benchmark** refuses a `live` App that has any tool that changes state.
- A `live` App whose tools are all read-only is allowed, but the Benchmark is marked
  not reproducible, because the data behind it can change.
- A **training** Job refuses every `live` App.

To fix that, point the App at a sandbox and give it a `reset` hook. The App becomes
`sandboxed`. `reset` is a command run at the start of every episode, with the Task's
starting state for this App as JSON on its standard input:

```yaml
apps:
  - name: crm
    mcp:
      url: https://sandbox.mcp.example.com/v1
      headers:
        Authorization: Bearer ${CRM_TOKEN}
      reset: python scripts/seed_crm.py
      snapshot: python scripts/dump_crm.py
      credentials: [CRM_TOKEN]
      secrets: [CRM_ADMIN_TOKEN]
```

The `reset` script wipes the sandbox tenant and loads the records the Task describes.
Anything it prints becomes the episode's opening observation, so print nothing unless
the Agent should see it. The App's secrets, such as `CRM_ADMIN_TOKEN`, are in the
script's environment; the Agent's credentials are not. Give a Task's starting state
under `initial_state`:

```yaml
initial_state:
  crm:
    tickets:
      - id: T-7
        status: open
        subject: Refund for a damaged order
```

With one App, the App's name can be left out of `initial_state`.

If the hooks are easier to write in Python, subclass `MCPApp` and use `call_tool`,
which calls one of the server's tools. Those calls go through the App's own connection,
so they act with the running Agent's credential; use a `reset` command with a setup
secret when the reset needs rights the Agent doesn't have:

```python
from plural.apps import MCPApp


class CRM(MCPApp):
    name = "crm"

    def reset(self, initial_state):
        self.call_tool("admin_reset_tenant")
        for ticket in initial_state.get("tickets", []):
            self.call_tool("create_ticket", **ticket)
        return None

    def snapshot(self):
        return {"tickets": self.call_tool("list_tickets")}
```

Then point the Environment at the class and pass the server settings as `config`:

```yaml
apps:
  - python: apps/crm.py:CRM
    config:
      url: https://sandbox.mcp.example.com/v1
      headers:
        Authorization: Bearer ${CRM_TOKEN}
      credentials: [CRM_TOKEN]
```

## 6. Check the work in a Verifier

A Verifier should check what happened in the system, not what the Agent says
happened. There are two ways.

**The snapshot.** If the App has a `snapshot` hook, its output is the App's final
state:

```python
from plural import Episode, VerifierOutput


def ticket_closed(episode: Episode) -> VerifierOutput:
    tickets = episode.apps["crm"].final["tickets"]
    closed = any(item["id"] == "T-7" and item["status"] == "closed" for item in tickets)
    return VerifierOutput(score=float(closed))
```

**A query.** A Verifier can call one of the App's read-only tools while the Trial's
Runtime is still running:

```python
from plural import Episode, VerifierOutput


def ticket_closed(episode: Episode) -> VerifierOutput:
    ticket = episode.apps["crm"].query("get_ticket", id="T-7")
    return VerifierOutput(score=float(ticket["status"] == "closed"))
```

`query` refuses a tool that changes state, so a Verifier can't alter what it checks.
It returns the tool's structured content when the server sends some, and its text
otherwise.

## 7. Run it

Write a Task and run it like any other:

```bash
plural run --task close-refund-ticket --model openai/gpt-5.6-luna
```

Each call the Agent makes is recorded on the Trial as an `environment.step`, with the
App, the tool, the arguments, and the result.

## Python form

Everything above also works without YAML:

```python
from plural import App, Environment, Runtime

crm = App.mcp(
    "crm",
    url="https://sandbox.mcp.example.com/v1",
    headers={"Authorization": "Bearer ${CRM_TOKEN}"},
    reset="python scripts/seed_crm.py",
    snapshot="python scripts/dump_crm.py",
    credentials=["CRM_TOKEN"],
    secrets=["CRM_ADMIN_TOKEN"],
)

environment = Environment(name="support-desk", apps=[crm], runtime=Runtime.local())
```

## Settings

| Setting | Meaning |
| --- | --- |
| `server` | A FastMCP server to start inside the Runtime, as `file.py:name`, such as `server.py:mcp`, or `package.module:name`, such as `plural.mcp.files:server`. See [Build an MCP server](build-mcp-server.md). |
| `command` | Start the server inside the Runtime. A list, or one string split like a shell would. |
| `url` | Reach a server over Streamable HTTP instead. Give exactly one of `server`, `command`, and `url`. |
| `headers` | HTTP headers for a `url` server. Values may contain `${NAME}`, a credential or secret. |
| `env` | Environment variables for a `server` or `command` server. Values may contain `${NAME}`, a credential or secret, and `${PLURAL_APP_DIR}`, the episode's empty folder. |
| `cwd` | Working folder for a `command` server, relative to the Environment. |
| `remote` | Set `true` when a `server` or `command` server works on a system outside the Runtime, such as a data lake. The App is then `live`, or `sandboxed` with a `reset` hook, instead of `owned`. |
| `tools` | Offer only these tools. |
| `exclude` | Never offer these tools. |
| `reset` | Command run at the start of each episode, with the App's starting state as JSON on stdin. |
| `snapshot` | Command that prints the App's state as JSON. |
| `snapshot_on_step` | Also snapshot around every action, so a Verifier's `reward` function receives `previous_state` and `current_state`. Off by default, since it costs a call per step. |
| `actions` | Tool declarations to use instead of asking the server, so the Environment loads without reaching it. |
| `timeout_seconds` | How long one tool call may run. Default 60. |
| `credentials` | Names the running Agent supplies, such as its own API token. |
| `secrets` | Names the project supplies, for `reset` and `snapshot` commands and Verifiers. |

## Troubleshooting

`plural env validate` reports each of these. Its error names the App.

| Error | What to do |
| --- | --- |
| `Agent 'gpt-5.6' does not carry: CRM_TOKEN, for App crm` | List `CRM_TOKEN` under `credentials:` in the Agent's `agent.yaml` and run with `--agent`. A `--model` run carries no credentials. |
| `Agent 'sales-bot' declares CRM_TOKEN but has no value for it` | Store it with `plural agent credential set sales-bot CRM_TOKEN`, or export it for a local run. |
| `App 'crm' needs CRM_ADMIN_TOKEN` | A setup secret is missing. Export it, or store it with `plural secret set CRM_ADMIN_TOKEN`. |
| `references CRM_TOKEN but does not list it` | Add the name to the App's `credentials`, or to its `secrets` if the project supplies it. |
| `Cannot start MCP server 'npx'` | The command isn't installed where the Apps run. Install it, or use its full path. |
| `MCP server exited: exit code 1. Its output is in .../server.log` | The server crashed on startup. The error shows the end of its output; the most common cause is a missing environment variable. |
| `Cannot reach MCP server https://...` | Check the URL, and that the server speaks Streamable HTTP. |
| `lists tools the server does not offer` | Fix a name in `tools`; the error lists the server's tools. |
| `MCP server did not answer in time` | Raise `timeout_seconds`, or check the server isn't waiting for input. |
| A Benchmark refuses a `live` App | Point the App at a sandbox and add a `reset` hook, or offer only read-only tools. |
