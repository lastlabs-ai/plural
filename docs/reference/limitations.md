---
route: /docs/reference/limitations
title: "Known limitations"
order: 250
description: "Current limitations for execution providers, harnesses, TITO capture, human review, and hosted workflows."
audience: all
nav: false
nav_group: Operations
---
# Known limitations

Use this page to check whether a planned workflow is supported. The guides explain the working path; these limits describe where additional setup or integration is needed.

## Projects and hosting

- Hosted commands (`push`, `pull`, `run --hosted`, and hosted `show`, `list`,
  `job`, `trial`, and `review` commands) need `plural auth login` and a project
  registered with `plural project init <name> --push`. Local commands need
  neither.
- `plural run --hosted` runs only revisions that are already pushed with
  identical content. Push first.
- Revisions saved in the web app, or pushed before 0.15, have no source package
  and cannot be pulled. See [Migrate to 0.15](../migration/projects.md).
- `.pluralignore` matches exact file paths only; it does not support patterns or
  directory entries.
- Package digests verify integrity only. Signatures, attestations, publisher
  identity, transparency logs, and keyless verification are unsupported.
- `plural agent serve` and `plural trial rescore` are reserved and not available
  yet.

## Execution

- The `local` Runtime is a trusted subprocess, not a sandbox. Docker trusts the
  host and its daemon and has provider-specific network and resource limits.
  Daytona depends on its external service and SDK.
- Use the named `local`, `docker`, or `daytona` Runtime provider. Other providers
  require a separately installed `SandboxProvider`, and the provider extension
  API is in alpha.
- Receipts are unsigned integrity records, and local runs report
  `self_reported` trust.
- Redaction matches exact secret values in captured logs. It cannot catch a
  secret that code has encoded or transformed, and it does not apply to custom
  artifacts or external logs.
- `plural review list` does not expose the full contracted evidence view; open
  the evidence with `plural trial show`.
- Cost limits cannot meter model calls a custom Harness makes outside Plural's
  gateway.
- A `Resource` descriptor does not fetch, mount, or grant access to its path or
  URI. Use `source`, `inline`, or `resolver` delivery to stage files.
- Plural stores a Task's `reset_options` but does not yet pass them to `reset`.
- A Verifier that runs a command receives every captured artifact; isolate
  untrusted scorers with their own `VerifierRuntime`.
- A Job makes model calls only through OpenAI-compatible `/chat/completions`
  endpoints. The `Client` adapters for Anthropic, Google, Bedrock, and Azure
  native APIs are separate and are not used by Jobs.
- A custom Harness class reports a stop reason only when it returns one in
  `HarnessResult.metadata`.

Plural rejects a run before it starts when the selected provider cannot enforce a
requested control and it can detect that. Every Trial uses the Runtime of its
Task's Environment. A Verifier's Runtime and network access are configured
separately and can add their own provider requirements.

## Training

Train mode requires a Harness that captures exact tokens in and tokens out
(TITO), and stores the records as hashed artifacts. Storing an artifact does not
replicate or attest it. Plural does not implement training algorithms, gradient
updates, checkpoint management, or deployment, and `plural run` has no train
mode; use a Python `Job`.

## Routing

Job results do not automatically train or configure a router. Choose model candidates and a Client routing policy in your application, and preserve the Harness behavior used in evaluation.
