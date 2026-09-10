---
route: /docs/reference/capabilities
title: "Capability table"
order: 480
description: "Generated from plural.sandbox.models.Capability and plural.domain.HarnessCapability. Local, Docker, and remote (Daytona) are the only providers."
audience: all
---
# Capability table

Generated from `plural.sandbox.models.Capability` and
`plural.domain.HarnessCapability`. Local, Docker, and remote (Daytona) are
the only providers.

## Sandbox controls

| Capability | local | docker | remote | Typical source |
| --- | --- | --- | --- | --- |
| `image` | no | yes | yes | environment image / snapshot / declarative image |
| `build` | no | yes | no | local `build_context` / `dockerfile` |
| `resources` | no | yes | yes | `EnvironmentRuntime.resources` |
| `network_none` | no | yes | yes | `network=none` (default) |
| `network_allowlist` | no | yes | yes | `network=restricted` |
| `upload` | yes | yes | yes | always required |
| `download` | yes | yes | yes | always required |
| `timeout` | yes | yes | yes | always required |
| `cancel` | yes | yes | yes | always required |
| `persistence` | no | yes | yes | `runtime.persistent` |
| `compose` | no | yes | yes | `runtime.compose` |
| `read_only_root` | no | yes | yes | `runtime.read_only_root` |
| `working_directory` | yes | yes | yes | always required |
| `environment` | yes | yes | yes | always required |
| `log_capture` | yes | yes | yes | always required |

Local is excluded when the environment requires `network_none`,
`network_allowlist`, persistence, compose, or resource limits. Remote
cannot consume a local build context.

A `CapabilityError` names the unsatisfied capability and the blame layer,
for example:

```
network_none required by environment 'support-triage' is not enforceable by provider 'local'
```

## Harness capabilities

| Capability | Removed when |
| --- | --- |
| `shell` | environment deny list / project allowlist |
| `file_read` | environment deny list / project allowlist |
| `file_edit` | `read_only_root`, or deny/allow lists |
| `code_execution` | environment deny list / project allowlist |
| `web_search` | `network=none` or `restricted` |
| `browser` | `network=none` or `restricted` |
| `network_fetch` | `network=none` |
| `mcp` | `network=none` |
| `subagents` | environment deny list / project allowlist |
| `persistence` | environment deny list / project allowlist |
