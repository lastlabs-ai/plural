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

```bash
plural env capabilities ./env
plural runtime doctor --env ./env
```

Those commands must agree with `Job.preflight()` and
`POST /api/v1/jobs/preflight`.

## Five layers

`resolve_effective_policy()` intersects, in order, only narrowing:

1. Provider capability (`runtime doctor`)
2. Project policy (allowed targets, network ceiling, max resources,
   allowed harness capabilities, unsafe-local permission)
3. Environment runtime and harness policy
4. Harness requirements reduced by the stamp
5. Agent request (routing, secrets, requested target)

`RuntimeSpec.provider` is a requested target. `--runtime local` on an
isolated environment fails at preflight, not at sandbox creation.

Package and backend share
`src/plural/schemas/execution_policy.cases.json` so they cannot drift.

See the [capability table](../reference/capabilities.md).
