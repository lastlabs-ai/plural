---
route: /docs/guides/build-mcp-server
title: Build an MCP server
order: 31
description: Write the system an Agent works with as a FastMCP server, read the Environment's and the Task's files from it, give it a starting state and a snapshot, or start from Plural's ready-made files server.
audience: all
nav: true
nav_group: Build
---

# Build an MCP server

When the system an Agent should work with doesn't exist yet, or you want a controlled
copy of one, write it as an MCP server with [FastMCP](https://gofastmcp.com). Every tool
becomes an action the Agent can take. Plural starts a fresh copy of the server for every
Trial, so each attempt starts from the same place.

Install FastMCP with Plural:

```bash
pip install 'plural[mcp]'
```

## 1. Create the Environment

```bash
plural env init support-desk
```

```text
Created Environment support-desk:
  environments/support-desk/environment.yaml
  environments/support-desk/server.py
  environments/support-desk/README.md
```

`environment.yaml` names the server as the Environment's one App:

```yaml
apps:
  - name: support_desk
    mcp:
      server: server.py:mcp
```

`server.py:mcp` is the file, relative to the Environment folder, and the FastMCP object
in it.

## 2. Write the tools

Replace the example tools in `server.py` with the moves your Agent needs:

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

- The docstring is the tool's description. Write it for the model: what the tool does
  and when to use it.
- What a tool returns is what the Agent sees next. A raised error is shown to the
  Agent too, and the episode goes on, so say what went wrong and how to fix it.
- Mark a tool that changes nothing with `readOnlyHint`. Verifiers may call only those,
  and a Benchmark treats every other tool as one that changes state.

## 3. Give it a starting state and a snapshot

A Task describes where the episode starts, and a Verifier checks where it ended. Two
decorators connect your server to both:

```python
@plural.mcp.reset(mcp)
def start(initial_state: dict) -> None:
    TICKETS[:] = [dict(ticket) for ticket in initial_state.get("tickets", [])]


@plural.mcp.snapshot(mcp)
def state() -> dict:
    return {"tickets": TICKETS}
```

`reset` receives the Task's `initial_state` for this App at the start of every episode.
Return text from it only if the Agent should see it first. `snapshot` returns the state
a Verifier reads as `episode.apps["support_desk"].final`. The Agent never sees either
as a tool.

A Task then seeds the server:

```yaml
initial_state:
  tickets:
    - {id: T-7, status: open, subject: Refund for a damaged order}
```

## 4. Read the Environment's and the Task's files

Files are volumes: the Environment has one, each Task may have its own, and a Trial
reads both without owning either. List the Environment's under `resources` in
`environment.yaml` and put a Task's in its `resources/` folder. In a Trial they sit side
by side, read-only:

```text
/workspace/resources/
  environment-resources/   every Task's files: resources/policy.md
  task-resources/          this Task's own files: resources/invoice.csv
```

Read them from the server with `plural.mcp`:

```python
@mcp.tool(annotations={"readOnlyHint": True})
def read_policy() -> str:
    """Read the refund policy."""
    return (plural.mcp.environment_resources() / "resources/policy.md").read_text()


@mcp.tool(annotations={"readOnlyHint": True})
def read_invoice() -> str:
    """Read the invoice attached to this case."""
    folder = plural.mcp.task_resources()
    if folder is None:
        return "This case has no invoice."
    return (folder / "resources/invoice.csv").read_text()
```

| Helper | What it is |
| --- | --- |
| `plural.mcp.environment_resources()` | The Environment's files. Outside a Trial, while you develop, it is the Environment folder, so the same paths work. |
| `plural.mcp.task_resources()` | The running Task's files, or `None` when it has none. |
| `plural.mcp.scratch()` | A writable folder for this Trial only, empty at the start and deleted at the end. |

The resource folders can't be changed during a Trial. Write anything the server needs to
keep to `scratch()`, and report it from `snapshot` if a Verifier should check it.

An Agent whose Harness can read files, such as a coding agent, can also read both
folders directly; `PLURAL_RESOURCES_DIR` points at them.

## 5. Check it and run it

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

`validate` starts the server, lists its tools, and prints them exactly as the model
will see them. Then write a Task and run it like any other:

```bash
plural run --task refund-t7 --model openai/gpt-5.6-luna
```

A server named with `server` runs inside the Runtime, fresh for every Trial, so it is
`owned` and can be used in Benchmarks and training. On a Docker or remote Runtime,
Plural installs FastMCP alongside itself.

## Start from Plural's files server

For an Agent that should work with documents and data, you may not need to write
anything. Plural ships a ready-made server over both resource folders:

```yaml
apps:
  - name: files
    mcp:
      server: plural.mcp.files:server
```

It offers:

| Tool | What it does |
| --- | --- |
| `list_files` | Lists `environment-resources/` and `task-resources/`, or a folder in them. |
| `read_file` | Reads a text file, a range of lines at a time. |
| `search_files` | Finds lines matching a regular expression, optionally only in files like `*.md`. |
| `list_tables` | Lists every CSV, JSON, JSONL, and SQLite file as tables, with their columns. |
| `query` | Runs one read-only SQL `SELECT` over those tables. |

Every tool only reads. A CSV, JSON, or JSONL file is a table named after the file; a
SQLite file's tables are named `<file>.<table>`. When the Environment and the Task both
have a file with the same name, the tables are `environment_resources_<name>` and
`task_resources_<name>`.

To let the Agent write, use `plural.mcp.files:writable`. It adds `write_file`, which
writes only to a third folder, `scratch/`, and its snapshot is every file written there,
for Verifiers.

To change what it offers, copy it into your Environment and edit it like your own:

```bash
plural env eject-files support-desk
```

```text
Wrote environments/support-desk/files_server.py. Point the App at it in environment.yaml:
  - name: files
    mcp:
      server: files_server.py:server
```

## Several Apps

An Environment can list your server beside others, such as a hosted CRM and the files
server. The Agent gets one list of tools; each keeps its own name, and only names that
clash are prefixed with their App. See
[What the Agent sees](../concepts/apps.md#what-the-agent-sees).

## Where to go next

- [Connect an MCP server](connect-mcp-server.md) that already exists, such as your CRM's.
- [Verifiers](../project/verifiers.md): score an episode from the snapshot.
- [Tasks](../project/tasks.md): starting states and per-Task files.
