---
route: /docs/project/harnesses
title: Harnesses
order: 60
description: Attach a built-in agent loop by name, or write a custom Harness when you need your own executable.
audience: all
nav: true
nav_group: Build
outcome: You can choose a built-in or custom Harness and understand where it runs.
---
# Harnesses

A Harness is the loop that turns a model into a working agent. It sends information to the model, executes the tools it requests, returns the results, and decides when to stop.

An Agent combines a model, instructions, and a Harness. The Environment supplies the world and its actions. **The Harness runs in the Runtime selected by the Task's Environment.** Built-in Harnesses install their CLI there automatically.

## Start with Plural's native loop

You do not need to name a Harness for your first evaluation. Leave `harness` unset:

```python
from plural import Agent

agent = Agent(
    model="openai/gpt-5.6-luna",
    instructions="Use the available actions and stop when the Task is complete.",
)
```

Plural uses its action loop when the Environment provides actions, or its chat loop otherwise. Use this to compare models under the same interaction strategy.

## Attach a built-in Harness

Hermes, Claude Code, and Codex attach by name. Plural validates the name and options before it creates a Runtime, then installs the pinned CLI inside that Runtime.
Their implementations use the same `run(task, agent, environment)` lifecycle
described below, so every Harness sees the Environment through one interface.

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

Built-in Harnesses are never directories in `harnesses/`; name them directly in `agent.yaml`. `plural agent validate support-claude` checks the name and every option.

### Shared options

Every built-in accepts:

- **`version`** — override the release-pinned CLI version.
- **`config`** — native CLI settings as an inline mapping or a file path. Plural loads a path, stores the mapping, and includes it in the Agent hash.

Claude Code also accepts `reasoning_effort`, `permission_mode`, and `max_turns`. Codex also accepts `reasoning_effort` and `sandbox`.

Unknown names and invalid options fail before the Runtime starts.

### What Plural installs and how it runs

Setup happens inside the fresh Runtime, not on your laptop.

1. Plural installs the pinned CLI. On Docker and Daytona it may install system tools as root first. The Harness itself then runs as the Runtime's default user.
2. The CLI starts from the Environment workspace.
3. Model authentication comes from `Job(client=...)` or `Job(api_key=...)`. Those calls set `PLURAL_API_KEY`, `OPENAI_API_KEY`, or `PLURAL_GATEWAY_URL`. If a required name is missing, the run stops and the error names it. The error does not include the value. You do not put model keys on `Agent.secret_names` for a built-in Harness. A custom Harness lists the names it reads in `secrets`, and the Agent requires that subset.
4. Environment actions are exposed to the CLI as tools.
5. Claude Code talks to a local compatibility service that forwards its Messages requests to the Job's OpenAI-compatible model gateway. Codex and Hermes call that gateway directly.

The Runtime must allow the network the installer and model gateway need. A `python:3.12-slim` image is enough for setup to add Node.js or pip tools. If the image cannot install those tools, or the network policy blocks them, the Trial fails with a clear error.

Use `Runtime.local()` only when you trust the machine. Local setup uses a CLI already on PATH, or installs into the Runtime workspace.

## Build a custom Harness

A custom Harness is a Python class with one required method: `run`. You do not
declare a command, source directory, output files, or transport. Plural finds the
class file, hashes its directory, runs it inside the Environment Runtime, and
writes the standard artifacts.

In a project, create the Harness directory from the template:

```bash
plural harness init support-loop
```

This writes `harnesses/support-loop/harness.yaml` and `harnesses/support-loop/harness.py`. Replace `harness.py` with:

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

The `run` arguments are the same for every custom Harness:

- `task` exposes `id`, `name`, `instructions`, `info`, and `metadata`.
- `agent` exposes the selected model and instructions. Call
  `agent.complete(messages, tools=...)` to use the Job's model gateway.
- `environment` exposes `observation`, `reset()`, `step(action, **arguments)`,
  and `tools()`. These methods execute the real Environment commands; the
  Harness never needs to parse command metadata. `step` returns the
  transition's `observation`, `reward`, `terminated`, `truncated`, and `info`.
  Send only the observation to the model: a reward or termination flag in the
  model's context can leak the expected outcome.

`run` may be synchronous or asynchronous. Return a `HarnessResult`, a string,
or a JSON-compatible mapping. `HarnessResult` lets you include structured
trajectory events, logs, metadata, and a trace ID. Plural always writes
`result.json`; it writes `trajectory.jsonl` and `logs.txt` when those values are
present. The Harness does not write files or emit runner events itself.

## Trajectories use ATIF

The trajectory file to exchange with other tools is [`trajectory.json` in ATIF](https://docs.harborframework.com/core-concepts/agents/atif), Harbor's Agent Trajectory Interchange Format. Current ATIF is `ATIF-v1.7`: an `agent` block, ordered `steps`, and optional `final_metrics`. Put Plural-only notes in the schema's `extra` field. A reward stays on the episode, and a verifier score stays on the trial; neither is an ATIF step.

`normalize_trajectory` reads an ATIF document as well as Plural's own JSON and JSONL trajectories. Built-in loops write `trajectory.jsonl`. A Harness described by a `HarnessDefinition` that writes ATIF sets its `trajectory` field to `trajectory.json`. The spec is Harbor's [ATIF RFC](https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md).

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

Plural uses the directory containing `SupportHarness` as its source. Imports,
helper modules, prompts, and other files beside the class are included in the
same content hash.

Pass reusable settings through the inherited `config` field and read them from
`self.config` inside `run`:

```python
harness = SupportHarness(config={"max_turns": 12})
```

Class attributes describe policy and compatibility when needed:

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

Grant application secrets through the Agent's `secret_names`. Model
authentication still comes from `Job(client=...)` or `Job(api_key=...)`.
Custom Python dependencies must already be available in the Environment
Runtime.

### Save the Harness in a project

`harnesses/support-loop/harness.yaml` names the class and supplies its configuration, instead of repeating execution details:

```yaml
name: support-loop
version: 1.0.0
description: Tool loop that follows the support policy.
python: harness.py:SupportHarness
config:
  max_turns: 12
```

`name` must match the directory name. The manifest supplies the Harness's identity, so a class saved in a project does not need `name` or `version` attributes; values set there are replaced by the manifest's. An Agent uses the Harness by name in `agent.yaml`:

```yaml
name: support-custom
model: openai/gpt-5.6-luna
instructions: Follow the support policy and finish the ticket.
harness: support-loop
```

Validating or pushing the Agent includes the Harness it names, so `plural agent push support-custom --with-deps` pushes both.

Try the Harness on one Task before scaling up. `plural run --task ticket-1 --agent support-custom --dry-run` checks configuration; a live run checks that the implementation, dependencies, outputs, and scoring work together. You can also pass the Harness inline, as in `plural run --task ticket-1 --model openai/gpt-5.6-luna --harness support-loop`. A run started with `--model` always expects a model credential; to run a Harness that never calls a model, save an Agent with `auth_mode: none`, as the `scripted` Agent in the [first project](../tutorials/first-project.md) does.

## Tools, permissions, and training

Environment actions describe the work available in the world. Harness capabilities describe extra tools used by the agent loop, such as file access or web search. An Environment's `harness_policy` can restrict which Harnesses or capabilities are allowed. Runtime controls enforce the execution boundary; capability declarations alone do not isolate arbitrary code.

For training, the Harness must capture exact tokens in and tokens out and declare the corresponding artifact. Ordinary transcripts do not satisfy that requirement. See [Training and RL](../running/training.md).

Next, choose a model and instructions in [Agents](agents.md).
