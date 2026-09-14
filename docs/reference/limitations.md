---
route: /docs/reference/limitations
title: "Known limitations"
order: 250
description: "Current limitations for execution providers, harnesses, TITO capture, human review, and hosted workflows."
audience: all
nav: true
nav_group: Operations
---
# Known limitations

Known gaps:

- Hosted synchronization requires a backend that supports the complete
  revision graph and append-only execution records.
- Package digests verify integrity only. Signatures, attestations, publisher
  identity, transparency logs, and keyless verification are unsupported.
- The local provider is not a sandbox. Docker trusts the host/daemon and has
  provider-specific network/resource limits. Daytona depends on its external
  service and SDK.
- There is no built-in `current`, `remote`, or Blaxel Runtime provider.
  Additional partners require a separately installed `SandboxProvider`.
- Receipts are self-reported, unsigned integrity records.
- Exact-value output redaction cannot prevent transformed secret exfiltration;
  artifacts and external logs are not generally redacted.
- Environment `Secret` targets and requiredness are metadata in package Job
  execution; values are not resolved or injected into those targets.
- Local review submission supports one criterion through the public CLI; full
  contracted evidence and multi-criterion submission are not exposed there.
- Cost limits cannot independently meter arbitrary external Harness behavior.
- Vendor adapters depend on separately installed tools and changing formats.
- The sandbox provider entry-point API is public Alpha.
- Authored Resource descriptors do not automatically fetch, mount, or grant
  access to their paths and URIs.
- Package command execution serializes and pins Task `reset_options` but does
  not yet forward them to the reset adapter.
- Command Verifiers receive all captured artifacts; `EvidenceContract` is not
  an artifact ACL.
- Job native runners call OpenAI-compatible `/chat/completions`. The Client
  adapters for Anthropic, Google, Bedrock, and Azure native APIs are separate
  and are not used by Job execution.

Unsupported controls fail preflight where detectable. Every Trial uses the
runtime owned by its Task's Environment. Verifier runtime/connectivity is
independent and can impose additional provider requirements.

Train mode requires exact TITO support and stores records as hashed artifacts.
Artifact durability does not by itself provide remote replication or
attestation. The package does not implement training algorithms, gradient
updates, checkpoint management, or deployment.
