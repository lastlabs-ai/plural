---
route: /docs/reference/definitions
title: "Definition field reference"
order: 450
description: "All schema-v2 models are frozen, reject unknown fields, and use schema_version: \"2\" where present. Generated JSON Schemas are the exact validation authority."
audience: all
---
# Definition field reference

All schema-v2 models are frozen, reject unknown fields, and use `schema_version: "2"`
where present. Generated JSON Schemas are the exact validation authority.

## `PackageSource`

- `kind`: `local`, `archive`, or `oci`.
- `uri`: non-empty path/URL/reference.
- `digest`: optional only for local; otherwise `sha256:` plus 64 lowercase hex.
- `trusted`: deprecated migration field; never bypasses integrity/unsafe checks.
- `unsafe_local`: explicit unsigned local opt-in; invalid for remote kinds.

## `HarnessDefinition` and `HarnessPackage`

- `schema_version`, `name`, `revision`, `description`.
- `protocol`: `plural-harness-v1` or `acp`.
- `protocol_adapter`: must be `acp-client-v1` exactly when protocol is ACP.
- `entrypoint`: optional metadata; execution uses `command`.
- `implementation`: `declared` or `runnable`. Declared harnesses have no command.
- `command`: required argv only when `implementation` is `runnable`.
- `requirements`, `capabilities` (`HarnessCapability` values), `supported_models`.
- `auth_modes`: any of `environment`, `api_key`, `oauth`, `none`.
- `secret_names`: secrets an Agent may grant.
- `environment_names`: non-secret process environment names passed when set.
- `healthcheck`: optional argv run before the harness.
- `trajectory_path`: optional path that must also be declared and emitted as an
  artifact.
- `outputs`, `artifacts`: exact `FileDeclaration` values (`path`, `required`,
  `media_type`).
- `HarnessPackage.definition` and `.source`: complete package. `content_hash` and
  `package_id` are derived. Load still accepts the 0.10 key `manifest`.

`HarnessBinding` contains `name`, `revision`, and required digest.

## `EnvironmentDefinition`

- `schema_version`, `name`, `revision`, `description`, `overview`, `readme`,
  and `metadata`.
- unique native `actions`, typed `observation_schema`, and hidden
  `state_schema`.
- train-only `rewarders`, plus `guardrails`, `resources`, and named `secrets`.
- `runtime`: the Environment-owned provider, placement, image/build,
  network, resources, targets, persistence, compose, and local opt-in.
- `harness_policy` and execution `limits`.
- optional `source`.

Tasks, Verifiers, and Job mode are intentionally absent.
`Environment.definition()` compiles a Python Environment class.

## `VerifierDefinition` and `TaskDefinition`

A Verifier is a discriminated `deterministic`, `agent`, or `human` revision.
Every kind carries an `EvidenceContract` (`artifacts`, `observation_paths`,
`state_paths`, `include_hidden_state`). Deterministic and agent Verifiers own
their runtime and network policy. Human Verifiers own a rubric and
instructions and yield `awaiting_review` until a review is submitted.

A Task owns `task_id`, `revision`, `instructions`, `info`, and `metadata`. It
embeds one exact Environment revision and one or more `WeightedVerifier`
revisions. Pin-time rejects a Verifier whose evidence paths are absent from
the Environment schemas.

## `BenchmarkDefinition`

A Benchmark owns `name`, `revision`, description, primary metric, metadata, and
an ordered unique list of complete Task revisions. Those Tasks may pin different
Environments.

## `AgentDefinition`

- `schema_version`, `name`, `revision`, `model`, `instructions`, and metadata.
- `routing`: provider, fallbacks, temperature, and maximum tokens.
- optional exact Harness binding/package, authentication mode, and secret grants.

An Agent never owns an Environment. Harness tool policy (`HarnessGrant`) is
resolved against the Task's Environment for each Trial.

## `JobFile` and `JobSpec`

`JobFile` has a discriminated `source_kind` (`task` or `benchmark`), one source
path, Agent paths, `mode`, `attempts`, global concurrency,
`per_runtime_concurrency`, and priority. Paths resolve relative to the Job file.

Resolved `JobSpec` embeds a `TaskJobSource` or `BenchmarkJobSource` and Agent
bindings. It owns scheduling and retry policy only; each selected Task's
Environment owns its runtime.

## Planning, Trials, and receipts

`TrialSpec` contains Job, Agent, Task, one-based attempt, exact
Environment/Harness bindings, the per-Trial `harness_grant`, and the
Environment's runtime provider. `trial_id` is derived independently of retries.

Each retry appends a `TrialExecution` with its own execution index. Jobs and
executions append monotonic `ProgressEvent` records. Human results use
`awaiting_review`.

`TrialReceipt` records Trial/Job/retry/attempt identity; Environment,
Agent, Harness, Runtime, image, task, trace, artifact and verifier hashes;
the grant; UTC timestamps; and `trust`, currently only `self_reported`.
