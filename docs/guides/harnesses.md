# Harness packages and adapters

A HarnessPackage is one executable agent loop plus a strict manifest. One
Agent binds exactly one Harness revision and every Trial for that Agent uses the
same binding.

## Minimal package

```yaml
manifest:
  schema_version: "1"
  name: minimal
  version: 0.1.0
  protocol: plural-harness-v1
  command: [python, harness.py]
  auth_modes: [none]
  outputs:
    - {path: result.json, required: true, media_type: application/json}
  artifacts:
    - {path: trajectory.jsonl, required: true, media_type: application/jsonl}
source:
  kind: local
  uri: .
  unsafe_local: true
```

The executable reads one `HarnessRunRequest` JSON line from stdin and writes
JSON-line events to stdout. It must finish with exactly one `result` or `error`
event. Result paths must match declared regular files. A harness cannot emit
`score`, `scores`, `reward`, `verifier`, or `expected` anywhere in an event;
only the isolated verifier can score.

Use `plural harness init`, then:

```bash
plural harness validate harness
plural harness test harness --unsafe-local
plural harness inspect harness
plural harness build harness
plural harness publish harness --output dist/minimal.tar.gz
```

`build` and `publish` create the same normalized gzip/tar format (sorted paths,
zero timestamps/owners, no symlinks) and print its SHA-256. Publish currently
writes only to a local path; it does not upload to a registry.

## Immutable archives

Add a local file or HTTPS archive with the exact digest:

```bash
plural harness add dist/minimal.tar.gz \
  --digest sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --environment environment
```

Remote/archive references require a digest. Retrieval accepts HTTPS, `file://`,
or local paths, refuses HTTPS downgrade, limits compressed/extracted data to
100 MiB, rejects links/devices/FIFOs/path traversal/duplicates, verifies bytes
before extraction, and caches by digest. This is integrity, not publisher
identity. Cache hits are revalidated against the authenticated archive and a
tampered extracted tree is rebuilt.

Plural does not currently verify Sigstore, Notary, cosign, PGP, transparency
logs, or certificate identity. There is no signature field in schema v1.
Distribute the expected digest through a separately trusted channel.
`load_harness` derives a binding from the current local source tree, so source
changes alter the binding, but mutable local development still requires
`--unsafe-local`. `trusted: true` does not bypass that requirement. Build and
add the digest-pinned archive for immutable execution.

## OCI

An OCI `PackageSource` must be digest pinned. OCI harness execution currently:

- requires the Docker provider;
- treats the digest-pinned harness image as the runtime image;
- cannot compose that image with a separate Environment image, snapshot,
  declarative image, or build context;
- does not stage OCI Environment sources;
- does not pull or publish OCI artifacts through CLI package commands;
- does not verify signatures or attestations.

Use an archive package when the harness needs to be uploaded into a separately
built Environment image.

## ACP adapter

Set `protocol: acp` and `protocol_adapter: acp-client-v1`; `command` is the ACP
agent argv. Plural installs its adapter into the sandbox and translates ACP v1
`initialize`, `session/new`, `session/prompt`, updates, cancellation, and the
final response into `result.json` and `trajectory.jsonl`.

The current ACP client advertises no filesystem read/write and no terminal
capability, passes no MCP servers, supports protocol version 1 only, and rejects
agent callbacks it cannot serve. Treat this as a narrow stdio adapter rather
than complete ACP host compatibility.

## Claude Code, Codex, and Hermes

`plural.harness.ADAPTER_RECIPES` contains manifests and installation recipes for
`claude-code`, `codex`, and `hermes-agent`. Plural ships adapter source only; it
does not bundle, install, license, authenticate, or pin the vendor CLI.

- Claude Code expects `claude`, supports Anthropic models, and may receive
  `ANTHROPIC_API_KEY` or the vendor's own OAuth state.
- Codex expects `codex`, supports OpenAI models, and may receive
  `OPENAI_API_KEY` or vendor OAuth state.
- Hermes expects `hermes`, allows any declared model, and may receive
  `OPENROUTER_API_KEY`.

Vendor stdout formats and flags can change independently. Copy the recipe into a
versioned external package, pin the vendor dependency yourself, declare only
required secret names, run `harness test`, and publish a digest-pinned archive.

## Secret grants

`HarnessManifest.secret_names` is the allowlist a package may request.
`AgentSpec.secret_names` is the subset granted to that Agent and is rejected
when undeclared. Only granted values present in the parent environment are
passed. Plural replaces exact secret byte values in captured harness stdout,
stderr, and error messages, but cannot redact transformed/encoded secrets,
files the harness writes, provider-side logs, or side channels. Use scoped,
short-lived credentials and network controls.
