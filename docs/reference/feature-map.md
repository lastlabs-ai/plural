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

- Installing Plural, creating a project, signing in, and choosing a scope:
  [Getting started](../getting-started.md).
- `plural auth login`, `logout`, `status`, and `scope`, configuration
  locations, output, and exit codes: [Command-line interface](../cli/index.md).
- Local versus hosted resources, and the CLI versus the Python SDK:
  [Concepts](../getting-started/concepts.md).

## Model calls and providers

- `Client` / `Plural`, `chat`, `achat`, `stream`, `astream`, errors, retries,
  and the model catalog: [Model calls](../sdk/client.md).
- `plural models list` and the models your organization permits:
  [Agents](../project/agents.md#find-a-model).
- Model endpoints, OpenAI-compatible hosts, bring-your-own keys, and routing
  after evaluation: [Providers and integrations](integrations.md).

## Build a project

- The project layout and every manifest: [YAML and serialization](../interfaces/yaml.md).
- Environment actions, State, Observation, rewards, resources, secrets, and
  Runtime: [Environments](../project/environments.md).
- Instructions, initial State, and Task files: [Tasks](../project/tasks.md).
- Deterministic checks, model judges, and human rubrics:
  [Verifiers](../project/verifiers.md).
- The native loop, the built-in Hermes, Claude Code, and Codex Harnesses, custom
  Harness classes, and secret grants: [Harnesses](../project/harnesses.md).
- Models, instructions, and saved Agents: [Agents](../project/agents.md).
- Task collections, scoring rules, tracks, and releases:
  [Benchmarks](../project/benchmarks.md).
- Versions, content hashes, and immutability:
  [Updating and versioning](../project/updating.md).

## Run and inspect

- `plural run`, dry runs, attempts, concurrency, and the Python `Job`:
  [Jobs](../running/jobs.md).
- Docker, Daytona, hosted runs, and reruns: [Build and run a job](../guides/jobs.md).
- `plural job list`, `job show`, `job rerun`, `trial show`, and `trial rerun`:
  [Trials and trajectories](../running/trials.md).
- Receipts, artifacts, logs, and redaction:
  [Artifacts and evidence](../running/artifacts.md).
- `plural review list` and `review submit`: [Reviews](../running/reviews.md).
- `plural session export` and `session import`: [Sessions](../running/sessions.md).
- Train mode and exact token capture: [Training and RL](../running/training.md).

## Traces, datasets, and export

- Reading a recorded episode, `Trace` records from the tracing SDK, and reusing
  evidence as data: [Traces and Trials](../running/traces.md).
- Normalized trajectories and `normalize_trajectory`:
  [Trials and trajectories](../running/trials.md#trajectories).
- `Redactor`, retention, and treating captured files according to their contents:
  [Artifacts and evidence](../running/artifacts.md).
- OpenTelemetry export, hosted ingestion, and CI evaluations:
  [Providers and integrations](integrations.md#plural-intel-ci-and-opentelemetry).
- Custom `SandboxProvider` implementations and registries:
  [Sandbox provider extensions](integrations.md#sandbox-provider-extensions).

## Hosted projects

- `plural project init --push`, `plural <kind> push` and `pull`, `--with-deps`,
  `.pluralignore`, and `plural.lock`:
  [Push and pull resources](../guides/studio-sync.md).
- Publishing a Benchmark release to the public Hub, a separate step in the web
  app: [Benchmark publications](../architecture/benchmark-publications.md).

## Every CLI command

The [CLI guide](../cli/evaluation.md#command-reference) lists every command and
option, generated from the command tree. Each resource kind uses the same verbs:

```bash
plural <env|task|verifier|harness|agent|benchmark> init|validate|push|pull|show|list
```

`plural benchmark add` and `remove` edit a Benchmark's Task list. The other
groups are `plural run`, `plural job`, `plural trial`, `plural review`,
`plural models`, `plural session`, `plural project`, and `plural auth`.

## Reference and operations

- [Evaluation contract](../architecture/evaluation-contract.md) for the public
  object model, ownership, lifecycle, and SDK, YAML, and CLI parity.
- [Migrate to 0.15](../migration/projects.md) for projects and commands from
  earlier releases.
