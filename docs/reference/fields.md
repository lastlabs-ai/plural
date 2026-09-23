---
route: /docs/reference/fields
title: "Field catalog"
order: 205
description: "Post-resolution constructor schemas generated from the current Plural models."
audience: all
nav: false
nav_group: Reference
---
# Field catalog

Use this catalog after the conceptual guides. It is generated from the post-resolution Pydantic constructor models, including nested types. Required fields have no usable default. Custom cross-field validators also apply.

These schemas describe resolved object values, not Python references, source materialization, runtime capability checks, or side effects. The imperative public `Job` constructor is omitted because it is not a Pydantic model; use the [Jobs guide](../running/jobs.md) and [Python SDK guide](../sdk/evaluation.md) for its source, Agent, mode, attempt, concurrency, retry, planning, and run arguments. Methods and Client request types belong in the API reference.

For Python-authored Environments, `runtime` is a required Environment parameter. The resolved schema below lists it as optional because it also describes stored definitions; use the [Environments guide](../project/environments.md) when creating an Environment.

[Download the complete schemas](../assets/project-schemas.json).

## Find a contract

- [Environment](#environment)
- [Harness](#harness)
- [Task](#task)
- [DeterministicVerifier](#deterministicverifier)
- [AgentVerifier](#agentverifier)
- [HumanVerifier](#humanverifier)
- [Agent](#agent)
- [Benchmark](#benchmark)
- [BenchmarkCategory](#benchmarkcategory)
- [BenchmarkScoring](#benchmarkscoring)
- [Capability](#capability)
- [DeclarativeImage](#declarativeimage)
- [Resource](#resource)
- [Runtime](#runtime)
- [EvaluationTrack](#evaluationtrack)
- [ExecutionLimits](#executionlimits)
- [ExecutionTarget](#executiontarget)
- [FileDeclaration](#filedeclaration)
- [Guardrail](#guardrail)
- [HarnessCapability](#harnesscapability)
- [HarnessDefinition](#harnessdefinition)
- [HarnessPolicy](#harnesspolicy)
- [Action](#action)
- [NetworkMode](#networkmode)
- [ResourceRequirements](#resourcerequirements)
- [Rewarder](#rewarder)
- [RubricCriterion](#rubriccriterion)
- [RuntimeVariable](#runtimevariable)
- [Secret](#secret)
- [VerifierRuntime](#verifierruntime)

## Environment

Schema-v2 Environment. Tasks, Verifiers, and mode are intentionally absent.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`description`** — `string`; optional. Default: `""`.
- **`overview`** — `string`; optional. Default: `""`.
- **`readme`** — `string`; optional. Default: `""`.
- **`actions`** — `array of Action`; optional. Default: `[]`.
- **`reset_command`** — `array of string`; optional. Default: `[]`.
- **`observation_schema`** — `object`; optional.
- **`state_schema`** — `object`; optional.
- **`rewarders`** — `array of Rewarder`; optional. Default: `[]`.
- **`guardrails`** — `array of Guardrail`; optional. Default: `[]`.
- **`resources`** — `array of Resource`; optional. Default: `[]`.
- **`runtime`** — `Runtime`; optional.
- **`secrets`** — `array of Secret`; optional. Default: `[]`.
- **`harness_policy`** — `HarnessPolicy`; optional.
- **`limits`** — `ExecutionLimits`; optional.
- **`metadata`** — `object`; optional.

## Harness

Base class for an Agent interaction loop.

- **`config`** — `object`; optional.

## Task

One versioned unit of work in a Python-authored Environment.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`instructions`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`goals`** — `array of string`; optional. Default: `[]`.
- **`info`** — `JSON value`; optional. Default: `null`.
- **`metadata`** — `object`; optional.
- **`environment`** — `JSON value`; required.
- **`verifiers`** — `array of DeterministicVerifier | AgentVerifier | HumanVerifier`; required. Constraints: `{"minItems": 1}`.
- **`resources`** — `array of Resource`; optional. Default: `[]`.
- **`initial_state`** — `object`; optional.
- **`reset_options`** — `object`; optional.

## DeterministicVerifier

Function or command that scores a completed Episode.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`info`** — `JSON value`; optional. Default: `null`.
- **`criteria`** — `array of RubricCriterion`; optional. Default: `[]`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`metadata`** — `object`; optional.
- **`kind`** — `"deterministic"`; optional. Default: `"deterministic"`.
- **`check`** — `JSON value`; required.
- **`runtime`** — `VerifierRuntime`; optional.
- **`result_path`** — `string`; optional. Default: `"verifier-result.json"`.
- **`evidence_required`** — `boolean`; optional. Default: `true`.

## AgentVerifier

Model-judge verifier with its own runtime and connectivity policy.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`info`** — `JSON value`; optional. Default: `null`.
- **`criteria`** — `array of RubricCriterion`; required. Constraints: `{"minItems": 1}`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`metadata`** — `object`; optional.
- **`kind`** — `"agent"`; optional. Default: `"agent"`.
- **`model`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`instructions`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`provider`** — `string | null`; optional. Default: `null`.
- **`fallback_models`** — `array of string`; optional. Default: `[]`.
- **`runtime`** — `VerifierRuntime`; optional.

## HumanVerifier

Human review verifier.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`info`** — `JSON value`; optional. Default: `null`.
- **`criteria`** — `array of RubricCriterion`; required. Constraints: `{"minItems": 1}`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`metadata`** — `object`; optional.
- **`kind`** — `"human"`; optional. Default: `"human"`.
- **`instructions`** — `string`; optional. Default: `""`.

## Agent

A catalog-backed model and its optional execution harness.

- **`model`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`name`** — `string`; optional. Default: `""`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`provider`** — `string | null`; optional. Default: `null`.
- **`instructions`** — `string`; optional. Default: `""`.
- **`fallback_models`** — `array of string`; optional. Default: `[]`.
- **`temperature`** — `number | null`; optional. Default: `null`.
- **`max_tokens`** — `integer | null`; optional. Default: `null`.
- **`harness`** — `HarnessDefinition | Harness | string | null`; optional. Default: `null`.
- **`harness_kwargs`** — `object`; optional.
- **`auth_mode`** — `"environment" | "api_key" | "oauth" | "none"`; optional. Default: `"environment"`.
- **`secret_names`** — `array of string`; optional. Default: `[]`.
- **`metadata`** — `object`; optional.

## Benchmark

A semantic version that pins an ordered set of Tasks.

- **`categories`** — `array of BenchmarkCategory`; optional. Default: `[]`.
- **`scoring`** — `BenchmarkScoring`; optional.
- **`tracks`** — `array of EvaluationTrack`; optional. Default: `[]`.
- **`default_view`** — `"models" | "agents"`; optional. Default: `"agents"`.
- **`purpose`** — `string`; optional. Default: `""`.
- **`success`** — `string`; optional. Default: `""`.
- **`limitations`** — `array of string`; optional. Default: `[]`.
- **`license`** — `string`; optional. Default: `""`.
- **`forked_from`** — `string | null`; optional. Default: `null`.
- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; required.
- **`tasks`** — `array of Task`; required. Constraints: `{"minItems": 1}`.
- **`primary_metric`** — `string`; optional. Default: `"score"`.
- **`description`** — `string`; optional. Default: `""`.
- **`metadata`** — `object`; optional.

## BenchmarkCategory

A named group of Tasks, scored together in results.

- **`id`** — `string`; required.
- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`description`** — `string`; optional. Default: `""`.
- **`tasks`** — `array of string`; required. Constraints: `{"minItems": 1}`.
- **`taxonomy`** — `string | null`; optional. Default: `null`.

## BenchmarkScoring

How a release turns attempts into one score per configuration.

- **`metric`** — `string`; optional. Default: `"Score"`.
- **`description`** — `string`; optional. Default: `""`.
- **`aggregation`** — `"weighted_mean"`; optional. Default: `"weighted_mean"`.
- **`score_range`** — `array of JSON value`; optional. Default: `[0.0, 1.0]`. Constraints: `{"maxItems": 2, "minItems": 2}`.
- **`success_threshold`** — `number | null`; optional. Default: `1.0`.
- **`task_weights`** — `object`; optional.
- **`coverage_required`** — `number`; optional. Default: `1.0`. Constraints: `{"exclusiveMinimum": 0, "maximum": 1}`.
- **`agent_failure`** — `"zero" | "exclude"`; optional. Default: `"zero"`.
- **`infrastructure_error`** — `"exclude"`; optional. Default: `"exclude"`.
- **`min_tasks_for_interval`** — `integer`; optional. Default: `5`. Constraints: `{"minimum": 2}`.

## Capability

Individual controls a provider can enforce.

Allowed values: `"image" | "build" | "resources" | "network_none" | "network_allowlist" | "upload" | "download" | "timeout" | "cancel" | "persistence" | "compose" | "read_only_root" | "working_directory" | "environment" | "log_capture"`.


## DeclarativeImage

Portable subset of Daytona's declarative image builder.

- **`base`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`pip_packages`** — `array of string`; optional. Default: `[]`.
- **`environment`** — `object`; optional.
- **`workdir`** — `string | null`; optional. Default: `null`.

## Resource

Data or application supplied by an Environment.

- **`kind`** — `"data" | "application" | "file"`; required.
- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`path`** — `string | null`; optional. Default: `null`.
- **`uri`** — `string | null`; optional. Default: `null`.
- **`digest`** — `string | null`; optional. Default: `null`.
- **`content_type`** — `string`; optional. Default: `""`.
- **`config`** — `object`; optional.
- **`description`** — `string`; optional. Default: `""`.
- **`delivery`** — `"descriptor" | "source" | "inline" | "resolver"`; optional. Default: `"descriptor"`.
- **`content`** — `string | null`; optional. Default: `null`.
- **`resolver`** — `string | null`; optional. Default: `null`.

## Runtime

Where an Environment runs: Docker, a trusted local process, or Daytona.

- **`provider`** — `string`; optional. Default: `"docker"`. Constraints: `{"minLength": 1}`.
- **`placement`** — `object`; optional.
- **`variables`** — `array of RuntimeVariable`; optional. Default: `[]`.
- **`image`** — `string | null`; optional. Default: `null`.
- **`snapshot`** — `string | null`; optional. Default: `null`.
- **`declarative_image`** — `DeclarativeImage | null`; optional. Default: `null`.
- **`build_context`** — `string | null`; optional. Default: `null`.
- **`dockerfile`** — `string | null`; optional. Default: `null`.
- **`network`** — `NetworkMode`; optional. Default: `"public"`.
- **`network_allowlist`** — `array of string`; optional. Default: `[]`.
- **`resources`** — `ResourceRequirements`; optional.
- **`read_only_root`** — `boolean`; optional. Default: `false`.
- **`targets`** — `array of ExecutionTarget`; optional. Constraints: `{"uniqueItems": true}`.
- **`persistent`** — `boolean`; optional. Default: `false`.
- **`compose`** — `boolean`; optional. Default: `false`.
- **`extra_capabilities`** — `array of Capability`; optional. Default: `[]`. Constraints: `{"uniqueItems": true}`.
- **`timeout_seconds`** — `number`; optional. Default: `300`. Constraints: `{"exclusiveMinimum": 0}`.
- **`build_timeout_sec`** — `number`; optional. Default: `600`. Constraints: `{"exclusiveMinimum": 0}`.
- **`allow_unsafe_local`** — `boolean`; optional. Default: `false`.

## EvaluationTrack

Versioned rules that make results on one track comparable.

- **`id`** — `string`; required.
- **`version`** — `string`; optional. Default: `"1.0.0"`.
- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`kind`** — `"models" | "agents"`; required.
- **`description`** — `string`; optional. Default: `""`.
- **`attempts`** — `integer`; optional. Default: `1`. Constraints: `{"maximum": 32, "minimum": 1}`.
- **`max_retries`** — `integer`; optional. Default: `0`. Constraints: `{"maximum": 10, "minimum": 0}`.
- **`harnesses`** — `array of string`; optional. Default: `[]`.
- **`instructions`** — `"none" | "any"`; optional. Default: `"any"`.
- **`temperature`** — `number | null`; optional. Default: `null`.
- **`max_tokens`** — `integer | null`; optional. Default: `null`.
- **`tools`** — `string`; optional. Default: `"Environment actions only."`.
- **`max_turns`** — `integer | null`; optional. Default: `null`.
- **`max_seconds`** — `number | null`; optional. Default: `null`.
- **`max_cost_usd`** — `number | null`; optional. Default: `null`.

## ExecutionLimits

Environment execution limits.

- **`max_turns`** — `integer`; optional. Default: `8`. Constraints: `{"maximum": 128, "minimum": 1}`.
- **`max_seconds`** — `number`; optional. Default: `120`. Constraints: `{"exclusiveMinimum": 0}`.
- **`max_cost_usd`** — `number | null`; optional. Default: `null`.

## ExecutionTarget

Execution isolation class.

Allowed values: `"local" | "docker" | "remote"`.


## FileDeclaration

A file emitted or consumed by a package.

- **`path`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`required`** — `boolean`; optional. Default: `true`.
- **`media_type`** — `string`; optional. Default: `"application/octet-stream"`.

## Guardrail

A plain-language Environment rule.

- **`name`** — `string`; optional. Default: `""`.
- **`rule`** — `string`; required. Constraints: `{"minLength": 1}`.

## HarnessCapability

A capability requested by an agent harness.

Allowed values: `"shell" | "file_read" | "file_edit" | "code_execution" | "web_search" | "browser" | "network_fetch" | "mcp" | "subagents" | "persistence"`.


## HarnessDefinition

A declared executable Agent interaction strategy.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`description`** — `string`; optional. Default: `""`.
- **`command`** — `array of string`; required. Constraints: `{"minItems": 1}`.
- **`source`** — `string`; optional. Default: `"."`.
- **`digest`** — `string | null`; optional. Default: `null`.
- **`requirements`** — `array of string`; optional. Default: `[]`.
- **`capabilities`** — `array of HarnessCapability`; optional. Default: `[]`. Constraints: `{"uniqueItems": true}`.
- **`models`** — `array of string`; optional. Default: `["*"]`.
- **`auth`** — `array of "environment" | "api_key" | "oauth" | "none"`; optional. Default: `["environment"]`.
- **`secrets`** — `array of string`; optional. Default: `[]`.
- **`environment`** — `array of string`; optional. Default: `[]`.
- **`healthcheck`** — `array of string | null`; optional. Default: `null`.
- **`outputs`** — `array of FileDeclaration`; optional. Default: `[]`.
- **`artifacts`** — `array of FileDeclaration`; optional. Default: `[]`.
- **`trajectory`** — `string | null`; optional. Default: `null`.
- **`tito`** — `string | null`; optional. Default: `null`.

## HarnessPolicy

Environment ceiling for a Trial's optional Agent harness.

- **`mode`** — `"allow_all" | "allowlist"`; optional. Default: `"allow_all"`.
- **`allowed_harnesses`** — `array of string`; optional. Default: `[]`.
- **`allowed_capabilities`** — `array of HarnessCapability | null`; optional. Default: `null`.
- **`denied_capabilities`** — `array of HarnessCapability`; optional. Default: `[]`. Constraints: `{"uniqueItems": true}`.

## Action

An action owned by an Environment.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`description`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`kind`** — `"command" | "python"`; optional. Default: `"command"`.
- **`command`** — `array of string`; optional. Default: `[]`.
- **`parameters`** — `object`; optional.
- **`observation_schema`** — `object`; optional.
- **`mutates_state`** — `boolean`; optional. Default: `true`.
- **`timeout_seconds`** — `number`; optional. Default: `30`. Constraints: `{"exclusiveMinimum": 0}`.

## NetworkMode

Requested sandbox network policy.

Allowed values: `"public" | "no-network" | "allowlist" | "public" | "no-network" | "allowlist"`.


## ResourceRequirements

Optional compute limits.

- **`cpu`** — `number | null`; optional. Default: `null`.
- **`memory_mb`** — `integer | null`; optional. Default: `null`.
- **`pids`** — `integer | null`; optional. Default: `null`.
- **`disk_mb`** — `integer | null`; optional. Default: `null`.
- **`storage_mb`** — `integer | null`; optional. Default: `null`.

## Rewarder

A named state-transition reward signal scored inside each step.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`description`** — `string`; optional. Default: `""`.
- **`kind`** — `"command" | "python"`; optional. Default: `"command"`.
- **`command`** — `array of string`; optional. Default: `[]`.
- **`implementation_digest`** — `string`; optional. Default: `""`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`timeout_seconds`** — `number`; optional. Default: `30`. Constraints: `{"exclusiveMinimum": 0}`.

## RubricCriterion

One Agent or Human rubric criterion.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`description`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`min_score`** — `number`; optional. Default: `0`.
- **`max_score`** — `number`; optional. Default: `1`.

## RuntimeVariable

A launch-time variable declaration. Values are supplied to Job, never saved here.

- **`name`** — `string`; required. Constraints: `{"pattern": "^[A-Z_][A-Z0-9_]*$"}`.
- **`description`** — `string`; optional. Default: `""`.
- **`required`** — `boolean`; optional. Default: `true`.
- **`secret`** — `boolean`; optional. Default: `false`.
- **`format`** — `"text" | "url" | "integer" | "json"`; optional. Default: `"text"`.

## Secret

A named credential supplied when a Job runs, with an explicit execution target.

- **`name`** — `string`; required. Constraints: `{"pattern": "^[A-Z_][A-Z0-9_]*$"}`.
- **`required`** — `boolean`; optional. Default: `true`.
- **`target`** — `"environment" | "harness" | "verifier"`; optional. Default: `"environment"`.
- **`description`** — `string`; optional. Default: `""`.

## VerifierRuntime

Machine for a verifier that needs its own sandbox.

- **`provider`** — `string`; optional. Default: `"docker"`. Constraints: `{"minLength": 1}`.
- **`image`** — `string | null`; optional. Default: `null`.
- **`network`** — `NetworkMode`; optional. Default: `"public"`.
- **`network_allowlist`** — `array of string`; optional. Default: `[]`.
- **`resources`** — `ResourceRequirements`; optional.
- **`timeout_seconds`** — `number`; optional. Default: `60`. Constraints: `{"exclusiveMinimum": 0}`.
