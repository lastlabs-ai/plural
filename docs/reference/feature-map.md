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
  gateway URLs, and SDK versus CLI credentials: [setup](../getting-started/setup.md).
- Device login/logout/status/whoami, profiles, org/project selection, precedence,
  config locations, output and exit codes: [CLI configuration](../cli/index.md).
- Local versus hosted objects and Python versus package execution:
  [concepts](../getting-started/concepts.md).

## Model calls and providers

- `Client` / `Plural`, `chat`, `achat`, `stream`, `astream`, closing/flushing,
  normalized requests/responses, errors, retries, tags, and catalog:
  [model client](../sdk/client.md).
- Tool fragments, structured output, reasoning, and provider translations:
  [capabilities](../guides/capabilities.md).
- Routing policies, fallback order, least-cost selection, provider preference,
  custom policies: [routing concepts](../concepts/routing.md).
- OpenAI, Anthropic, Google, compatible hosts, BYOK, and custom in-process
  providers: [routing examples](../guides/routing-examples.md).
- Azure and AWS Bedrock: [cloud providers](../guides/cloud-providers.md).
- Implement a provider: [provider guide](../guides/add-provider.md).
- Migrate existing OpenRouter-style calls: [migration guide](../guides/migrate-openrouter.md).

## Python environments and evaluation

- Typed Environment, Runtime, Agent, Verifier, Task, Benchmark, and Job graphs:
  [SDK tutorial](../tutorials/sdk-walkthrough.md).
- Environment actions, typed state/observation, Rewarders, resources, secrets,
  and runtime placement: [authoring guide](../guides/write-environment.md).
- Cross-Environment Task selection, attempts, bounded scheduling, verification,
  and modes: [benchmark guide](../guides/benchmark-models.md) and
  [benchmark concepts](../concepts/benchmark.md).

## Traces, datasets, and export

- Record, label, read, filter, save, reload, upload, and curate new tasks:
  [trace and dataset tutorial](../tutorials/traces-and-datasets.md).
- `Trace`, `TraceContext`, `Turn`, action steps, reward events, credit,
  transitions and returns: [trace concepts](../concepts/trace.md).
- Trace `Dataset`, filtering, hashes, and manifests:
  [datasets](../concepts/dataset.md).
- `JSONLSink`, `SQLiteSink`, `MultiSink`, `OTelSink`, writer lifecycle:
  [sinks](../concepts/sink.md), [capture](../guides/capture-traces.md),
  [OpenTelemetry](../guides/export-otel.md).
- `Redactor`, `Sampler`, content retention: [redaction](../guides/redact-pii.md).
- Hugging Face-style records and verifier-style traces:
  [export API](api.md#datasets-and-export).

## Package authoring and execution

- Environment/harness/agent/benchmark/job creation, inspection, dry run, model
  access, updates, and first execution: [CLI tutorial](../tutorials/cli-walkthrough.md).
- Environment action adapters, JSON stdin/stdout, artifacts, and grading:
  [actions and verifier tutorial](../tutorials/package-tools.md).
- `Job`, `Trial`, `JobStore`, programmatic planning, execution,
  cancellation, resume, and reports: [Python jobs](../sdk/package-jobs.md).
- Attempts versus retries, deterministic locks, receipts, and identity:
  [execution concepts](../concepts/execution.md).
- Docker/Daytona, concurrency, runtime health, retries/resume/cancel:
  [job operations](../guides/jobs.md).
- Custom harness protocols, first-party profiles, vendor recipes, ACP,
  immutable archives, OCI, and secret grants: [harness guide](../guides/harnesses.md).
- Custom `SandboxProvider` implementations and registries:
  [runtime plugins](../guides/provider-plugins.md).

## Plural Intel objects

- Publish and resolve exact Environment, Harness, Agent, Task, Verifier, and
  cross-Environment Benchmark versions:
  [advanced hosted API](../sdk/hosted-advanced.md).
- Preserve Task-or-Benchmark Job sources, Trial/TrialExecution identity,
  append-only events, human review state, and artifact digests:
  [package sync](../guides/studio-sync.md).

## Every CLI command group

The [generated CLI reference](cli-commands.md) includes all options, positional
arguments, defaults, help, and shell-completion flags. Its entries are generated
from the command tree and checked for drift.

- `init`, `validate`, `inspect`, `export`, `models`, and `benchmarks`:
  [CLI tutorial](../tutorials/cli-walkthrough.md).
- `job init/list/show/watch`, `trial list/watch`, and `review list/submit`:
  [job operations](../guides/jobs.md).
- `run REF [--agent REF...] [--mode <eval|train>]` and `schemas`:
  [CLI overview](../cli/index.md).

## Reference and operations

- [Python API](api.md), [definition fields](definitions.md), [package schemas](schemas.md),
  [trace schema](trace-schema.md), and [glossary](glossary.md).
- [CI evaluations](../guides/ci.md).
- [Security and trust](../operations/security.md),
  [troubleshooting](../operations/troubleshooting.md), [limitations](limitations.md).
- [Version migration](../migration/v1.md) for users of the earlier API.
