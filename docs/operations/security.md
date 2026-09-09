# Security, isolation, and trust

## Credentials

Interactive tokens are stored in the OS keyring when the optional `keyring`
extra works; otherwise Plural writes owner-only `credentials.json` in an
owner-only config directory. This fallback is permissions protection, not
encryption. Non-secret profile context is in `config.toml`. CI should inject a
scoped `PLURAL_API_KEY` through its secret manager.

Harnesses receive only names declared by the package and granted by the Agent.
Exact secret values are redacted from captured process output and surfaced
errors. Redaction does not cover encoded, fragmented, hashed, or transformed
values, harness artifacts, child/provider logs, network traffic, or a malicious
runtime. Rotate credentials after any suspected exposure.

## Boundaries

The Environment owns instructions, tasks, hidden evaluator values, commands,
code/source, limits, policy, and verifier. The harness sees only public task
data and the declared environment view. It must not score itself.

The verifier is launched separately, with networking disabled, and receives
hidden expected/verifier input plus declared artifacts. Separate launch reduces
accidental leakage but shares the selected provider, host/provider account,
runtime image policy, and local job store. It is not an independent
administrative trust domain.

`local` provides no isolation. Docker drops Linux capabilities, enables
no-new-privileges, runs as UID/GID 65532, applies a pid limit, and can disable
networking/read-only root and CPU/memory controls. The Docker daemon and host
remain trusted; disk limits and allowlist networking are unsupported. Daytona
is a remote external trust boundary whose enforcement and retention also depend
on the service and SDK.

Preflight refuses requested controls that a provider cannot claim. Receipts
record the provider-confirmed effective policy and image/runtime identities, but
all receipts currently say `trust: self_reported`. They are content-integrity
records, not signed attestations or proof of execution.

## Packages and artifacts

Remote/archive/OCI Harness sources require SHA-256 locks. Archive extraction
rejects traversal, links, special files, duplicates, and oversized content.
Local source may be explicitly trusted/unsafe, which is a user decision.
Publisher signatures, OCI attestations, and transparency verification are not
implemented.

Only exact declared regular output/artifact paths are downloaded. Paths are
relative and cannot contain traversal. Stored artifacts are immutable by path:
a later retry cannot silently replace bytes. Treat artifact contents as
untrusted input when opening or publishing them.

## Network and resources

Prefer `network: none`. Restricted allowlists are available only where the
provider advertises them (currently Daytona, not Docker/local). Default
`RuntimeSpec.network` is `full`, so set a stricter value deliberately. Limits
are provider-specific; unsupported disk/pid/read-only controls fail rather than
degrade.

Timeout is enforced by the provider/host and cancellation destroys active
sandboxes where possible. A process that escapes the provider boundary, a
daemon failure, or external side effect may outlive the Job.

## Cleanup and retention

Normal paths destroy each harness/verifier sandbox in `finally` blocks. Docker
containers carry `dev.plural.execution=true`; Daytona cancellation deletes the
remote sandbox. Crashes, host loss, or provider outages can leave resources
behind—periodically inspect provider consoles/daemon labels.

Local job records, logs, receipts, hidden verifier inputs during execution, and
artifacts may be sensitive. Plural has no retention scheduler or secure-delete
guarantee. Restrict access to `.plural/jobs` and delete it according to your own
policy after preserving required audit evidence.
