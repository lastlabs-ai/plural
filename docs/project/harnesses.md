---
route: /docs/project/harnesses
title: Harnesses
order: 60
description: A Harness is how your Agent plays, the loop that asks the model what to do next. Use Plural's built-in loop, a well-known one by name, or write your own.
audience: all
nav: true
nav_group: Build
outcome: You can choose a built-in or custom Harness and understand where it runs.
---
# Harnesses

A **Harness** is *how* the Agent plays. A model on its own only answers messages. The
Harness is the loop around it that turns it into a working contestant: it shows the
model what it can see, asks what to do, carries out the move, reports back what
happened, and decides when to stop.

In Wordle, the Harness is what reads the colored tiles to the model, takes its next
guess, submits it to the game, and repeats until the word is found or the guesses run
out.

## Why it matters

Two Agents with the same model can score very differently depending on how they
play. Comparing Harnesses lets you answer questions like "is this model better on its
own, or inside Claude Code?" without changing the Tasks or the grading.

Most of the time you don't need to choose. There are three options:

- **Plural's native loop**, used when you pick nothing. Good for comparing models
  fairly, because every model plays the same way.
- **A built-in Harness** by name: `hermes`, `claude-code`, or `codex`. These are
  well-known agent tools that Plural installs for you.
- **Your own Harness**, a small Python class, when you need a loop of your own.

An agent that already runs as its own service needs no Harness at all. Make it an
[External Agent](external-agents.md), and Plural calls it once per episode instead.

## Where a Harness runs

An Agent brings the model, the instructions, and the Harness. The Environment brings
the world and its actions. **The Harness runs in the Runtime selected by the Task's
Environment**, the sealed place where the world runs, usually a Docker container.
Built-in Harnesses install their command-line tool there automatically, not on your
laptop.

## Start with Plural's native loop

You do not need to name a Harness for your first evaluation. Leave `harness` unset:

```python
from plural import Agent

agent = Agent(
    model="openai/gpt-5.6-luna",
    instructions="Use the available actions and stop when the Task is complete.",
)
```

Plural uses its action loop when the Environment provides actions, or its chat loop
otherwise. Use this to compare models under the same way of playing.

## Attach a built-in Harness

Hermes, Claude Code, and Codex attach by name:

```python
from plural import Agent

claude = Agent(
    model="anthropic/claude-sonnet-5",
    harness="claude-code",
    harness_config={"reasoning_effort": "high"},
)

codex = Agent(
    model="openai/gpt-5.6-luna",
    harness="codex",
    harness_config={"sandbox": "workspace-write"},
)

hermes = Agent(
    model="openai/gpt-5.6-luna",
    harness="hermes",
)
```

The same fields work in a project's `agents/support-claude/agent.yaml`:

```yaml
name: support-claude
model: anthropic/claude-sonnet-5
harness: claude-code
harness_config:
  reasoning_effort: high
```

Built-in Harnesses are never folders in `harnesses/`; name them directly in
`agent.yaml`. `plural agent validate support-claude` checks the name and every
option.

Plural checks the name and options before it starts a Runtime, then installs the
pinned version of the tool inside that Runtime. Built-ins use the same
`run(task, agent, environment)` lifecycle described below, so every Harness sees the
Environment through one interface.

### `harness_config` options

`harness_config` takes a different set of keys for each built-in. Every key is
optional; leave one out to use the tool's own default. Unknown names and invalid
values fail before the Runtime starts.

Every built-in accepts:

| Key | Type | Allowed values |
| --- | --- | --- |
| `version` | string | A release number of the tool, such as `2.1.236`, in place of the pinned one. npm aliases, URLs, and paths are refused. |
| `config` | mapping, JSON text, or file path | The tool's own settings. A path to a JSON or YAML file holding a mapping is loaded first. Plural stores the mapping and includes it in the Agent hash. |

Claude Code (`claude-code`, pinned to 2.1.236, Anthropic models only) also accepts:

