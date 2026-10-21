---
route: /docs/start
title: Create an Environment
order: 22
description: "One command gives you an Environment that runs and scores. Start from nothing, an MCP server, an HTTP API, or an agent's traces."
audience: all
nav: true
nav_group: Start
---
# Create an Environment

An **Environment** is the world an Agent works in: the systems it can use, called
**Apps**, plus where it runs and its limits. Whatever you start from, one command
creates an Environment you can run at once:

| You start with | Run | You get |
| --- | --- | --- |
| Nothing yet | `plural env init NAME` | A FastMCP server you write, with a working example Task and Verifier |
| A game or simulation you'd rather write as a class | `plural env init NAME --python` | The same, with a Python `App` class |
| An MCP server | `plural app add NAME --mcp URL_OR_COMMAND` | An App offering the server's tools, and a read-only starter Task scored by a judge |
| An HTTP API | `plural app add NAME --openapi SPEC` | An App with one action per operation, and the same starter |
| Traces from an agent you already run | `plural app add NAME --traces FILE` | A replay App, one Task per trace, a judge, and a Benchmark |

This page assumes you have installed Plural, signed in, and created a project with
`plural project init`; [the Quickstart](../getting-started.md#1-create-an-account-and-install)
covers all three. If App, Task, and Verifier are new words, read
[Core concepts](../getting-started/concepts.md) first.

## Start from nothing

```bash
plural env init support-desk
plural run --task support-desk-first --model openai/gpt-5.6-luna
```

`plural env init` writes a small, complete example, and the run scores it:

```text
environments/support-desk/
├── environment.yaml        the Environment: its App, resources, Runtime, and limits
├── server.py               the App: a FastMCP server whose tools are the Agent's actions
├── README.md
└── resources/policy.md     a file the Agent can read
tasks/support-desk-first/
├── task.yaml               which Environment, which Verifier, and the starting State
└── instruction.md          what the Agent is asked to do
verifiers/support-desk-check/
├── verifier.yaml
└── verify.py               the check that scores the finished episode
```

The Task asks whether a customer gets a refund for an order delivered 45 days ago.
`server.py` offers two tools, `read_resource` and `submit`. The expected answer, store
credit, is in the Task's `initial_state`, which the server loads into its State at the
start of every episode. The Agent never sees State; the Verifier compares the Agent's
submission with it and scores 1 or 0.

### Make it yours

Every place to replace is marked `PLURAL-TODO`, and
`plural task validate support-desk-first` lists the ones left. Work through them in
this order, running the Task after each change:

1. **The tools**, in `server.py`. Each `@mcp.tool` is one move the Agent can make. Its
   docstring is what the Agent reads, and what it returns is all the Agent sees next.
   Mark tools that change nothing with `readOnlyHint`. See
   [Build an MCP server](../guides/build-mcp-server.md).
2. **The State**: what the tools read and change, and what `@plural.mcp.reset` loads
   from each Task's `initial_state`. Keep answers here, never in what a tool returns.
3. **The Task**: what `instruction.md` asks, and the `initial_state` it starts from.
   Add more Tasks with
   `plural task init NAME --environment support-desk --verifier support-desk-check`.
4. **The Verifier**: `check` in `verify.py` compares `episode.state` with what the Task
   asked for. See [Verifiers](../project/verifiers.md).
5. **The README**: what the world is, for the people who will use it.

An unfinished place never stops a local run, so you can try every change straight
away. It does stop `push`, `release`, and `run --record`, so a half-built Environment
never reaches your hosted project or a leaderboard.

To try the tools by hand, without a model, run `plural env serve support-desk` and
connect any MCP client to the URL it prints.

## Start from an MCP server

```bash
plural app add office --mcp "npx -y @modelcontextprotocol/server-memory"
plural run --task office-first --model openai/gpt-5.6-luna
```

`plural app add` starts the server, lists its tools, and marks the ones that change
nothing as `[read-only]`. It writes the Environment, a starter Task `office-first`, and
a Verifier `office-check`. The starter Task asks the Agent to call one tool that only
reads and report what it returned, so it is safe to run even against a live system. A
model judges each episode against the Task's instructions.

A hosted server works the same way. A `${NAME}` in a header is a credential the Agent
supplies, so each person runs as themselves:

```bash
plural app add crm --mcp https://mcp.example.com/mcp \
  --header 'Authorization=Bearer ${CRM_TOKEN}'
```

A run then needs an Agent that carries `CRM_TOKEN`: `plural run --task crm-first
--agent NAME`. [Connect an MCP server](../guides/connect-mcp-server.md) covers
credentials, choosing tools, and making a live server safe to benchmark.

Then replace the smoke test with the work you want to measure. For a score you can
rely on, swap the judge for a Verifier that queries the system itself; see
[Start from a system](from-a-system.md#5-write-a-verifier-that-queries-the-app).

## Start from an HTTP API

```bash
plural app add orders --openapi https://api.example.com/openapi.json
plural run --task orders-first --model openai/gpt-5.6-luna
```

Each operation in the document becomes an action, and `GET` operations are read-only.
Offer only some with `--operation ID`, repeated, and send requests somewhere other
than the document's servers with `--base-url`. A local document is copied into the
Environment, so a run doesn't depend on where it came from.

## Start from traces

```bash
plural app add support --traces conversations.jsonl
```

Every system the traces call becomes a replay App, which answers from the recorded
calls, so the work is repeatable without touching the real systems. Plural drafts one
Task per trace, a judge, and a Benchmark. See [Start from traces](from-traces.md).

## Combine systems

Run `plural app add` again with the same Environment name to add another App:

```bash
plural app add support-desk --mcp https://mcp.example.com/mcp
```

The new App's tools join the old ones. A tool is prefixed with its App's name only
when two Apps offer the same name. A starter Task is drafted only when the
Environment is new.

## Choose where it runs

A new Environment runs on `local`: the App and the Agent run as processes on your
machine, which needs no setup and is not a sandbox. When the Agent runs shell
commands, or the App is code you didn't write, run it in a container or a remote
sandbox instead:

```yaml
runtime:
  provider: docker          # needs Docker running
  image: python:3.12-slim
```

`provider: daytona` runs each Trial in a remote sandbox, on your Daytona account or
Plural's. See [Runtimes](../project/runtimes.md) and
[Record runs and run in the cloud](../platform/runs.md).

## Next

- Group Tasks into a Benchmark to compare models on them:
  `plural benchmark init NAME`, then `plural benchmark add TASK --benchmark NAME`. See
  [Benchmarks](../project/benchmarks.md).
- Record runs in the web app with `--record`, and push your work:
  [Record runs and run in the cloud](../platform/runs.md).
- Every field an Environment takes: [Environments](../project/environments.md) and
  [Apps](../concepts/apps.md).
