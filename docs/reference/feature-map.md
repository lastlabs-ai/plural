---
route: /docs/reference/feature-map
title: "SDK and CLI coverage guide"
order: 440
description: "Find the page for any Plural feature, grouped by what you want to do: sign in, call models, build a project, run and inspect it, export data, or share it."
audience: all
nav: false
---
# SDK and CLI coverage guide

This page is a map. Find what you want to do, then follow the link to the page that
explains it.

If you are new, don't start here. Read [Core concepts](../getting-started/concepts.md),
then follow [Getting started](../getting-started.md) or a tutorial such as the
[support queue](../tutorials/support-queue.md) in order. Come back here when you need a
specific feature.

Every command and API named on this page exists in the installed package today. Each
linked page lists every supported parameter.

## Getting started and authentication

- Installing Plural, creating a project, signing in, and choosing a scope:
  [Getting started](../getting-started.md).
- `plural auth login`, `logout`, `status`, and `scope`, configuration
  locations, output, and exit codes: [Command-line interface](../cli/index.md).
- Local versus hosted resources, and the CLI versus the Python SDK:
  [Concepts](../getting-started/concepts.md).

## Model calls and providers

- Calling a model from Python with `Client` / `Plural`, `chat`, `achat`, `stream`,
  `astream`, errors, retries, and the model catalog: [Model calls](../sdk/client.md).
- `plural models list` and the models your organization permits:
  [Agents](../project/agents.md#find-a-model).
- Model endpoints, OpenAI-compatible hosts, bring-your-own keys, and routing
  after evaluation: [Providers and integrations](integrations.md).

## Build a project

These are the pieces you describe: the world, the assignments, the grader, and the
contestants.

- The project layout and every manifest: [YAML and serialization](../interfaces/yaml.md).
- The world (Environment): actions, State, Observation, rewards, resources, secrets,
  and Runtime: [Environments](../project/environments.md).
- The assignments (Tasks): instructions, initial State, and Task files:
  [Tasks](../project/tasks.md).
- The grader (Verifiers): deterministic checks, model judges, and human rubrics:
  [Verifiers](../project/verifiers.md).
- How the contestant plays (Harnesses): the native loop, the built-in Hermes, Claude
  Code, and Codex Harnesses, custom Harness classes, and secret grants:
  [Harnesses](../project/harnesses.md).
- The contestants (Agents): models, instructions, and saved Agents:
  [Agents](../project/agents.md).
- The exam (Benchmarks): Task collections, scoring rules, tracks, and releases:
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

Pushing saves a private copy of your work so Plural can run it for you. Nothing you
push is public.

- `plural project init --push`, `plural project push`, `plural <kind> push` and `pull`, `--with-deps`,
  `.pluralignore`, and `plural.lock`:
  [Push and pull resources](../guides/studio-sync.md).
- `plural job push`, which records a finished local Job in the hosted project:
  [Jobs](../running/jobs.md).
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
`plural agent serve` and `plural trial rescore` are reserved names that are not
available yet.

## Reference and operations

- [Evaluation contract](../architecture/evaluation-contract.md) for the public
  object model, ownership, lifecycle, and SDK, YAML, and CLI parity.
- [Migrate to 0.15](../migration/projects.md) for projects and commands from
  earlier releases.