| Key | Type | Allowed values |
| --- | --- | --- |
| `reasoning_effort` | string | `low`, `medium`, `high` |
| `permission_mode` | string | `default`, `acceptEdits`, `plan`, `bypassPermissions` |
| `max_turns` | integer | 1 or more. The most turns Claude Code takes in one Trial. |

Codex (`codex`, pinned to 0.153.2, OpenAI models only) also accepts:

| Key | Type | Allowed values |
| --- | --- | --- |
| `reasoning_effort` | string | `low`, `medium`, `high` |
| `sandbox` | string | `read-only`, `workspace-write`, `danger-full-access` |

Hermes (`hermes`, pinned to 0.19.0, any model) accepts only the shared keys.

A full example:

```yaml
name: support-claude
model: anthropic/claude-sonnet-5
harness: claude-code
harness_config:
  version: 2.1.236
  reasoning_effort: high
  permission_mode: acceptEdits
  max_turns: 40
  config: claude-settings.json
```

`plural harness show claude-code --json` prints the same options as JSON Schema,
with the pinned version.

### What Plural installs and how it runs

This section is for readers who want to know exactly what happens inside the
Runtime. Setup happens in the fresh Runtime, not on your laptop.

1. Plural installs the pinned tool. On Docker and Daytona it may install system tools
   as root first. The Harness itself then runs as the Runtime's default user.
2. The tool starts from the Environment workspace.
3. Model authentication comes from `Job(client=...)` or `Job(api_key=...)`. Those
   calls set `PLURAL_API_KEY` and `PLURAL_GATEWAY_URL`, and every model call goes
   through the Plural gateway. A vendor tool such as Codex or Claude Code is pointed
   at the gateway too, even when a provider key is in the environment. If a required
   name is missing, the run stops and the error names it. The error does not include
   the value. You do not put model keys on `Agent.secrets` for a built-in
   Harness. A custom Harness lists the names it reads in `secrets`, and the Agent
   requires that subset.
4. Environment actions are offered to the tool as tools.
5. `PLURAL_STOP_SECONDS` is how many seconds the Harness has before it is killed. A
   Harness that stops before then and writes its outputs is verified; one that is
   killed fails with the stop reason `harness_timeout`.
6. Claude Code talks to a local compatibility service that forwards its Messages
   requests to the Job's OpenAI-compatible model gateway. Codex and Hermes call that
   gateway directly.

The Runtime must allow the network access the installer and the model gateway need.
A `python:3.12-slim` image is enough for setup to add Node.js or pip tools. If the
image cannot install those tools, or the network policy blocks them, the Trial fails
with a clear error.

Use `Runtime.local()` only when you trust the machine. Local setup uses a tool
already on PATH, or installs into the Runtime workspace.

## Build a custom Harness

A custom Harness is a Python class with one required method: `run`. You do not
declare a command, source folder, output files, or transport. Plural finds the class
file, hashes its folder, runs it inside the Environment Runtime, and writes the
standard artifacts (the files each attempt leaves behind).

In a project, create the Harness folder from the template:

```bash
plural harness init support-loop
```

This writes `harness.yaml`, `harness.py`, and `README.md` in
`harnesses/support-loop/`. Replace `harness.py` with:

```python
import json

from plural import Harness, HarnessResult


class SupportHarness(Harness):
    name = "support-loop"
    version = "1.0.0"

    def run(self, task, agent, environment):
        observation = environment.reset()
        messages = [
            {"role": "system", "content": agent.instructions},
            {"role": "user", "content": task.instructions},
            {"role": "user", "content": f"Current observation: {observation}"},
        ]
        trajectory = []

        max_turns = int(self.config.get("max_turns", 20))
        for turn in range(max_turns):
            completion = agent.complete(messages, tools=environment.tools())
            trajectory.append(
                {"turn": turn, "type": "model", "text": completion.text}
            )
            if not completion.tool_calls:
                return HarnessResult(
                    response=completion.text,
                    trajectory=tuple(trajectory),
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": completion.text,
                    "tool_calls": list(completion.tool_calls),
                }
            )
            for call in completion.tool_calls:
                function = call["function"]
                arguments = json.loads(function.get("arguments") or "{}")
                step = environment.step(function["name"], **arguments)
                trajectory.append(
                    {
                        "turn": turn,
                        "type": "action",
                        "name": function["name"],
                        "arguments": arguments,
                        "observation": step.observation,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(step.observation),
                    }
                )

        return HarnessResult(
            response=f"Stopped after {max_turns} turns.",
            trajectory=tuple(trajectory),
        )
```

