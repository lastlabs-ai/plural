---
route: /docs/reference/schemas
title: "Package JSON Schemas"
order: 460
description: "Plural packages these deterministic schemas under plural/schemas/packages/:"
audience: all
---
# Package JSON Schemas

Plural packages these deterministic schemas under
`plural/schemas/packages/`:

- `EnvironmentDefinition.schema.json`
- `HarnessDefinition.schema.json` and `HarnessPackage.schema.json`
- `AgentDefinition.schema.json`
- `TaskDefinition.schema.json`
- `DeterministicVerifier.schema.json`, `AgentVerifier.schema.json`, and
  `HumanVerifier.schema.json`
- `BenchmarkDefinition.schema.json`
- `JobFile.schema.json` and `JobSpec.schema.json`
- `TrialSpec.schema.json`, `TrialExecution.schema.json`, and
  `TrialReceipt.schema.json`
- `ProgressEvent.schema.json` and `TITORecord.schema.json`
- `CLIConfig.schema.json` and `ResolvedContext.schema.json`

Generate and verify them with:

```bash
uv run python scripts/generate_package_schemas.py
uv run python scripts/generate_package_schemas.py --check
```

The generator derives directly from the strict Pydantic models, sorts keys, and
writes stable indentation/newlines. CI uses `--check`. The Trace schema is generated separately as `trace.v3.json`:

```bash
uv run python scripts/generate_trace_schema.py --check
```

Schema files describe syntax and model invariants. Cross-file loading also
checks relative paths, source tree/archive digests, pinned revision graphs,
per-Trial Harness compatibility, and provider capabilities. Passing JSON Schema
validation alone does not establish trust or executability.
