---
route: /docs/concepts/harness-policy
title: "Harness and Environment policy"
order: 140
description: "A Harness wraps the LLM. An Environment is the world. The Environment may forbid harness tools; it does not own the Agent loop."
audience: all
---
# Harness and Environment policy

A **Harness** wraps the LLM. It owns extra instructions, tools, skills, and
the loop that decides what to do. It belongs to the **Agent**, not the
Environment.

An **Environment** is the world. Native actions are what the Agent performs
there. The Environment parses those calls and returns observations. It does
not wrap the model.

When a Trial runs, the Agent executes inside that Task's Environment
runtime. The Environment may forbid harness tools — for example
`network=none` removes web search. That is a ceiling, not ownership.

## Two tool classes

- `environment.<action>` is parsed and executed by the Environment. The
  Agent always receives world actions.
- `harness.<tool>` is parsed by the harness. Restricted or unknown harness
  tools return `{error: "denied", reason}` and the Trial continues.

Skills and instructions stay harness-owned. Soft denials are injected
before the first turn: "`web_search` is unavailable because this
Environment has no public internet."

Hard-fail only if a denied capability is **successfully performed**.
Harness stdout still must not smuggle scores or rewards.

## Declared versus runnable

`HarnessDefinition.implementation` is `declared` or `runnable`. Declared
harnesses have no command. They can be registered, granted, referenced by
an Agent, and rendered in the UI. They cannot execute a Trial.

This release ships four declared definitions — `hermes`, `claude-code`,
`codex`, `cursor` — and one runnable executor: the native runner
(`native.chat.v1`, `native.actions.v1`). Vendor subprocess loops attach
later without changing ownership.

A job that names a declared harness fails at preflight:

```
harness <name> is declared but not runnable
```

## How a grant is computed

`resolve_trial_harness_grant(environment, agent)` starts from the Harness
declared capabilities and only subtracts:

1. `environment.harness_policy.denied_capabilities`
2. The optional environment allowlist
3. Derived network denials (`network=none` removes `web_search`, `browser`,
   `network_fetch`, `mcp`; `restricted` removes `web_search` and `browser`)
4. `file_edit` when `read_only_root` is set

`HarnessRunRequest` carries `granted_capabilities`, `denied_capabilities`,
and `capability_denials` (`{capability, reason}`).
