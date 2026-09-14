---
route: /docs/project/runtime
title: Runtime
order: 35
description: Choose where an Agent runs and declare image, compute, filesystem, network, persistence, placement, and current secret metadata.
audience: all
nav: true
nav_group: Build
outcome: You can select a runtime that can enforce your Environment requirements.
---
# Runtime

`Environment.runtime` says where the Agent Harness and Environment execute.
It is part of the Environment hash, so changing it changes every Task pin that
uses that Environment. Each deterministic or Agent Verifier has a separate
`VerifierRuntime`.

```python
from plural import ExecutionTarget, Runtime
from plural.sandbox import NetworkMode

runtime = Runtime(
    provider="docker",
    image="python:3.12-slim",
    network=NetworkMode.NONE,
    targets=frozenset({ExecutionTarget.DOCKER}),
    timeout_seconds=180,
)
```

## Provider and target

Plural 0.12.1 registers `local`, `docker`, and `daytona`. There is no built-in
provider named `current`, `remote`, or `blaxel`. `local`, `docker`, and
`remote` are target classes; a provider implements one. `daytona` maps to
`remote`. Unknown provider names can come from installed plugins, but
registration alone does not prove capability or hosted availability.

Plural does not fall back between Runtime providers. Planning and preflight
must reject any requested control the selected provider cannot enforce.

## Trusted local execution

```yaml
runtime:
  provider: local
  network: full
  allow_unsafe_local: true
  targets: [local]
  timeout_seconds: 180.0
```

`local` runs a subprocess in a temporary workspace on the current machine. It
is not in-process execution and not a sandbox. It supports scoped upload and
download, argv execution, environment values, logs, timeout, and cancellation.
It cannot enforce image, OS, compute, network, read-only-root, persistence, or
compose requirements. `network` must be `full`, `targets` must include `local`,
and `allow_unsafe_local=True` is mandatory.

Use it only for trusted development code.

## Docker: image, OS, build, and filesystem

```yaml
runtime:
  provider: docker
  image: python:3.12-slim
  network: none
  targets: [docker]
  timeout_seconds: 180
  resources:
    cpu: 2
    memory_mb: 2048
    pids: 256
  read_only_root: true
```

The image defines OS userspace and installed dependencies; there is no `os`
field. Pin an immutable image digest for reproducibility. Alternatively,
`build_context` plus optional `dockerfile` builds locally. A remote provider
cannot consume that local context. `image`, `snapshot`, and
`declarative_image` are mutually exclusive.

Docker uses a fresh container, drops Linux capabilities, sets
`no-new-privileges`, uses an unprivileged user, and creates a scoped workspace.
`read_only_root` makes the container root read-only while the workspace remains
writable. The built-in adapter supports CPU, memory, and PID controls but
rejects `disk_mb`, persistence, compose, and restricted network allowlists.
The Docker daemon remains a trusted host boundary.

## Network

- `none`: block outbound network.
- `full`: permit outbound network.
- `restricted`: permit only `network_allowlist`; valid only on providers that
  advertise and enforce allowlisting.

The native model loop runs inside this Runtime, so model API calls need network
access. `plural run` being local does not make those calls offline.

Docker supports `none` and `full`. Daytona supports all three; restricted
Daytona networking requires a nonempty all-domain or all-CIDR allowlist.

```yaml
runtime:
  provider: daytona
  targets: [remote]
  network: restricted
  network_allowlist: [api.openai.com]
  timeout_seconds: 180.0
```

## Daytona and remote providers

Daytona support is implemented but optional:

```bash
python -m pip install "plural[daytona]==0.12.1"
export DAYTONA_API_KEY=...
```

The adapter supports image, snapshot, or `DeclarativeImage`; CPU and memory;
network blocking/allowlisting; upload/download; timeout/cancel; environment;
working directory; and logs. It rejects local build contexts, PID/disk limits,
stdin execution, persistence, compose, and read-only root.

Daytona is the only named remote sandbox integration bundled in 0.12.1.
Daytona, Blaxel, or another partner can also ship an independent
`SandboxProvider` plugin through the `plural.sandbox_providers` entry-point
group. Blaxel is an extension path, not a completed integration in this
release.

Every partner implementation must provide clean create/upload/exec/download/
cancel/destroy lifecycle behavior, truthful `capabilities()` and `doctor()`
reports, scoped paths, captured logs, idempotent cleanup, and fail-closed
preflight. Unsupported policy must never degrade silently.

Inspect provider health programmatically:

```python
import asyncio
from plural import ProviderRegistry

reports = asyncio.run(ProviderRegistry().doctors(include_unavailable=True))
for report in reports:
    print(report.name, report.healthy, report.reason)
```

## Files, resources, secrets, and persistence

Environment and Harness source bundles are uploaded into scoped workspaces.
Only declared outputs and artifacts are downloaded before teardown. An authored
`Resource` is a hashed object descriptor; it is not automatically a secret or
an arbitrary host mount.

Declare secret references, never values:

```yaml
secrets:
  - name: SUPPORT_API_TOKEN
    required: true
    target: environment
```

Targets are `environment`, `harness`, and `verifier`, but package Job execution
in 0.12.1 treats Environment secret references as metadata: it does not resolve
required or optional values, inject them into any target, or use them as a
redaction list. A reference also does not provision a vault.

Harness credentials use a separate executable path. Harness `secrets` declares
allowed names and Agent `secret_names` grants a subset; undeclared grants fail
before forwarding. Values come from the execution process. Agent Verifiers
receive only their supported model endpoint variables. Deterministic
Verifiers receive no Environment secret injection. Keep values out of YAML,
metadata, resources, observations, logs, and artifacts.

`persistent=True` requests provider-backed persistence; it does not mean “keep
the local temp directory.” None of the three built-ins advertises persistence
in 0.12.1, so the request fails preflight.

## Compute, placement, and limits

`resources` contains optional `cpu`, `memory_mb`, `pids`, and `disk_mb`.
`placement` carries provider-specific string hints. `extra_capabilities`
requires additional provider controls. `runtime.timeout_seconds` limits Runtime
operations; Environment `limits` separately cap turns, elapsed episode time,
and optional cost.

Custom Harnesses must cooperate with turn and cost limits. Plural cannot
independently meter arbitrary external behavior.

## Effective security boundary

Execution proceeds only when the Environment Runtime, optional Harness grant,
project policy, target class, and provider capabilities agree. Provider
preflight is a guarantee to reject unsupported controls, not proof against a
malicious provider or compromised host.

See [Security](../operations/security.md) and
[provider extensions](../reference/integrations.md#sandbox-provider-extensions).
