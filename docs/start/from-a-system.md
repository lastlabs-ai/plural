---
route: /docs/start/from-a-system
title: Start from a system
order: 23
description: "Connect a system your work happens in, such as an MCP server, an HTTP API, or a database, as an App. Then write a Verifier that checks the system itself and run models against it."
audience: all
nav: true
nav_group: Start
---
# Start from a system

**You start with** a system the work happens in: Salesforce behind an MCP server, an
HTTP API with an OpenAPI document, or data in files or a database.

**You end with** that system as an App, a Verifier that checks the system itself rather
than the Agent's claims, and a Benchmark you can run any model on.

This page uses the open-source memory MCP server, a small knowledge graph, so every
command runs as written. It needs [Node.js](https://nodejs.org) for `npx`. The steps
are the same for your own system.

## 1. Pick the connection type

| Your system offers | Draft it with |
| --- | --- |
| An MCP server, started locally or reached at a URL | `plural env from-mcp` |
| An HTTP API with an OpenAPI document | `plural env from-openapi` |
| Data in CSV, JSON, JSONL, or SQLite, with no API | `plural env from-data` |

Each one drafts an ordinary `environment.yaml` with one App, whose actions are what the
system offers. Create a project to hold it:

```bash
plural project init notes
cd notes
```

## 2. Draft the Environment

```bash
plural env from-mcp memory \
  --command "npx -y @modelcontextprotocol/server-memory" \
  --env 'MEMORY_FILE_PATH=${PLURAL_APP_DIR}/memory.jsonl'
```

```text
Drafted environment memory:
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

**What just happened.** Plural started the server, listed its tools, and wrote them down
as the App's actions. `[read-only]` marks tools that say they change nothing. The
`--env` setting stores the server's graph in `${PLURAL_APP_DIR}`, a new empty folder
Plural gives the server for every episode, so no Trial sees what another stored.

## 3. Attach secrets

The memory server needs none. A system that does, such as a CRM reached over HTTP,
names its secrets on the App, and you store each value once in the hosted project:

```bash
plural env from-mcp crm \
  --url https://mcp.example.com/v1 \
  --header 'Authorization=Bearer ${CRM_TOKEN}' \
  --secret CRM_TOKEN
plural secret set CRM_TOKEN
```

**What just happened.** `${CRM_TOKEN}` stays a reference in `environment.yaml`; the
value never enters your project. `plural secret set` prompts for it without echoing it.
Every `plural run` in the project, and every hosted Job, fills it in. An exported
variable of the same name wins. The value goes only to the process that runs the Apps,
never to the Agent or its Harness. `plural env validate` says where each secret will
come from. See [Supply secrets](../guides/connect-mcp-server.md#4-supply-secrets).

## 4. Choose a control level

```bash
plural env validate memory
```

```text
environment/memory is valid: sha256:ee8a536cf853...

App memory (mcp, owned)
  create_entities
  ...
```

**What just happened.** Every App has a control level, which decides where it can be
used:

| Control | Meaning | Benchmarks | Training |
| --- | --- | --- | --- |
| `owned` | Plural starts it fresh for every Trial. | Yes | Yes |
| `sandboxed` | A shared system with a `reset` hook that restores it each Trial. | Yes | Yes |
| `live` | A shared system Plural can't reset. | Only if every action is read-only, and then marked not reproducible | No |

A server started with `command` is `owned`. A remote server is `live` until you point
it at a sandbox and give it `reset` and `snapshot` commands; see
[Make a remote server safe to benchmark](../guides/connect-mcp-server.md#5-make-a-remote-server-safe-to-benchmark).

## 5. Write a Verifier that queries the App

```bash
plural verifier init remembered
```

Replace `verifiers/remembered/verify.py` with:

```python
"""Score whether the memory server holds Ada Lovelace as a mathematician."""

import json

from plural import Episode, VerifierOutput


def verify(episode: Episode) -> VerifierOutput:
    """Ask the memory server itself, not the Agent's reply."""
    found = episode.apps["memory"].query("search_nodes", query="Ada Lovelace")
    graph = found if isinstance(found, dict) else json.loads(found)
    ada = [item for item in graph.get("entities", []) if item["name"] == "Ada Lovelace"]
    notes = " ".join(" ".join(item.get("observations", [])) for item in ada).lower()
    return VerifierOutput(score=float("mathematician" in notes), evidence=[json.dumps(ada)])
```

**What just happened.** `query` calls one of the App's read-only tools while the
Trial's Runtime is still running, so the Verifier checks what is actually in the
system. It refuses a tool that changes state, so a Verifier can't alter what it checks.
An App with a `snapshot` hook also offers `episode.apps["memory"].final`.

## 6. Write a Task and a Benchmark

```bash
plural task init remember-ada --environment memory --verifier remembered
plural benchmark init memory
plural benchmark add remember-ada --benchmark memory
```

Replace `tasks/remember-ada/instruction.md` with what the Agent must do:

```text
Store this in memory: Ada Lovelace is a person. Add the observation that she was a
mathematician who wrote the first published algorithm.
```

In `benchmarks/memory/benchmark.yaml`, set `purpose` and `scoring.description`, and
describe the Benchmark in its `README.md`. Each place to fill in is marked
`PLURAL-TODO`. Then check the whole thing:

```bash
plural benchmark validate memory
```

## 7. Run a Job

```bash
plural run --benchmark memory --model openai/gpt-5.6-luna
```

```text
  [1/1] trl_25307cebd405ee1f5018590a  remember-ada  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
Job job_0feea5c3744a03eafec701d9 succeeded.
  gpt-5.6-luna: mean score 1.000 over 1 trial(s), 1 succeeded
```

```bash
plural trial show trl_25307cebd405ee1f5018590a
```

```text
  Verifier remembered: succeeded score=1.0
    - [{"entityType": "person", "name": "Ada Lovelace", "observations": ["She was a mathematician who wrote the first published algorithm."]}]
```

**What just happened.** The model called the server's tools, and each call was recorded
on the Trial as a step with the App, the tool, its arguments, and its result. The
Verifier then asked the server what it held. The evidence is the server's answer, not
the model's.

## Where you are now

You have a Benchmark, `memory`, that you can rerun on any model with
`plural run --benchmark memory --model <model>`, or repeat exactly with
`plural job rerun <job-id>`. The other two paths end in the same place.

Next:

- Add Tasks for the work you care about, each with its own starting state.
- Compose several systems into one Environment by listing more Apps; see
  [Apps](../concepts/apps.md).
- The [MCP guide](../guides/connect-mcp-server.md) covers tool filters, Python hooks,
  and troubleshooting.
