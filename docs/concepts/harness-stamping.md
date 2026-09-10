---
route: /docs/concepts/harness-stamping
title: "Harness stamping"
order: 140
description: "Stamping freezes what one harness revision may do on one environment revision. Implementations of vendor loops are out of scope; the mechanism and the grant matrix are not."
audience: all
---
# Harness stamping

Stamping freezes what one harness revision may do on one environment
revision. Implementations of vendor loops are out of scope; the mechanism
and the grant matrix are not.

## Declared versus runnable

`HarnessManifest.implementation` is `declared` or `runnable`. Declared
harnesses have no command. They can be registered, stamped, referenced by a
template, and rendered in the UI. They cannot execute a trial.

This release ships four declared manifests — `hermes`, `claude-code`,
`codex`, `cursor` — and one runnable executor: the native runner
(`native.chat.v1`, `native.actions.v1`).

A job that names a declared harness fails at preflight:

```
harness <name> is declared but not runnable
```

## How a stamp is computed

`resolve_trial_harness_stamp(environment, agent)` starts from the Harness
declared capabilities and only subtracts:

1. `environment.harness_policy.denied_capabilities`
2. The optional environment allowlist
3. Derived network denials (`network=none` removes `web_search`, `browser`,
   `network_fetch`, `mcp`; `restricted` removes `web_search` and `browser`)
4. `file_edit` when `read_only_root` is set

An empty grant is a configuration error. A stale stamp (not equal to a
freshly recomputed one) is rejected.

```bash
plural env harness stamp ./harness
plural env harness capabilities ./harness
plural env harness unstamp hermes
```

## Runtime enforcement

`HarnessRunRequest` carries `granted_capabilities` and
`denied_capabilities`. If a harness emits `HarnessEvent(type="capability")`
for a capability that was not granted, the trial fails with
`protocol_failed`.
