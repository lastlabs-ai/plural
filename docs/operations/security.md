---
route: /docs/operations/security
title: Security
order: 934
description: What Plural keeps private, where your keys live, what the AI never sees, and how to choose isolation and data access for your evaluations.
audience: all
nav: false
nav_group: Operations
---
# Security

Plural keeps your work private by default, keeps your keys out of your project, and
never shows the AI anything beyond the Task's instructions and what the Environment
lets it see. This page explains those guarantees in plain words first, then the
settings you choose for isolation and data access.

Plural checks the safety controls you ask for and keeps a record of what ran. You
still decide which code, model providers, and people you trust.

## The short version

- **Your work stays private.** Pushing to Plural saves a private copy inside your
  hosted project. Nothing becomes public unless you publish it yourself in the web
  app.
- **Your keys never live in your project.** `plural auth login` keeps your
  credential in your computer's keyring (the operating system's password store) or a
  private file in your user settings folder. A push refuses files that look like
  credentials, such as `.env` files and private keys.
- **The AI sees only what it is meant to see.** An Agent (the contestant: a model
  plus its instructions) sees the Task's instructions and the Environment's
  Observations, and nothing else. It never sees its score, its rewards, the hidden
  State of the world, or what the grader knows.
- **Other secrets arrive when a run starts.** An API key a tool needs is declared by
  name only, and its value is supplied when the run begins. Plural hides those exact
  values in the logs it captures.

The rest of this page is for when you are running code or data you need to protect.

## Choose the process boundary

A **Runtime** is where the world runs. Each option draws the safety line in a
different place:

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

After each action the Agent sees only the Observation. Scores, rewards,
termination flags, State, and Verifier data never enter the model's context.

That separation governs what Plural shows the model; it is not process
isolation. Code running in the same Runtime can still read a staged file or
process memory. Use separate processes, minimal staged files, and Runtime
controls for actual isolation.

Verifiers (the graders) receive the full final Episode, including State. Isolate
untrusted Verifier code and avoid capturing secrets.

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
artifacts.

> **Good to know:** Plural replaces the exact values of injected secrets in the
> Harness and Verifier logs it captures. It cannot catch an encoded or transformed
> secret, and it does not redact artifacts or data your code sends elsewhere.

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

Plural fingerprints your code and results so you can tell if something changed.
Those fingerprints prove *what* ran, not *who* made it or whether it is safe.

Environment and Harness source digests detect changes. Remote archives and OCI
sources require digests. These are integrity checks, not signatures,
attestations, publisher identity, or malware scanning.

Artifact SHA-256 values and receipts detect edits after a run. Receipts are
unsigned; a local run reports `self_reported` trust, and imported runs report
`imported_unverified`.

## Minimize capability

Give each run only what it needs:

- Use a pinned image, modest compute and time limits, focused actions, and a
  read-only root where supported.
- Allow access to the model endpoint and other services the Task needs. For a fully
  offline workflow, block networking with a Runtime that supports it.
- Grant optional Harness capabilities only when the workflow requires them; see
  [Harness and Environment policy](../concepts/harness-policy.md).

A hosted project's policy is an additional ceiling. It cannot enforce a control
that the selected Runtime provider does not support.

Read [Runtime](../project/environments.md#runtime), [Artifacts and evidence](../running/artifacts.md),
and [Known limitations](../reference/limitations.md) before processing
sensitive data.