In plain words: the loop starts the world, shows the model the instructions and
what it can see, and then keeps asking the model for its next move. Each move is
carried out in the Environment, and only the resulting Observation is sent back.
When the model stops asking for moves, or the turn limit is reached, the loop ends.

The `run` arguments are the same for every custom Harness:

- `task` exposes `id`, `name`, `instructions`, `info`, and `metadata`.
- `agent` exposes the selected model and instructions. Call
  `agent.complete(messages, tools=...)` to use the Job's model gateway.
- `environment` exposes `observation`, `reset()`, `step(action, **arguments)`, and
  `tools()`. These methods run the real Environment commands; the Harness never needs
  to parse command metadata. `step` returns the transition's `observation`, `reward`,
  `terminated`, `truncated`, and `info`.

> **Important:** Send only the observation to the model. A reward or termination flag
> in the model's context can leak the expected outcome.

`run` may be synchronous or asynchronous. Return a `HarnessResult`, a string, or a
JSON-compatible mapping. `HarnessResult` lets you include structured trajectory
events, logs, metadata, and a trace ID. Plural always writes `result.json`; it writes
`trajectory.jsonl` and `logs.txt` when those values are present. The Harness does not
write files or emit runner events itself.

### Attach the custom Harness

```python
from plural import Agent

harness = SupportHarness()

agent = Agent(
    name="support-custom",
    model="openai/gpt-5.6-luna",
    instructions="Follow the support policy and finish the ticket.",
    harness=harness,
)
```

Plural uses the folder containing `SupportHarness` as its source. Imports, helper
modules, prompts, and other files beside the class are included in the same content
hash, a fingerprint that changes whenever any of those files change.

Pass reusable settings through the inherited `config` field and read them from
`self.config` inside `run`:

```python
harness = SupportHarness(config={"max_turns": 12})
```

When you need them, class attributes describe policy and compatibility:

```python
from plural import Harness
from plural.common import HarnessCapability


class ResearchHarness(Harness):
    name = "research-loop"
    version = "1.0.0"
    capabilities = frozenset({HarnessCapability.NETWORK_FETCH})
    models = ("openai/*",)
    secrets = ("SEARCH_API_KEY",)

    def run(self, task, agent, environment):
        ...
```

Grant application secrets through the Agent's `secrets`. Model authentication
still comes from `Job(client=...)` or `Job(api_key=...)`. Custom Python dependencies
must already be available in the Environment Runtime.

### Save the Harness in a project

A project Harness is a folder under `harnesses/`:

```text
harnesses/support-loop/
  harness.yaml   # identity, the class to run, and its settings
  harness.py     # the Harness subclass
  README.md      # the overview shown on the Harness page
```

The Harness page in Plural Intel shows the README above the folder's code, so a
reader sees what the loop does and then exactly how. Use the README for what the code
doesn't say on its own: what the model is shown each turn, how it is asked for its
next move, how the move is carried out, and when the loop stops.

`harness.yaml` names the class and supplies its settings, instead of repeating how
to run it:

```yaml
name: support-loop
version: 1.0.0
description: Tool loop that follows the support policy.
python: harness.py:SupportHarness
config:
  max_turns: 12
```

The manifest supplies the Harness's identity, so a class saved in a project does not
need `name` or `version` attributes; values set there are replaced by the
manifest's.

### `harness.yaml` fields

Unknown keys are errors, so a misspelled field fails validation instead of being
ignored.

