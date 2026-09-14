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

`Environment.runtime` is required. It says where the Agent Harness and
Environment execute. The provider is part of the Environment hash, so changing
it changes every Task pin that uses that Environment. Each deterministic or
Agent Verifier has a separate `VerifierRuntime`.

```python
from plural import Runtime

Runtime.docker()                          # python:3.12-slim, public network
Runtime.docker(image="my-org/eval:1")
Runtime.docker(dockerfile="Dockerfile", build_context=".")
Runtime.local()                           # trusted subprocess
Runtime.daytona(image="python:3.12-slim") # requires plural[daytona]
```

Harbor defaults on `Runtime` are `provider="docker"`, `network="public"`,
`image="python:3.12-slim"`, and `build_timeout_sec=600`. Optional `cpus`,
`memory_mb`, and `storage_mb` map onto `resources`. `allowed_hosts` is the
allowlist field (`network_allowlist` remains an alias).

## Provider and target

Plural registers `local`, `docker`, and `daytona`. `local`, `docker`, and
`remote` are target classes; a provider implements one. `daytona` maps to
`remote`. Unknown provider names can come from installed plugins, but
registration alone does not prove capability or hosted availability.

Plural does not fall back between Runtime providers. Planning and preflight
must reject any requested control the selected provider cannot enforce.

## Trusted local execution

```python
environment = Environment(name="dev", runtime=Runtime.local())
```

`local` runs a subprocess in a temporary workspace on the current machine. It
is not in-process execution and not a sandbox. It supports scoped upload and
download, argv execution, environment values, logs, timeout, and cancellation.
It cannot enforce image, OS, compute, network, read-only-root, persistence, or
compose requirements.

`Runtime.local()` sets `allow_unsafe_local=True` and `targets` that include
`local`. Use it only for trusted development code.

## Docker: image, OS, build, and filesystem

```python
Runtime.docker(
    image="python:3.12-slim",
    network="no-network",
    cpus=2,
    memory_mb=2048,
)
```

The image defines OS userspace and installed dependencies; there is no `os`
field. Pin an immutable image digest for reproducibility. Alternatively,
`dockerfile` plus `build_context` builds locally. A remote provider cannot
consume that local context. `image`, `snapshot`, and `declarative_image` are
mutually exclusive.

Docker uses a fresh container, drops Linux capabilities, sets
`no-new-privileges`, uses an unprivileged user, and creates a scoped workspace.
`read_only_root` makes the container root read-only while the workspace remains
writable.

## Network

Harbor names are canonical:

- `public`: permit outbound network.
- `no-network`: block outbound network.
- `allowlist`: permit only `allowed_hosts`.

Legacy aliases `full`, `none`, and `restricted` still parse.

The native model loop runs inside this Runtime, so model API calls need
network. Agent judges also need network unless the author sets
`network="no-network"`. `plural run` being local does not make those calls
offline.

```python
Runtime.daytona(
    image="python:3.12-slim",
    network="allowlist",
    allowed_hosts=("api.openai.com",),
)
```

## Daytona and remote providers

```bash
python -m pip install "plural[daytona]==0.13.0"
export DAYTONA_API_KEY=...
```

The adapter supports image, snapshot, or `DeclarativeImage`; CPU and memory;
network blocking/allowlisting; upload/download; timeout/cancel; environment;
working directory; and logs. It rejects local build contexts, PID/disk limits,
stdin execution, persistence, compose, and read-only root.

Daytona is the bundled remote sandbox. A partner can also ship an independent
`SandboxProvider` plugin through the `plural.sandbox_providers` entry-point
group.

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
Only declared outputs and artifacts are downloaded before teardown.

Declare secret references, never values. Package Job execution treats
Environment secret references as metadata. Harness `secrets` declares allowed
names and Agent `secret_names` grants extra application secrets, not model
authentication. Job `client=` or `api_key=` injects model credentials.

`persistent=True` requests provider-backed persistence; none of the three
built-ins advertises persistence, so the request fails preflight.

## Compute, placement, and limits

`resources` contains optional `cpu`, `memory_mb`, `pids`, `disk_mb`, and
`storage_mb`. `placement` carries provider-specific string hints.
`runtime.timeout_seconds` limits Runtime operations; `build_timeout_sec`
limits image builds. Environment `limits` separately cap turns, elapsed
episode time, and optional cost.

See [Security](../operations/security.md) and
[provider extensions](../reference/integrations.md#sandbox-provider-extensions).
