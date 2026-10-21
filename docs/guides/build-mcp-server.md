---
route: /docs/guides/build-mcp-server
title: Build an MCP server
order: 31
description: Write the system an Agent works with as a FastMCP server, give it a starting state and files, build tools over a data lake, or start from Plural's ready-made files server.
audience: all
nav: true
nav_group: Build
---

# Build an MCP server

Write the tools your Agent needs as an MCP server with [FastMCP](https://gofastmcp.com).
Every tool becomes an action the Agent can take, and Plural starts a fresh copy of the
server for every Trial.

```bash
pip install 'plural[mcp]'
```

## 1. Create the Environment

```bash
plural env init support-desk --bare
```

This writes `environments/support-desk/` with a `server.py` and an `environment.yaml`
that names it as the Environment's one App. Without `--bare` it also writes a starter
Task and Verifier for the example tools; this guide replaces those tools, so it leaves
them out:

```yaml
apps:
  - name: support_desk
    mcp:
      server: server.py:mcp
```

## 2. Write the tools

Replace the example tools in `server.py`:

```python
from fastmcp import FastMCP

import plural.mcp

mcp = FastMCP("support-desk")
TICKETS: list[dict] = []


@mcp.tool(annotations={"readOnlyHint": True})
def list_tickets(status: str = "open") -> list[dict]:
    """List tickets with this status."""
    return [ticket for ticket in TICKETS if ticket["status"] == status]


@mcp.tool
def close_ticket(id: str, resolution: str) -> str:
    """Close one ticket, saying how it was resolved."""
    for ticket in TICKETS:
        if ticket["id"] == id:
            ticket.update(status="closed", resolution=resolution)
            return f"Closed {id}."
    raise ValueError(f"No ticket {id}.")
```

- The docstring is what the model reads. Say what the tool does and when to use it.
- What a tool returns is what the Agent sees next. An error is shown to it too, so say
  how to fix it.
- Mark a tool that changes nothing with `readOnlyHint`.

:::details Why `readOnlyHint` matters
Verifiers may call only read-only tools, so they can't change what they check. A
Benchmark treats every other tool as one that changes state, which decides whether a
system Plural can't reset is allowed in it.
:::

## 3. Check it

```bash
plural env validate support-desk
```

```text
environment/support-desk is valid: sha256:...

App support_desk (mcp, owned)
  list_tickets  [read-only]
  close_ticket

The Agent sees 2 tools:
  list_tickets  List tickets with this status.
  close_ticket  Close one ticket, saying how it was resolved.
```

The last lines are the tools exactly as the model will see them. `validate` also lists
each `PLURAL-TODO` left in the template; they don't stop a local run, but they stop a
push. Then [write a Task](../project/tasks.md) and run it like any other:

```bash
plural run --task refund-t7 --model openai/gpt-5.6-luna
```

## Try it in an MCP client

```bash
plural env serve support-desk
```

```text
Serving support_desk at http://127.0.0.1:3825/mcp. Connect any MCP client; stop with Ctrl+C.
```

Point the MCP Inspector, Cursor, or any client at that address to call your tools by
hand. Port 3825 spells EVAL on a phone keypad; pick another with `--port`.

:::details Why Trials don't use a port
In a Trial, Plural talks to the server over its standard input and output. No port is
opened, so concurrent Trials never collide and nothing outside the Runtime can reach the
server. `plural env serve` is only for trying it yourself. It also shows Plural's two
hooks, `plural_reset` and `plural_snapshot`; an Agent never sees those.
:::

## Give it a starting state

A Task says where the episode starts, and a Verifier checks where it ended. Two
decorators connect your server to both:

```python
@plural.mcp.reset(mcp)
def start(initial_state: dict) -> None:
    TICKETS[:] = [dict(ticket) for ticket in initial_state.get("tickets", [])]


@plural.mcp.snapshot(mcp)
def state() -> dict:
    return {"tickets": TICKETS}
```

A Task then seeds the server in `task.yaml`:

```yaml
initial_state:
  tickets:
    - {id: T-7, status: open, subject: Refund for a damaged order}
```

:::details More about reset and snapshot
`reset` receives the Task's `initial_state` for this App at the start of every episode.
Return text from it only if the Agent should see it first. `snapshot` returns the state
a Verifier reads as `episode.apps["support_desk"].final`. Neither is offered to the
Agent as a tool.
:::

## Read files

The Environment can carry files, and so can each Task. In a Trial they sit side by
side, read-only:

```text
/workspace/resources/
  environment-resources/   files every Task gets
  task-resources/          this Task's own files
```

Read them from a tool:

```python
@mcp.tool(annotations={"readOnlyHint": True})
def read_policy() -> str:
    """Read the refund policy."""
    return (plural.mcp.environment_resources() / "resources/policy.md").read_text()
```

:::details Where files come from, and the other helpers
List the Environment's files under `resources` in `environment.yaml`, and put a Task's
in its `resources/` folder. A Trial references both; it never owns or changes them.

| Helper | What it is |
| --- | --- |
| `plural.mcp.environment_resources()` | The Environment's files. Outside a Trial it is the Environment folder, so the same paths work while you develop. |
| `plural.mcp.task_resources()` | The running Task's files, or `None` when it has none. |
| `plural.mcp.scratch()` | A writable folder for this Trial only, empty at the start and deleted at the end. |

Write anything the server must keep to `scratch()`, and report it from `snapshot` if a
Verifier should check it. A Harness that can read files, such as a coding agent, can
also read both folders directly; `PLURAL_RESOURCES_DIR` points at them.
:::

## Start from Plural's files server

For documents and data files, you may not need to write anything:

```yaml
apps:
  - name: files
    mcp:
      server: plural.mcp.files:server
```

| Tool | What it does |
| --- | --- |
| `list_files` | Lists the Environment's and the Task's files. |
| `read_file` | Reads a text file, a range of lines at a time. |
| `search_files` | Finds lines matching a pattern. |
| `list_tables` | Lists every CSV, JSON, JSONL, and SQLite file as tables. |
| `query` | Runs one read-only SQL `SELECT` over those tables. |

:::details Writing, table names, and making it your own
- **Writing.** `plural.mcp.files:writable` adds `write_file`, which writes only to a
  `scratch/` folder. Its snapshot is every file written there, for Verifiers.
- **Table names.** A CSV, JSON, or JSONL file is a table named after the file. A SQLite
  file's tables are `<file>.<table>`. When the Environment and the Task both have a file
  with the same name, the tables are `environment_resources_<name>` and
  `task_resources_<name>`.
- **Your own copy.** `plural app add support-desk --files-server --copy` copies the server into
  your Environment as `files_server.py`, to edit like your own, and points the App
  at `server: files_server.py:server`.
:::

## Work in a data lake or warehouse

Give the Agent a few tools that match how people use the data: what tables exist, what
a table holds, and a read-only query with a row limit. Then decide where the data
comes from:

| | A snapshot in the Environment | The live lake |
| --- | --- | --- |
| Data | An extract, such as Parquet files, in the Environment's files | Queried over the network |
| Every Trial sees | The same data | Today's data |
| Benchmarks | Yes | Only with read-only tools, marked not reproducible |
| Training | Yes | No |

Use a snapshot to compare models and to train. Use the live lake to check an Agent
against today's data. This server queries a snapshot of Parquet files with DuckDB:

```python
import duckdb
from fastmcp import FastMCP

import plural.mcp

mcp = FastMCP("lake")
LIMIT = 200


def connect() -> duckdb.DuckDBPyConnection:
    db = duckdb.connect()
    for path in sorted((plural.mcp.environment_resources() / "lake").glob("*.parquet")):
        db.execute(f"CREATE VIEW {path.stem} AS SELECT * FROM read_parquet('{path}')")
    return db


@mcp.tool(annotations={"readOnlyHint": True})
def list_tables() -> list[str]:
    """List the tables you can query."""
    return [row[0] for row in connect().execute("SHOW TABLES").fetchall()]


@mcp.tool(annotations={"readOnlyHint": True})
def describe_table(table: str) -> list[dict]:
    """List a table's columns and their types."""
    rows = connect().execute(f"DESCRIBE {table}").fetchall()
    return [{"column": row[0], "type": row[1]} for row in rows]


@mcp.tool(annotations={"readOnlyHint": True})
def query(sql: str) -> list[dict]:
    """Run one SELECT and return at most 200 rows."""
    if not sql.lstrip().lower().startswith(("select", "with")):
        raise ValueError("Only SELECT queries are allowed.")
    result = connect().execute(sql)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchmany(LIMIT)]
```

:::details Query the live lake instead
Mark the App `remote: true`, so Plural knows a fresh server isn't a fresh lake, and pass
the Agent's own credential to the server:

```yaml
apps:
  - name: lake
    mcp:
      server: server.py:mcp
      remote: true
      env: {WAREHOUSE_TOKEN: "${WAREHOUSE_TOKEN}"}
      credentials: [WAREHOUSE_TOKEN]
```

The server reads `os.environ["WAREHOUSE_TOKEN"]` to connect, so each Agent queries as
its own user, with its own grants, and each Trial records whose token acted. The App
is `live`: a Benchmark accepts it only if every tool is read-only. To let the Agent
write, give the server a `plural.mcp.reset` hook that restores a sandbox schema; the App
is then `sandboxed` and usable in Benchmarks and training.

To limit where the Runtime may connect, set `network: allowlist` and list the lake's
host in `allowed_hosts` in the Environment's `runtime`; see
[Runtimes](../project/runtimes.md).
:::

:::details Packages your server needs
A server that imports a package beyond Plural and FastMCP, such as `duckdb` or a
warehouse client, needs it in the Runtime. List it in the Environment's `runtime`:

```yaml
runtime:
  python_packages:
    - duckdb>=1.1
```

Plural installs it alongside itself. The `local` Runtime uses your project's Python
instead, and a Job names any package it lacks; see
[Packages](../project/runtimes.md#packages).
:::

## Several Apps

An Environment can list your server beside others, such as a hosted CRM and the files
server. The Agent gets one list of tools; see
[What the Agent sees](../concepts/apps.md#what-the-agent-sees) and
[Several systems in one Environment](../start/from-a-system.md#several-systems-in-one-environment).

## Where to go next

- [Connect an MCP server](connect-mcp-server.md) that already exists, such as your CRM's.
- [Verifiers](../project/verifiers.md): score an episode from the snapshot.
- [Tasks](../project/tasks.md): starting states and per-Task files.
