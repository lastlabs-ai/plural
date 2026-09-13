---
route: /docs/project/runtime
title: Runtime and connectivity
order: 35
description: Choose local, Docker, or remote execution and declare enforceable network and resource policies.
audience: all
nav: false
outcome: You can select a runtime that can enforce your Environment requirements.
---
# Runtime and connectivity

The runtime is the machine where the agent and Environment execute. It determines the operating system, installed dependencies, network access, and resource limits. This configuration lives on the **Environment**. Each deterministic or agent Verifier separately declares the machine and connectivity needed to score the run.

Choose the runtime for the behavior you need. A local process is convenient for trusted development. A container gives you a reproducible userspace and enforceable isolation features. A remote sandbox moves execution to a provisioned machine.

## Inspect available providers

```bash
plural providers list
plural providers doctor
```

The built-in registry includes `local`, `docker`, and `daytona`. `remote` is an execution target category, not a built-in provider name you can use in place of `daytona`. Installed provider plugins can register additional names.

A target describes the type of execution; a provider implements it. Listing a target in `targets` does not automatically switch to it when another provider fails. Plural checks requested features against provider capabilities and rejects combinations it cannot enforce.

## Trusted local execution

This Environment runtime matches the starter:

```yaml
runtime:
  provider: local
  network: full
  allow_unsafe_local: true
  targets: [local]
  timeout_seconds: 180
```

The local provider runs processes on your machine. It does not enforce network isolation, filesystem isolation, container images, persistence, or resource limits. `network: none` and `network: restricted` are incompatible with local execution. Setting local opt-in acknowledges this development mode; it does not add isolation.

Local execution is useful for stepping through actions and testing a trusted harness. Keep real credentials and unrelated files outside the example's needs.

## Docker and the operating system

A minimal container runtime fragment is:

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
    disk_mb: 4096
```

The image defines the operating system userspace and installed tools. There is no separate `os` field. Install dependencies in an image or build context before execution; a sandbox with `network: none` cannot download packages during the run. For a reproducible comparison, pin an image digest rather than relying on a moving tag.

Start with only the resource requirements your provider reports it can enforce. In particular, provider support for disk limits and other capabilities may differ; do not assume this fragment is portable to every Docker host.

For an Environment-specific image, `build_context` and `dockerfile` describe a local build. Remote providers cannot consume a local build context. Build and publish an image or use a supported snapshot/declarative image workflow when moving to a remote provider. `image`, `snapshot`, and `declarative_image` are mutually exclusive.

Changing the Environment runtime does not change its Verifiers. Update each Verifier runtime too if the complete experiment should run in containers.

## Network access

There are three declared modes:

- **`none`:** execution has no outbound network where the selected provider enforces it. Useful for offline puzzles, file transformations, and deterministic tests.
- **`full`:** outbound network is permitted. Use it when the agent must call a model API or external tools, with the corresponding access policy.
- **`restricted`:** only the configured destinations are allowed, on a provider that supports allowlisting. `network_allowlist` is valid only with this mode.

The built-in Docker provider supports blocked or full networking; it does not advertise restricted networking. Daytona supports restricted networking through its adapter. A restricted request with no supported enforcement should fail, never silently become full access.

For example, an Environment using Daytona can declare:

```yaml
runtime:
  provider: daytona
  targets: [remote]
  network: restricted
  network_allowlist: [api.openai.com]
  timeout_seconds: 180
```

This is a connectivity fragment, not a complete cloud setup. Add the image or snapshot and dependencies required by your harness. The Daytona adapter accepts domain allowlists or CIDR lists; do not mix them in one list. Check the installed provider before running.

A model API call made inside the runtime needs connectivity too. `--offline` does not block those calls; it selects local Job orchestration and storage. A locally orchestrated Job can still use Docker, Daytona, or a paid model API.

## Daytona and other remote sandboxes

Install the optional provider support from the current checkout:

```bash
python -m pip install -e '.[daytona]'
plural providers doctor
```

Run the installation in the package root. Supply Daytona credentials through your process environment, then use `provider: daytona`. See [Cloud providers](../guides/cloud-providers.md) for adapter setup. A local source directory is not automatically available on another machine; hosted execution needs a materializable package source and access to the selected runtime.

For another cloud, implement the [sandbox provider interface](../guides/provider-plugins.md). Advertise only capabilities that the provider actually enforces.

## Secrets and process configuration

The Environment declares secret names and their intended target:

```yaml
secrets:
  - name: SUPPORT_API_TOKEN
    required: true
    target: environment
```

The targets are `environment`, `harness`, and `verifier`. A declaration describes the requirement; the execution integration must supply the value to the correct process. Do not place secret values in YAML, Task metadata, resources, or recorded observations.

For a Harness, the package declares permitted `secret_names`, and the Agent grants the names it needs. The local runner reads granted values from its process environment. Non-secret configuration, such as a model gateway URL, uses the Harness's `environment_names`. See [Harnesses](harnesses.md) for the full contract.

Do not assume that merely naming an Environment secret provisions a vault, downloads a connector, or makes an arbitrary credential available in every runtime. Verify your provider's injection path with a non-sensitive test value before using it in a real project.

## Limits, placement, and policy

`runtime.timeout_seconds` limits runtime operations. Environment `limits` describe the episode budget: `max_turns`, `max_seconds`, and optional `max_cost_usd`. Custom harnesses must cooperate with the episode contract and enforce their loop's limits; declarations alone do not implement arbitrary stopping behavior.

`placement` carries provider placement hints. `persistent`, `compose`, `read_only_root`, and `extra_capabilities` request additional runtime behavior. Check provider support instead of assuming these settings work everywhere.

For hosted execution, the project's execution policy sets an additional ceiling. The effective run must satisfy the Environment, Agent/Harness compatibility, project policy, and provider capabilities. A local opt-in does not override a hosted policy that forbids local execution.

## Diagnose a runtime mismatch

If validation or preflight fails, read the named capability, then inspect `plural providers doctor`. Common causes are local execution with blocked networking, an unavailable Docker daemon, missing Daytona configuration, a local build context on a remote target, or a model endpoint omitted from an allowlist.

Resolve the configuration mismatch before increasing retries. [Troubleshooting](../operations/troubleshooting.md) follows failures from planning through scoring.
