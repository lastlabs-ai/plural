---
route: /docs/guides/harnesses
title: "Build and bind a Harness"
order: 280
description: "A HarnessPackage contains a schema-v2 manifest and content-addressed source. It declares its protocol, command, capabilities, supported models, authentication modes, secret names, outputs, and artifacts."
audience: all
---
# Build and bind a Harness

A `HarnessPackage` contains a schema-v2 manifest and content-addressed source.
It declares its protocol, command, capabilities, supported models,
authentication modes, secret names, outputs, and artifacts.

```bash
plural harness init harness --name support-loop
plural harness validate harness
plural harness show harness
```

Bind the Harness to an Environment-independent Agent:

```bash
plural agent init agent.yaml --name candidate \
  --model openai/gpt-4.1-mini --harness harness
plural agent validate agent.yaml
```

`AgentDefinition` carries the exact Harness binding/package but never an
Environment identity. During planning, Plural resolves a compatibility stamp
for each Trial against the selected Task's Environment.

## Protocol

A runnable `plural-harness-v1` process reads one JSON request from stdin and
emits JSONL events on stdout. It writes declared outputs and artifacts at safe
relative paths. ACP packages declare `protocol: acp` and
`protocol_adapter: acp-client-v1`.

Declared-only Harnesses describe compatibility but cannot execute.

## Capabilities and secrets

Effective capabilities are the intersection of provider, project,
Environment, Harness, and Agent policy. Any unsatisfied requirement fails
preflight before a sandbox is created.

`HarnessManifest.secret_names` is the allowlist a package may request.
`AgentDefinition.secret_names` is the granted subset. The selected Environment
must also allow those names. Secret values are injected by the runtime and are
never embedded in canonical manifests.

## Train-only TITO

Set `supports_tito: true`, choose `tito_path`, and declare that path as an
artifact. Train mode fails preflight when the selected Harness cannot provide
exact TITO. Eval mode never requests it.

Each JSONL record includes step, tokenizer/model, input/output/observation token
IDs, aligned output log probabilities and top log probabilities, output text,
assistant message, and validated input/output/observation lengths. The engine
stores the file as an immutable hashed artifact.

## Source integrity

Remote archive and OCI sources require SHA-256 digests. Local sources require
an explicit unsafe-local declaration and are suitable only for reviewed
development code. Archive extraction rejects traversal, links, special files,
duplicates, and oversized content.

See [execution capabilities](../concepts/execution-capabilities.md) and
[package tools](../tutorials/package-tools.md).
