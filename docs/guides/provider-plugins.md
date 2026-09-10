---
route: /docs/guides/provider-plugins
title: "Sandbox provider plugins"
order: 290
description: "Implement and package a sandbox provider plugin that enforces canonical runtime requirements and capability preflight."
audience: all
---
# Sandbox provider plugins

Package a plugin with an entry point in `pyproject.toml`:

```toml
[project.entry-points."plural.sandbox_providers"]
my-runtime = "my_package:provider"
```

The loaded object (or zero-argument factory result) must be a
`plural.SandboxProvider` with a unique `name`. The registry loads entry points
lazily on first lookup/listing.

Implement these async operations:

- `capabilities()` and `doctor()` without exposing credentials;
- `create(requirements)` after preflight;
- scoped `upload_files`, argv-based `exec`, and exact `download_files`;
- forceful `cancel` and idempotent `destroy`.

The base `preflight()` compares `SandboxRequirements.required_capabilities()`
with claims returned by `capabilities()`. Override it to reject finer-grained
forms your provider cannot enforce, then call `super()`. Never claim a control
based only on accepting a field: network, resources, timeout, read-only root,
and cleanup must actually be enforced.

Provider handles are opaque identities. Keep provider credentials out of handle
metadata and doctor output. Validate every remote path, do not follow symlinks
when bundling/downloading, capture effective policy for receipts, and delete
partial resources if creation fails.

Test with an injected fake service offline, including unavailable credentials,
each rejected capability, timeout/cancel races, traversal attempts, exact
downloads, and idempotent cleanup. Put real-service tests behind a dedicated
marker and credentials, as the Daytona provider does.

`plural runtime list`, `show`, and `doctor` discover plugins. There is no
stability guarantee for this alpha plugin API beyond the current abstract base
class; pin the Plural version and run typing/tests on upgrades.
