---
route: /docs/reference/limitations
title: "Known limitations"
order: 430
description: "Current alpha limitations for execution providers, harnesses, TITO capture, human review, and hosted workflows."
audience: all
---
# Known limitations

This release remains Alpha:

- Hosted synchronization requires a backend that supports the complete
  schema-v2 revision graph and append-only execution records.
- Package digests verify integrity only. Signatures, attestations, publisher
  identity, transparency logs, and keyless verification are unsupported.
- The local provider is not a sandbox. Docker trusts the host/daemon and has
  provider-specific network/resource limits. Daytona depends on its external
  service and SDK.
- Receipts are self-reported, unsigned integrity records.
- Exact-value output redaction cannot prevent transformed secret exfiltration;
  artifacts and external logs are not generally redacted.
- Cost limits cannot independently meter arbitrary external Harness behavior.
- Vendor adapters depend on separately installed tools and changing formats.
- The sandbox provider entry-point API is public Alpha.

Unsupported controls fail preflight where detectable. Every Trial uses the
runtime owned by its Task's Environment. Verifier runtime/connectivity is
independent and can impose additional provider requirements.

Train mode requires exact TITO support and stores records as hashed artifacts.
Artifact durability does not by itself provide remote replication or
attestation.
