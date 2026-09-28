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
    harness_kwargs={"reasoning_effort": "high"},
)

codex = Agent(
    model="openai/gpt-5.6-luna",
    harness="codex",
    harness_kwargs={"sandbox": "workspace-write"},
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
harness_kwargs:
  reasoning_effort: high
```

Built-in Harnesses are never folders in `harnesses/`; name them directly in
`agent.yaml`. `plural agent validate support-claude` checks the name and every
option.

Plural checks the name and options before it starts a Runtime, then installs the
pinned version of the tool inside that Runtime. Built-ins use the same
`run(task, agent, environment)` lifecycle described below, so every Harness sees the
Environment through one interface.

### Shared options

Every built-in accepts:

- **`version`**: override the release-pinned tool version.
- **`config`**: the tool's own settings, as an inline mapping or a file path. Plural
  loads a path, stores the mapping, and includes it in the Agent hash.

Claude Code also accepts `reasoning_effort`, `permission_mode`, and `max_turns`.
Codex also accepts `reasoning_effort` and `sandbox`.

Unknown names and invalid options fail before the Runtime starts.

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
   the value. You do not put model keys on `Agent.secret_names` for a built-in
   Harness. A custom Harness lists the names it reads in `secrets`, and the Agent
   requires that subset.
4. Environment actions are offered to the tool as tools.
5. Claude Code talks to a local compatibility service that forwards its Messages
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

This writes `harnesses/support-loop/harness.yaml` and
`harnesses/support-loop/harness.py`. Replace `harness.py` with:

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
from plural import Harness, HarnessCapability


class ResearchHarness(Harness):
    name = "research-loop"
    version = "1.0.0"
    capabilities = frozenset({HarnessCapability.NETWORK_FETCH})
    models = ("openai/*",)
    secrets = ("SEARCH_API_KEY",)

    def run(self, task, agent, environment):
        ...
```

Grant application secrets through the Agent's `secret_names`. Model authentication
still comes from `Job(client=...)` or `Job(api_key=...)`. Custom Python dependencies
must already be available in the Environment Runtime.

### Save the Harness in a project

`harnesses/support-loop/harness.yaml` names the class and supplies its settings,
instead of repeating how to run it:

```yaml
name: support-loop
version: 1.0.0
description: Tool loop that follows the support policy.
python: harness.py:SupportHarness
config:
  max_turns: 12
```

`name` must match the folder name. The manifest supplies the Harness's identity, so a
class saved in a project does not need `name` or `version` attributes; values set
there are replaced by the manifest's. An Agent uses the Harness by name in
`agent.yaml`:

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
never calls a model, save an Agent with `auth_mode: none`, as the `scripted` Agent in
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

The trajectory file to exchange with other tools is
[`trajectory.json` in ATIF](https://docs.harborframework.com/core-concepts/agents/atif),
Harbor's Agent Trajectory Interchange Format. Current ATIF is `ATIF-v1.7`: an `agent`
block, ordered `steps`, and optional `final_metrics`. Put Plural-only notes in the
format's `extra` field. A reward stays on the episode, and a verifier score stays on
the Trial; neither is an ATIF step.

`normalize_trajectory` reads an ATIF document as well as Plural's own JSON and JSONL
trajectories. For any Harness that runs through Plural's episode, including the
built-in loops, Plural derives `trajectory.json` from `episode.jsonl` itself. A
command-based Harness spec (`HarnessDefinition`) that writes ATIF sets its
`trajectory` field to `trajectory.json`. The spec is Harbor's
[ATIF RFC](https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md).

Next, choose a model and instructions in [Agents](agents.md).
