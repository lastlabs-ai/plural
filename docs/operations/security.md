---
route: /docs/operations/security
title: Security
order: 934
description: Choose isolation, credential handling, and evidence access for your evaluation workflow.
audience: all
nav: false
nav_group: Operations
---
# Security

Choose isolation and data access to match the code and information in your evaluation. Plural checks declared Runtime controls and records what ran; you remain responsible for which code, providers, and people you trust.

## Choose the process boundary

- `local` is an explicitly unsafe subprocess for trusted development.
- Docker adds container controls but trusts the host and Docker daemon.
- Daytona delegates isolation to an external service and adapter.
- A plugin is trusted to report and enforce capabilities truthfully.

Preflight fails when declared controls are unavailable. It cannot detect every
provider bug or malicious implementation.

## Separate information

State is internal; Observation is Agent-visible. Colocated code can still
read a file or process memory. Use separate processes, minimal staged files,
and Runtime controls for actual isolation.

Verifiers receive the full final Episode, including State. Isolate untrusted
Verifier code and avoid capturing secrets.

## Handle secrets

Environment secret targets are metadata in package Job execution;
requiredness and target injection are not enforced. Do not rely on them to
supply Environment, Harness, or Verifier credentials.

Executable Harness credentials are fail-closed: a Harness declares allowed
names, an Agent grants a subset with `secret_names`, and values come from the
execution environment. Undeclared grants fail before forwarding. Agent
Verifiers receive supported model API variables directly from the Job process;
deterministic Verifiers receive no Environment secret injection.

Never store values in YAML, Task info, State, Observation, resources, model
messages, logs, or artifacts. Managed Harness and Verifier logs redact exact
credential values known to those processes. Event writers require an explicit
secret list. No mechanism here prevents encoded, transformed, artifact, or
externally transmitted leakage.

## Lock code and output

Environment and Harness source digests detect changes. Remote archives and OCI
sources require digests. These are integrity checks, not signatures,
attestations, publisher identity, or malware scanning.

Artifact SHA-256 values and receipts detect post-run edits. Receipts are
currently unsigned and self-reported. Imported runs are marked
`imported_unverified`.

## Minimize capability

Use a pinned image, modest compute and time limits, focused actions, and a read-only root where supported. Allow access to the model endpoint and other services the Task needs. For a fully offline workflow, block networking with a supporting Runtime. Grant optional Harness capabilities only when the workflow requires them.

Hosted project policy is an additional ceiling; it cannot make a permissive
Environment more restrictive inside a provider that lacks enforcement.

Read [Runtime](../project/environments.md#runtime), [Artifacts and evidence](../running/artifacts.md),
and [Known limitations](../reference/limitations.md) before processing
sensitive data.
