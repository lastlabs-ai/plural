---
route: /docs/guides/provider-plugins
title: Provider Plugins
order: 927
description: This page moved to Integrations. Open that guide for the current walkthrough and examples.
audience: all
nav: false
---
# Provider Plugins

A sandbox provider supplies the machine lifecycle for Agent and Verifier execution. It is different from a model provider, which sends requests to an LLM service.

## Implement the lifecycle

Subclass `plural.sandbox.base.SandboxProvider` and implement its asynchronous methods:

- `capabilities()` declares availability and enforceable controls for this installation.
- `doctor()` reports dependency, service, and credential health.
- `create(requirements)` provisions a clean runtime after preflight.
- `upload_files(handle, files, root=...)` stages validated files within the workspace.
- `exec(handle, request)` executes argv with cwd, environment, stdin, timeout, and captured stdout/stderr.
- `download_files(handle, paths, root=...)` returns the exact requested files.
- `cancel(handle)` stops active execution.
- `destroy(handle)` idempotently removes the runtime and scoped data.

The base implementation supplies `preflight`, `upload_bundle`, and `download_artifacts`. Override them only when your backend needs different behavior while preserving the contract. In particular, unsupported network or resource controls must fail before launch rather than being ignored.

Inspect the built-in providers in the current source checkout for working implementations.

## Register your implementation

For an in-process application:

```python
from plural.sandbox.registry import ProviderRegistry
from my_runtime import MyProvider

registry = ProviderRegistry()
registry.register(MyProvider())
provider = registry.get("my-provider")
```

This assumes your `MyProvider` implementation exposes `name = "my-provider"`. To make an installed plugin discoverable by the CLI, declare an entry point in its `pyproject.toml`:

```toml
[project.entry-points."plural.sandbox_providers"]
my-provider = "my_runtime:MyProvider"
```

The registry loads the factory and requires a `SandboxProvider` instance. Provider names must be unique unless you explicitly replace a registration in-process.

## Verify the capability contract

Test the runtime lifecycle with a small trusted command. Then request a feature your provider cannot enforce and confirm it rejects the request. Check cancellation, timeouts, cleanup after failures, upload path restrictions, and exact artifact downloads.

The Environment target classification and project policy must support the provider's intended placement; registration alone does not make a new name a fully integrated remote execution target. The entry-point API is currently Alpha. Use [Runtime](../project/environments.md#runtime) to understand how requirements are combined.
