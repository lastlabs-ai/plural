---
route: /docs/reference/feature-map
title: "SDK and CLI coverage guide"
order: 440
description: "Use this page to find a workflow by feature. Read tutorials in order for a first run; use the linked reference for every supported parameter. APIs and command names here describe the installed package, not proposed future convenience APIs."
audience: all
nav: false
---
# SDK and CLI coverage guide

Use this page to find a workflow by feature. Read tutorials in order for a first
run; use the linked reference for every supported parameter. APIs and command
names here describe the installed package, not proposed future convenience APIs.

## Getting started and authentication

- Install, Python version, optional extras, API keys, BYOK, project scope,
  gateway URLs, and SDK versus CLI credentials: [setup](../getting-started.md).
- Device login/logout/status/whoami, profiles, org/project selection, precedence,
  config locations, output and exit codes: [CLI configuration](../cli/index.md).
- Local versus hosted objects and Python versus package execution:
  [concepts](../getting-started/concepts.md).

## Model calls and providers

- `Client` / `Plural`, `chat`, `achat`, `stream`, `astream`, closing/flushing,
  normalized requests/responses, errors, retries, tags, and catalog:
  [model client](../sdk/client.md).
- Tool fragments, structured output, reasoning, provider translations, routing
  policies, fallback order, least-cost selection, provider preference, custom
  policies, OpenAI, Anthropic, Google, compatible hosts, BYOK, Azure, Bedrock,
  and migrating existing OpenRouter-style calls:
  [providers and integrations](../reference/integrations.md).

## Python environments and evaluation

- Typed Environment, Task, Verifier, Agent, Harness, Benchmark, and Job graphs:
  [Python SDK guide](../sdk/evaluation.md).
- Environment actions, typed state/observation, Rewarders, resources, secrets,
  and runtime placement: [Environments](../project/environments.md).
- Tasks, attempts, bounded scheduling, verification, and modes:
  [Benchmarks](../project/benchmarks.md) and [Jobs](../running/jobs.md).

## Traces, datasets, and export

- Record, label, read, filter, save, reload, upload, and curate new tasks:
  [traces](../running/traces.md) and [artifacts](../running/artifacts.md).
- `Trace`, action steps, reward events, usage, latency, and reusing evidence as
  datasets: [traces](../running/traces.md#reuse-evidence-responsibly).
- `Redactor`, content retention, and treating captured files according to their
  contents: [artifacts](../running/artifacts.md).
- OpenTelemetry export, hosted ingestion, and CI evaluations:
  [providers and integrations](../reference/integrations.md#plural-intel-ci-and-opentelemetry).
- Hugging Face-style records and verifier-style traces:
  [Python SDK guide](../sdk/evaluation.md).

## Package authoring and execution

- Environment/harness/agent/benchmark/job creation, inspection, dry run, model
  access, updates, and first execution: [CLI tutorial](../tutorials/cli-walkthrough.md).
- Environment actions, artifacts, and grading:
  [Verifiers](../project/verifiers.md).
- `Job`, `Trial`, `JobStore`, programmatic planning, execution,
  cancellation, resume, and reports: [Jobs](../running/jobs.md).
- Attempts versus retries, deterministic locks, receipts, and identity:
  [Jobs](../running/jobs.md) and [job operations](../guides/jobs.md).
- Docker/Daytona, concurrency, runtime health, retries/resume/cancel:
  [job operations](../guides/jobs.md).
- Built-in Hermes, Claude Code, and Codex names, custom Harness loops, ACP,
  immutable archives, OCI, and secret grants: [Harnesses](../project/harnesses.md).
- Custom `SandboxProvider` implementations and registries:
  [provider extensions](../reference/integrations.md#sandbox-provider-extensions).

## Plural Intel objects

- Publish and resolve exact Environment, Harness, Agent, Task, Verifier, and
  cross-Environment Benchmark versions. Preserve Task-or-Benchmark Job sources,
  Trial/TrialExecution identity, append-only events, human review state, and
  artifact digests: [studio sync](../guides/studio-sync.md).

## Every CLI command group

The [CLI guide](../cli/evaluation.md#command-reference) includes every command
and option, generated from the command tree.

- `init`, `validate`, `inspect`, `export`, `models`, and `benchmarks`:
  [CLI tutorial](../tutorials/cli-walkthrough.md).
- `job init/list/show/watch`, `trial list/watch`, and `review list/submit`:
  [job operations](../guides/jobs.md).
- `run REF [--agent REF...] [--mode <eval|train>]` and `schemas`:
  [CLI overview](../cli/index.md).

## Reference and operations

- [Evaluation contract](../architecture/evaluation-contract.md) for the public
  object model, ownership, lifecycle, and SDK/YAML/CLI parity.
- [Version migration](../migration/v1.md) for users of the earlier API.
