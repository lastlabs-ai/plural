---
route: /docs/concepts/harness-policy
title: Harness and Environment policy
order: 140
description: A Harness wraps the LLM. An Environment is the world. The Environment may forbid harness tools; it does not own the Agent loop.
audience: all
nav: false
---
# Harness and Environment policy

A **Harness** wraps the LLM. It owns extra instructions, tools, skills, and
the loop that decides what to do. It belongs to the **Agent**, not the
Environment.

An **Environment** is the world. Native actions are what the Agent performs
there. The Environment runs those actions and returns observations. It does
not wrap the model.

When a Trial runs, the Harness executes inside the Runtime of that Task's
Environment. The Environment can forbid Harness tools; for example, an
Environment with `network: no-network` removes web search. That is a ceiling,
not ownership of the loop.

## Two kinds of tools

- **Environment actions** are run by the Environment. The Agent always receives
  them, and they cannot be denied.
- **Harness tools**, such as web search or file editing, are run by the Harness.
  When the Environment denies one, calling it returns an error with the reason
  (`{"error": "denied", "reason": ...}`), and the Trial continues.

Skills and instructions stay with the Harness. Plural's native loop tells the
model which tools are unavailable before the first turn, for example "`web_search`
is unavailable because Environment network=none."

Nothing a Harness writes can add a score, a reward, or new actions to the Trial.

## Built-in versus custom

Omit `harness` on the Agent to use `native`, Plural's built-in tool loop. Set it
to `"claude-code"`, `"codex"`, or `"hermes"` for a vendor CLI, or to an instance
of your own `Harness` subclass when you need a custom loop:

```python
from plural import Agent, Harness, HarnessResult


class ResearchHarness(Harness):
    def run(self, task, agent, environment):
        completion = agent.complete(
            [{"role": "user", "content": task.instructions}],
            tools=environment.tools(),
        )
        return HarnessResult(response=completion.text)


harness = ResearchHarness()
agent = Agent(model="openai/gpt-5.6-luna", harness=harness)
```

Plural records the content hash of the Harness's directory and its configuration
before a Trial starts. Every Harness receives the same Task, Agent, and
Environment interface. See [Harnesses](../project/harnesses.md).

## How the Environment limits a Harness

An Environment's `harness_policy` sets which Harnesses may run and which
capabilities they keep:

```yaml
harness_policy:
  mode: allowlist
  allowed_harnesses: [native, support-loop]
  denied_capabilities: [web_search]
```

- `mode: allow_all`, the default, accepts any Harness. `mode: allowlist` accepts
  only the Harnesses named in `allowed_harnesses`; any other is refused before
  the run starts. Include `native` to allow Plural's built-in loop.
- `denied_capabilities` removes the listed capabilities.
- `allowed_capabilities`, when set, removes every capability not listed.

Plural starts from the capabilities the Harness declares and only ever removes
some. On top of the policy above, it removes:

- `web_search`, `browser`, `network_fetch`, and `mcp` when the Runtime's network
  is `no-network`;
- `web_search` and `browser` when the network is `allowlist`;
- `file_edit` when the Runtime has a read-only root.

The capabilities are `shell`, `file_read`, `file_edit`, `code_execution`,
`web_search`, `browser`, `network_fetch`, `mcp`, `subagents`, and `persistence`.
Each Trial's receipt records the capabilities that were declared, granted, and
denied, with the reason for each denial. Capability declarations describe the
Harness; only the Runtime isolates code, so use Docker or a remote Runtime for a
Harness you do not trust.
