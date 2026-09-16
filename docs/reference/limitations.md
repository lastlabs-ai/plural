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

## Execution and hosting

- Hosted synchronization requires a backend that supports the complete
  revision graph and append-only execution records.
- Package digests verify integrity only. Signatures, attestations, publisher
  identity, transparency logs, and keyless verification are unsupported.
- The local provider is not a sandbox. Docker trusts the host/daemon and has
  provider-specific network/resource limits. Daytona depends on its external
  service and SDK.
- Use the named `local`, `docker`, or `daytona` Runtime provider.
  Additional partners require a separately installed `SandboxProvider`.
- Receipts are self-reported, unsigned integrity records.
- Exact-value output redaction cannot prevent transformed secret exfiltration;
  artifacts and external logs are not generally redacted.
- Environment `Secret` targets and requiredness are metadata in package Job
  execution; values are not resolved or injected into those targets.
- Local review submission supports one criterion through the public CLI; full
  contracted evidence and multi-criterion submission are not exposed there.
- Cost limits cannot independently meter arbitrary external Harness behavior.
- The sandbox provider entry-point API is public Alpha.
- Authored Resource descriptors do not automatically fetch, mount, or grant
  access to their paths and URIs.
- Package command execution serializes and pins Task `reset_options` but does
  not yet forward them to `reset`.
- Command Verifiers receive all captured artifacts; isolate untrusted scorers.
- Job native runners call OpenAI-compatible `/chat/completions`. The Client
  adapters for Anthropic, Google, Bedrock, and Azure native APIs are separate
  and are not used by Job execution.

Unsupported controls fail preflight where detectable. Every Trial uses the
runtime owned by its Task's Environment. Verifier runtime/connectivity is
independent and can impose additional provider requirements.

## Training

Train mode requires exact TITO support and stores records as hashed artifacts.
Artifact durability does not by itself provide remote replication or
attestation. The package does not implement training algorithms, gradient
updates, checkpoint management, or deployment.

## Routing

Job results do not automatically train or configure a router. Choose model candidates and a Client routing policy in your application, and preserve the Harness behavior used in evaluation.