| Field | Required | Type | Default | Allowed values |
| --- | --- | --- | --- | --- |
| `name` | Yes | string | | The folder name under `harnesses/`: lowercase letters, digits, and single hyphens, up to 63 characters, such as `support-loop`. |
| `version` | No | string | `0.1.0` | A semantic version, such as `1.2.0` or `2.0.0-beta.1`. |
| `description` | No | string | `""` | One line on what the loop is for. Shown under the Harness name. |
| `python` | Yes | string | | The Harness subclass as `file.py:ClassName`, relative to the folder. The file must stay inside the folder. |
| `config` | No | mapping | `{}` | Any JSON-compatible keys and values. The class reads them as `self.config`. |
| `readme` | No | string or `null` | `README.md` | A Markdown file inside the folder. Left at the default, a missing file is skipped; named explicitly, a missing file is an error. `null` turns it off. |
`config` has no fixed keys: its keys are whatever your class reads. Document each one
in the README, with its type and default, and read it with a fallback so a missing
key still runs:

```python
max_turns = int(self.config.get("max_turns", 20))
```

A `config` value must be JSON-compatible: a string, a number, `true` or `false`,
`null`, a list, or a mapping of those. It is part of the Harness hash, so changing
a value makes a new version.

An Agent can change these options without a second Harness. The keys in its
`agent.yaml` `harness_config:` replace the same keys in `config:` for that Agent's
runs, and the Agent's hash records them:

```yaml
name: careful
model: openai/gpt-5.6-luna
harness: support-loop
harness_config:
  max_turns: 30
```

A Harness defined only in Python sets its README as the `readme` class attribute, a
Markdown string. Like every file in the folder, the README is part of the Harness
hash, so editing it saves a new version.

An Agent uses the Harness by name in `agent.yaml`:

```yaml
name: support-custom
model: openai/gpt-5.6-luna
instructions: Follow the support policy and finish the ticket.
harness: support-loop
```

Validating or pushing the Agent includes the Harness it names, so this pushes both:

```bash
plural agent push support-custom --with-deps
```

Try the Harness on one Task before scaling up:

```bash
plural run --task ticket-1 --agent support-custom --dry-run
plural run --task ticket-1 --model openai/gpt-5.6-luna --harness support-loop
```

The dry run checks the configuration. A live run checks that the code, its
dependencies, its outputs, and the scoring work together. The second command passes
the Harness inline, without a saved Agent.

A run started with `--model` always expects a model credential. To run a Harness that
never calls a model, save an Agent with `auth: none`, as the `scripted` Agent in
the [first project](../tutorials/first-project.md) does.

## Tools, permissions, and training

There are two kinds of tools in play:

- **Environment actions** are the moves available in the world, like `guess` in
  Wordle.
- **Harness capabilities** are extra tools the loop itself brings, such as file access
  or web search.

An Environment's `harness_policy` can restrict which Harnesses or capabilities are
allowed. See [Harness and Environment policy](../concepts/harness-policy.md). Runtime
controls enforce the real boundary; capability declarations alone do not isolate
arbitrary code.

For training, the Harness must capture the exact tokens in and tokens out and declare
the matching artifact. Ordinary transcripts do not satisfy that requirement. See
[Training and RL](../running/training.md).

## Trajectories use ATIF

This section is for readers exchanging records with other tools. A *trajectory* is
the step-by-step record of what the Agent saw and did.

The trajectory file to exchange with other tools is `atif-trajectory.json`, in ATIF,
the Agent Trajectory Interchange Format. Current ATIF is `ATIF-v1.7`: an `agent`
block, ordered `steps`, and optional `final_metrics`. Put Plural-only notes in the
format's `extra` field. A reward stays on the episode, and a verifier score stays on
the Trial; neither is an ATIF step.

`normalize_trajectory` reads an ATIF document as well as Plural's own JSON and JSONL
trajectories. For any Harness that runs through Plural's episode, including the
built-in loops, Plural derives `atif-trajectory.json` from `episode.jsonl` itself, along with
`trajectory.json`, the same turns as plain chat messages. A
command-based Harness spec (`HarnessDefinition`) that writes ATIF sets its
`trajectory` field to `atif-trajectory.json`.

Next, choose a model and instructions in [Agents](agents.md).
