# Known limitations

This release remains Alpha. Current boundaries are:

- v1 Environment and client-orchestrated Job sync requires a compatible hosted
  API. Hosted records do not execute workloads or attest local receipts.
- Device authentication depends on backend endpoints not provided by this
  package. There is no general background refresh loop. Hosted publication/sync can
  refresh stored device credentials; auth status/whoami do not provide that flow.
- `plural run` does not write externally by default. `--sync` opts into
  best-effort registration/upload; `plural job upload` replays stored results.
- Package digests verify integrity only. Signatures, attestations, publisher
  identity, transparency logs, and keyless verification are unsupported.
- OCI Harnesses require Docker, cannot compose with an Environment image/build,
  and cannot be published by the CLI. OCI Environment staging is unsupported.
- Local Environment source staging is the only execution form currently
  accepted by Job preflight. OCI Environment staging is unsupported.
- The local provider is not a sandbox. Docker trusts the host/daemon, cannot
  enforce disk limits or network allowlists, and has no compose/persistence.
  Daytona depends on external SDK/service behavior and lacks build-context,
  pid/disk, persistence, compose, read-only-root, and stdin support.
- Verifiers require enforced no-network execution, so verifier/regrade Jobs
  cannot use the local provider.
- Receipts are `self_reported`, unsigned, and not remote attestations.
- Exact-value log redaction cannot prevent all secret exfiltration. Artifacts
  and external logs are not generally redacted.
- Environment `max_cost_usd` is exposed to built-in loop policy but there is no
  universal independent cost meter for arbitrary external Harnesses.
- CLI `job cancel` cannot force active sandboxes in a different process; use the
  in-process async API for immediate cancellation.
- Resume and retry are aliases over locked resume: successes are skipped and
  non-successes run. There is no separate selector for one failed Trial.
- Regrade requires all Trials to have successful immutable source artifacts.
- Benchmark/Agent pins must be regenerated after Environment/Harness changes;
  there is no automatic dependency rewrite.
- Vendor adapters depend on separately installed CLIs and their changing output
  formats. ACP support is a narrow protocol-v1 stdio subset without filesystem,
  terminal, or MCP host capabilities.
- Studio Benchmark trace upload is best-effort and suppresses individual upload
  errors.
- The sandbox provider entry-point API is public Alpha and may evolve before a
  stable v1 release.

Unsupported controls fail preflight where Plural can detect them. A successful
run should not be interpreted as stronger isolation, authentication, or
durability than the selected provider and documented backend surface provide.

Hosted reads return records, not installed executable Python environments.
There is no general CLI pull command; see the [retrieval walkthrough](../guides/push-to-plural.md).
