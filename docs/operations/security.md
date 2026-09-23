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

- `local` runs the Environment, Harness, and Verifiers as a trusted subprocess
  on your machine, under your user account. It is not a sandbox; use it only for
  code you trust.
- Docker adds container controls but trusts the host and Docker daemon.
- Daytona delegates isolation to an external service and its SDK.
- A third-party `SandboxProvider` is trusted to report and enforce its
  capabilities truthfully.

Plural refuses to start a run when the selected provider cannot enforce a
declared control. It cannot detect every provider bug or malicious
implementation.

## Separate information

After each action the agent sees only the Observation. Scores, rewards,
termination flags, State, and Verifier data never enter the model's context.
That separation governs what Plural shows the model; it is not process
isolation. Code running in the same Runtime can still read a staged file or
process memory. Use separate processes, minimal staged files, and Runtime
controls for actual isolation.

Verifiers receive the full final Episode, including State. Isolate untrusted
Verifier code and avoid capturing secrets.

## Handle secrets

Credentials are never stored in a project. `plural auth login` keeps its
credential in your OS keyring or a private file in your user config directory,
and a push refuses files that look like credentials, such as `.env` files and
private keys.

Supply other secrets when the Job runs:

- **Environment secrets.** An Environment declares `secrets` by name and target
  (`environment`, `harness`, or `verifier`) and `RuntimeVariable` declarations
  on its Runtime; the declarations never hold values. At run time Plural reads
  the values from the Job's environment and injects them: `environment` and
  `harness` targets into the Runtime the Environment and Harness share, and
  `verifier` targets into the Verifier's process. A missing required value
  stops the run before it starts.
- **Harness secrets.** A custom Harness lists the names it reads in `secrets`,
  and an Agent grants a subset with `secret_names`. Granting a name the Harness
  did not declare fails before any value is forwarded.
- **Model keys.** A Job passes model credentials to the Harness and to Agent
  Verifiers itself; you do not list them in `secret_names`.

Never store values in YAML, Task info, State, Observation, resources, logs, or
artifacts. Plural replaces the exact values of injected secrets in the Harness
and Verifier logs it captures. It cannot catch an encoded or transformed
secret, and it does not redact artifacts or data your code sends elsewhere.

## Hosted access

- `plural auth scope` selects where hosted commands go. It never changes what
  your credential may do.
- A browser login acts as you and reaches every account and project your roles
  allow. An API key limited to one project reaches only that project; use one
  for CI.
- Pushing saves a private revision in your project and never makes anything
  public. Listing a resource on the Hub and
  [publishing a Benchmark release](../architecture/benchmark-publications.md)
  are separate, explicit actions in the web app.
- Organization admins can restrict which models members may use. The service
  enforces that list for runs, reruns, and model calls through the gateway.

## Lock code and output

Environment and Harness source digests detect changes. Remote archives and OCI
sources require digests. These are integrity checks, not signatures,
attestations, publisher identity, or malware scanning.

Artifact SHA-256 values and receipts detect edits after a run. Receipts are
unsigned; a local run reports `self_reported` trust, and imported runs report
`imported_unverified`.

## Minimize capability

Use a pinned image, modest compute and time limits, focused actions, and a read-only root where supported. Allow access to the model endpoint and other services the Task needs. For a fully offline workflow, block networking with a Runtime that supports it. Grant optional Harness capabilities only when the workflow requires them; see [Harness and Environment policy](../concepts/harness-policy.md).

A hosted project's policy is an additional ceiling. It cannot enforce a control
that the selected Runtime provider does not support.

Read [Runtime](../project/environments.md#runtime), [Artifacts and evidence](../running/artifacts.md),
and [Known limitations](../reference/limitations.md) before processing
sensitive data.
