---
route: /docs/start/from-a-system
title: Start from a system
order: 23
description: "Add the systems your work happens in, such as an MCP server, an HTTP API, or a database, to an Environment as Apps. Then write a Verifier that checks the systems themselves and run models against it."
audience: all
nav: true
nav_group: Start
---
# Start from a system

**You start with** the systems the work happens in: Salesforce behind an MCP server, an
HTTP API with an OpenAPI document, or data in files or a database.

**You end with** an Environment with each system as an App, a Verifier that checks
the systems themselves rather than the Agent's claims, and a Benchmark you can run
any model on.

This page uses the open-source memory MCP server, a small knowledge graph, so every
command runs as written. It needs [Node.js](https://nodejs.org) for `npx`. The steps
are the same for your own system.

## 1. Pick the connection type

| Your system offers | Add it with |
| --- | --- |
| An MCP server, started locally or reached at a URL | `plural env add ENV --mcp URL_OR_COMMAND` |
| An HTTP API with an OpenAPI document | `plural env add ENV --openapi SPEC` |
| Recorded conversations of an agent using it | `plural env add ENV --traces FILE`; see [Start from traces](from-traces.md) |
| Files: documents, CSV, JSON, JSONL, or SQLite, with no API | Plural's files server, `server: plural.mcp.files:server`; see [Build an MCP server](../guides/build-mcp-server.md#start-from-plurals-files-server) |
| A database, warehouse, or data lake | Your own FastMCP server; see [Build an MCP server](../guides/build-mcp-server.md#work-in-a-data-lake-or-warehouse) |
| Nothing an Agent can call yet | `plural env init`, then write the tools; see [Build an MCP server](../guides/build-mcp-server.md) |

`plural env add` adds one system to an Environment as an App, whose actions are what
the system offers. It creates the Environment the first time, writing an ordinary
`environment.yaml`, and adds to it after that, so you run it once per system. A hosted
MCP server can also be added from the Environment's Apps tab, with **Add system**.
Create a project to hold it:

```bash
plural project init notes
cd notes
```

## 2. Add the system

```bash
plural env add office \
  --mcp "npx -y @modelcontextprotocol/server-memory" \
  --env 'MEMORY_FILE_PATH=${PLURAL_APP_DIR}/memory.jsonl'
```

```text
Created environment office:
  environments/office/environment.yaml
  environments/office/README.md

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

**What just happened.** Plural created the `office` Environment with one App, named
`memory` after the server's package. It started the server, listed its tools, and
wrote them down as the App's actions. Pass `--app NAME` to choose the App's name. `[read-only]` marks tools that say they change nothing. The
`--env` setting stores the server's graph in `${PLURAL_APP_DIR}`, a new empty folder
Plural gives the server for every episode, so no Trial sees what another stored.

## 3. Give the Agent its credentials

The memory server needs none. A system that does, such as a CRM reached over HTTP,
takes the credential of the Agent that runs, so each Agent acts as its own user with
its own scopes. The App names the credential; the Agent carries it. With your own CRM's
address in place of the example one:

```bash
plural env add sales \
  --mcp https://mcp.example.com/v1 --app crm \
  --header 'Authorization=Bearer ${CRM_TOKEN}'
plural agent init sales-bot
```

In `agents/sales-bot/agent.yaml`, list the credential and the scopes its token grants:

```yaml
credentials:
  CRM_TOKEN:
    scopes: [read:accounts, write:opportunities]
```

Then save your own token to your account, and check the Agent:

```bash
plural credential set CRM_TOKEN
plural agent validate sales-bot
```

Runs that use the CRM App then take `--agent sales-bot`.

**What just happened.** `${CRM_TOKEN}` stays a reference in `environment.yaml`, listed
under the App's `credentials`; the value never enters your project. `plural credential
set` prompts for it without echoing it and saves it, encrypted, to your account; a
coworker saves their own. The value goes only to the process that runs the Apps, never
to the model or its Harness, and each Trial records whose token acted, its scopes, and
a fingerprint of the value. A `--model` run carries no credentials, so it can't use this
App. See [Supply credentials](../guides/connect-mcp-server.md#4-supply-credentials).

## 4. Choose a control level

```bash
plural env validate office
```

```text
environment/office is valid: sha256:ee8a536cf853...

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

A server started with `command` or `server` is `owned`. A remote server is `live` until
you point it at a sandbox and give it `reset` and `snapshot` commands; see
[Make a remote server safe to benchmark](../guides/connect-mcp-server.md#5-make-a-remote-server-safe-to-benchmark).

:::details A server in the Runtime that works on an outside system
A server you start in the Runtime is `owned` because a fresh server is a fresh system.
That stops being true when its tools read or write something outside, such as a data
lake. Mark the App `remote: true` under `mcp:` and Plural treats it like a remote
server: `live`, or `sandboxed` once it has a reset hook.

A server that holds project `secrets` is treated that way already, since a secret
usually unlocks an outside system. If yours only unlocks something inside the Runtime,
such as a local database, mark it `remote: false`.
:::

## 5. Write a Verifier that queries the App

A Verifier decides what counts as good work. Its `check` scores the finished
episode, and that score is what Benchmarks rank on. Its optional `reward` function rewards
each action as it happens, for training.

```bash
plural verifier init remembered
```

Replace `verifiers/remembered/verify.py` with:

```python
"""Reward storing Ada Lovelace as a mathematician in the memory server."""

import json
from typing import Any

from plural import Episode, VerifierOutput, Step


def ada(found: Any) -> list[dict[str, Any]]:
    graph = found if isinstance(found, dict) else json.loads(found)
    return [item for item in graph.get("entities", []) if item["name"] == "Ada Lovelace"]


def check(episode: Episode) -> VerifierOutput:
    """Score the finished episode by asking the memory server, not the Agent's reply."""
    stored = ada(episode.apps["memory"].query("search_nodes", query="Ada Lovelace"))
    notes = " ".join(" ".join(item.get("observations", [])) for item in stored).lower()
    return VerifierOutput(score=float("mathematician" in notes), evidence=[json.dumps(stored)])


def reward(step: Step) -> float | None:
    """Reward each write that leaves Ada in the graph, and penalize a rejected call."""
    if step.error:
        return -0.1
    if step.action not in {"create_entities", "add_observations"}:
        return None
    stored = ada(step.apps["memory"].query("search_nodes", query="Ada Lovelace"))
    return 0.5 if stored else 0.0
```

In `verifiers/remembered/verifier.yaml`, turn on the `reward` function by uncommenting it:

```yaml
check: verify.py:check
reward: verify.py:reward
```

**What just happened.** `query` calls one of the App's read-only tools while the
Trial's Runtime is still running, so the Verifier checks what is actually in the
system. It refuses a tool that changes state, so a Verifier can't alter what it checks.
`check` runs once, after the episode. `reward` runs after every action, beside the
Apps, and `step.apps` reads any App in the Environment. Its rewards go to the Trial's
reward ledger, not into the score, and the Agent never sees either. An App with a
`snapshot` hook also offers `episode.apps["memory"].final`. See
[Verifiers](../project/verifiers.md).

## 6. Write a Task and a Benchmark

```bash
plural task init remember-ada --environment office --verifier remembered
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
on the Trial as a step with the App, the tool, its arguments, and its result. After
each call, the Verifier's `reward` function rewarded it. At the end, `check` asked the
server what it held. The evidence is the server's answer, not the model's. To see the
step rewards:

```bash
plural rewards show trl_25307cebd405ee1f5018590a
```

```text
step  e3     +0.500  step:remembered@0.1.0
```

## Several systems in one Environment

When the work spans systems, add each to the same Environment. Every `plural env add`
appends an App and keeps everything already there:

```bash
plural env add support --mcp https://mcp.example.com/v1 --app crm \
  --header 'Authorization=Bearer ${CRM_TOKEN}'
plural env add support --openapi billing.yaml \
  --header 'Authorization=Bearer ${BILLING_TOKEN}'
```

A server you write yourself is added by hand, as one more entry. The resulting
`apps:` in `environments/support/environment.yaml`:

```yaml
apps:
  - name: crm
    mcp:
      url: https://mcp.example.com/v1
      headers: {Authorization: "Bearer ${CRM_TOKEN}"}
      credentials: [CRM_TOKEN]
  - name: billing
    openapi:
      spec: billing.yaml
      headers: {Authorization: "Bearer ${BILLING_TOKEN}"}
      credentials: [BILLING_TOKEN]
  - name: desk
    mcp:
      server: server.py:mcp
```

The Agent gets one list of tools from all three. Run `plural env validate` to see it
exactly as the model will.

:::details What changes with several Apps
- **Tool names.** Each tool keeps its name. Only a name two Apps share is prefixed,
  such as `crm__search` and `desk__search`. Each description starts with its App, such
  as `[billing] Issue a refund.`
- **Credentials.** The Agent that runs supplies every credential the Apps list, here
  `CRM_TOKEN` and `BILLING_TOKEN`. A Job checks it has them all before it starts.
- **Control.** Each App keeps its own control level. A Benchmark accepts the
  Environment only if every `live` App is read-only, and training only if none is
  `live`.
- **Verifiers.** `episode.apps["crm"]` and `episode.apps["billing"]` each query their
  own system, so a Verifier's `check` can check that the refund and the CRM note both
  happened. Its `reward` reads every App through `step.apps` after each action, so it can
  reward a refund only once the CRM shows the ticket as eligible.
- **Effects across systems.** `Environment.on_step` sees every App, for rules such as
  "a refund also closes the ticket"; see [Apps](../concepts/apps.md).
:::

## Where you are now

You have a Benchmark, `memory`, that you can rerun on any model with
`plural run --benchmark memory --model <model>`, or repeat exactly with
`plural job rerun <job-id>`. The other two paths end in the same place.

Next:

- Add Tasks for the work you care about, each with its own starting state.
- Add the other systems the work touches with `plural env add`, as in
  [Several systems in one Environment](#several-systems-in-one-environment).
- The [MCP guide](../guides/connect-mcp-server.md) covers tool filters, Python hooks,
  and troubleshooting.
