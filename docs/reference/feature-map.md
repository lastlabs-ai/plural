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

- Runnable native actions, tasks, scorer, scripted smoke test, single-model
  rollout, model comparison, real task input:
  [SDK tutorial](../tutorials/sdk-walkthrough.md).
- `Environment`, `State`, `Observation`, `hidden`, decorated actions, setup/done,
  `ActionResult`, snapshots, fingerprints, and reconstruction:
  [authoring guide](../guides/write-environment.md).
- `reset`, final `step`, `messages`, `close_episode`, stop reasons, replay,
  `Policy` / `PluralPolicy` / `ScriptedPolicy`, synchronous tool `Runtime`:
  [environment lifecycle](../concepts/environment.md).
- `Benchmark`, `Report`, repeats/concurrency, policy factories, paired win rates,
  compatibility and regression tolerance: [benchmark guide](../guides/benchmark-models.md)
  and [benchmark concepts](../concepts/benchmark.md).

## Traces, datasets, and export

- Record, label, read, filter, save, reload, upload, and curate new tasks:
  [trace and dataset tutorial](../tutorials/traces-and-datasets.md).
- `Trace`, `TraceContext`, `Turn`, action steps, reward events, credit,
  transitions and returns: [trace concepts](../concepts/trace.md).
- `TaskDataset`, `Dataset` / `TraceDataset`, `TraceFilter`, hashes and manifests:
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
- Native action schemas, JSON stdin/stdout, `native.actions.v1`, artifacts, and
  grading: [actions and verifier tutorial](../tutorials/package-tools.md).
- `JobSpec`, `Job`, `Trial`, `JobStore`, programmatic planning, execution,
  cancellation, resume, and reports: [Python jobs](../sdk/package-jobs.md).
- Attempts versus retries, deterministic locks, receipts, and identity:
  [execution concepts](../concepts/execution.md).
- Docker/Daytona, concurrency, runtime health, retries/resume/regrade/cancel:
  [job operations](../guides/jobs.md).
- Custom harness protocols, first-party profiles, vendor recipes, ACP,
  immutable archives, OCI, and secret grants: [harness guide](../guides/harnesses.md).
- Custom `SandboxProvider` implementations and registries:
  [runtime plugins](../guides/provider-plugins.md).

## Plural Intel objects

- List/get/create/update/delete environments, agent templates, instances, and
  benchmarks; invoke hosted templates; snapshot records; reuse stored package
  definitions: [object walkthrough](../guides/push-to-plural.md).
- Exact harness revisions, environment stamps, benchmark revisions and
  promotion, jobs/trials and result upload: [advanced hosted API](../sdk/hosted-advanced.md).
- `env push`, `run --sync`, `job upload`, delivery and local/hosted boundaries:
  [package sync](../guides/studio-sync.md).

## Every CLI command group

The [generated CLI reference](cli-commands.md) includes all options, positional
arguments, defaults, help, and shell-completion flags. Its entries are generated
from the command tree and checked for drift.

- `auth login`, `logout`, `status`, `whoami`: [setup](../getting-started/setup.md).
- `org use/show/list`, `project use/show/list`: [CLI context](../cli/index.md).
  The `list` commands currently report unsupported backend functionality.
- `env init/validate/build/push`, `env action add/list/remove`,
  `env resource add/list`, `env capabilities`, `env harness stamp/unstamp/list/capabilities`,
  `env task add/list`:
  [CLI tutorial](../tutorials/cli-walkthrough.md) and [sync](../guides/studio-sync.md).
  `env build` writes a deterministic manifest artifact; it does not build a
  runtime image or publish source code.
- `harness init/validate/build/test/publish/add/list/inspect`:
  [harness guide](../guides/harnesses.md).
- `agent template init/show/validate/push`, `agent instance list/show/memory/skills/data/experience`,
  `benchmark init/validate/show`, `job init`, and `run`:
  [CLI tutorial](../tutorials/cli-walkthrough.md).
- `runtime list/show/doctor [--env]`: [runtime operations](../guides/jobs.md).
- `job list/show/resume/retry/regrade/cancel/upload`, `trial list/show`:
  [job operations](../guides/jobs.md).

There are no general hosted CLI list/get/update/pull commands for environments,
agents, and benchmarks. `agent list` finds local `agent.yaml` files at the given
root and one directory level below; it does not find every arbitrarily named
YAML file. Use hosted SDK helpers for Plural Intel reads and metadata updates.

## Reference and operations

- [Python API](api.md), [manifest fields](manifests.md), [package schemas](schemas.md),
  [trace schema](trace-schema.md), and [glossary](glossary.md).
- [CI evaluations](../guides/ci.md).
- [Security and trust](../operations/security.md),
  [troubleshooting](../operations/troubleshooting.md), [limitations](limitations.md).
- [Version migration](../migration/v1.md) for users of the earlier API.
