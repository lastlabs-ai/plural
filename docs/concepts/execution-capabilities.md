---
route: /docs/concepts/execution-capabilities
title: "Execution capabilities"
order: 150
description: "The environment declares what execution it requires. Providers declare what they can enforce. Project policy is a ceiling. The intersection is EffectivePolicy. Anything unsatisfiable fails before a sandbox is created and names the blame lay"
audience: all
---
# Execution capabilities

The environment declares what execution it requires. Providers declare what
they can enforce. Project policy is a ceiling. The intersection is
`EffectivePolicy`. Anything unsatisfiable fails before a sandbox is created
and names the blame layer: `provider`, `project`, `environment`, `harness`,
or `agent`.

## Environment runtime

`EnvironmentRuntime` owns image or build context, `NetworkMode`
(`none` / `restricted` / `full`), resources, `read_only_root`, persistence,
compose, and `targets` (`local` / `docker` / `remote`).

Defaults are secure: `network=none` and targets `{docker, remote}`. Local
requires `allow_unsafe_local=true` and is excluded when the environment
needs network isolation, persistence, compose, or resource limits.

`JobSpec` validation and `Job.preflight()` apply these requirements before
runtime creation.

## Five layers

`resolve_effective_policy()` intersects, in order, only narrowing:

1. Provider capability
2. Project policy (allowed targets, network ceiling, max resources,
   allowed harness capabilities, unsafe-local permission)
3. Environment runtime and harness policy
4. Harness requirements reduced by the stamp
5. Agent request (routing, secrets, requested target)

`EnvironmentRuntime.provider` selects the target for every Trial using that
Environment. An unenforceable local placement fails at preflight, not at
sandbox creation.

Package and backend share
`src/plural/schemas/execution_policy.cases.json` so they cannot drift.

See the [capability table](../reference/capabilities.md).
