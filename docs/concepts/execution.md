# Packages, jobs, and trials

The environment owns the task contract and the execution surface. The
harness, when present, is stamped onto that environment. The agent is a
template (and optionally an instance). A job expands templates × tasks ×
attempts into trials.

## Ownership

An **Environment** owns instructions, native actions, tasks, guardrails,
resources, runtime, harness policy, and the isolated verifier. Hidden
`expected` and `verifier_input` values are never included in a harness
payload. Native actions are omitted from stamped-harness requests.

A **HarnessPackage** declares implementation (`declared` or `runnable`),
capabilities, and — when runnable — a command. A **HarnessStamp** is the
frozen grant on one environment revision.

An **AgentTemplate** binds a model to one environment identity and
optionally one stamp. A **JobSpec** combines the environment, benchmark,
and agent bindings. Planning expands:

`agents × selected task_ids × n_attempts = trials`

`RuntimeSpec.provider` is a requested target validated against
`environment.runtime.available_targets()`.

## Preflight

`resolve_effective_policy()` intersects provider, project, environment,
harness, and agent layers. Unsupported requirements raise
`CapabilityError` before any sandbox is created.

Declared harnesses fail with `harness <name> is declared but not runnable`.

See [execution capabilities](execution-capabilities.md).
