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
- [AgentCredential](#agentcredential)
- [AppAction](#appaction)
- [AppDefinition](#appdefinition)
- [BenchmarkCategory](#benchmarkcategory)
- [BenchmarkScoring](#benchmarkscoring)
- [DeclarativeImage](#declarativeimage)
- [Resource](#resource)
- [Runtime](#runtime)
- [EvaluationTrack](#evaluationtrack)
- [ExecutionLimits](#executionlimits)
- [ExecutionTarget](#executiontarget)
- [ExternalAgent](#externalagent)
- [FileDeclaration](#filedeclaration)
- [Guardrail](#guardrail)
- [HarnessCapability](#harnesscapability)
- [HarnessDefinition](#harnessdefinition)
- [HarnessPolicy](#harnesspolicy)
- [NetworkMode](#networkmode)
- [Party](#party)
- [ResourceRequirements](#resourcerequirements)
- [RubricCriterion](#rubriccriterion)
- [RuntimePackages](#runtimepackages)
- [RuntimeVariable](#runtimevariable)
- [SandboxCapability](#sandboxcapability)
- [Secret](#secret)
- [VerifierRuntime](#verifierruntime)

## Environment

Schema-v2 Environment: Apps composed with one Runtime and one set of limits.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`description`** — `string`; optional. Default: `""`.
- **`overview`** — `string`; optional. Default: `""`.
- **`readme`** — `string`; optional. Default: `""`.
- **`apps`** — `array of AppDefinition`; optional. Default: `[]`.
- **`python`** — `string | null`; optional. Default: `null`.
- **`guardrails`** — `array of Guardrail`; optional. Default: `[]`.
- **`resources`** — `array of Resource`; optional. Default: `[]`.
- **`runtime`** — `Runtime`; optional.
- **`harness_policy`** — `HarnessPolicy`; optional.
- **`limits`** — `ExecutionLimits`; optional.
- **`party`** — `Party | null`; optional. Default: `null`. How many Agents share each episode, for a game such as poker. Leave it unset for an Environment one Agent works in alone.
- **`metadata`** — `object`; optional.

## Harness

Base class for an Agent interaction loop.

- **`config`** — `object`; optional.

## Task

One versioned unit of work in a Python-authored Environment.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`title`** — `string | null`; optional. Default: `null`. Display name in the hosted project. Defaults to name.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`instructions`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`goals`** — `array of string`; optional. Default: `[]`.
- **`info`** — `JSON value`; optional. Default: `null`.
- **`metadata`** — `object`; optional.
- **`environment`** — `JSON value`; required.
- **`verifiers`** — `array of DeterministicVerifier | AgentVerifier | HumanVerifier`; required. Constraints: `{"minItems": 1}`.
- **`resources`** — `array of Resource`; optional. Default: `[]`.
- **`initial_state`** — `object`; optional.
- **`seat_instructions`** — `object`; optional.
- **`expected`** — `JSON value`; optional. Default: `null`.

## DeterministicVerifier

Code that verifies an episode: it scores the end, rewards actions, or both.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`info`** — `JSON value`; optional. Default: `null`.
- **`criteria`** — `array of RubricCriterion`; optional. Default: `[]`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`metadata`** — `object`; optional.
- **`secrets`** — `array of Secret`; optional. Default: `[]`.
- **`kind`** — `"deterministic"`; optional. Default: `"deterministic"`.
- **`check`** — `JSON value`; optional. Default: `null`.
- **`reward`** — `JSON value`; optional. Default: `null`.
- **`hindsight`** — `JSON value`; optional. Default: `null`.
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
- **`secrets`** — `array of Secret`; optional. Default: `[]`.
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
- **`secrets`** — `array of Secret`; optional. Default: `[]`.
- **`kind`** — `"human"`; optional. Default: `"human"`.
- **`instructions`** — `string`; optional. Default: `""`.

## Agent

A catalog-backed model and its optional execution harness.

- **`model`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`name`** — `string`; optional. Default: `""`.
- **`title`** — `string | null`; optional. Default: `null`. Display name in the hosted project. Defaults to name.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`provider`** — `string | null`; optional. Default: `null`.
- **`instructions`** — `string`; optional. Default: `""`.
- **`fallback_models`** — `array of string`; optional. Default: `[]`.
- **`temperature`** — `number | null`; optional. Default: `null`.
- **`max_tokens`** — `integer | null`; optional. Default: `null`.
- **`harness`** — `HarnessDefinition | Harness | string | null`; optional. Default: `null`.
- **`harness_config`** — `object`; optional. Options for a built-in Harness, such as reasoning_effort.
- **`auth`** — `"environment" | "api_key" | "oauth" | "none"`; optional. Default: `"environment"`. How the Harness authenticates to the model; none when it calls no model.
- **`secrets`** — `array of string`; optional. Default: `[]`. Names of the Harness's declared secrets this Agent grants it.
- **`endpoint`** — `string | null`; optional. Default: `null`.
- **`endpoint_key`** — `string | null`; optional. Default: `null`.
- **`external`** — `ExternalAgent | null`; optional. Default: `null`.
- **`credentials`** — `object`; optional.
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
- **`title`** — `string | null`; optional. Default: `null`. Display name in the hosted project. Defaults to name.
- **`version`** — `string`; required.
- **`tasks`** — `array of Task`; required. Constraints: `{"minItems": 1}`.
- **`primary_metric`** — `"score"`; optional. Default: `"score"`.
- **`description`** — `string`; optional. Default: `""`.
- **`metadata`** — `object`; optional.

## AgentCredential

A credential this Agent supplies to the Apps it works with.

- **`scopes`** — `array of string`; optional. Default: `[]`.
- **`description`** — `string`; optional. Default: `""`.

## AppAction

One move an App offers the Agent.

- **`name`** — `string`; required. Constraints: `{"maxLength": 128, "minLength": 1}`.
- **`description`** — `string`; optional. Default: `""`.
- **`parameters`** — `object`; optional.
- **`mutates_state`** — `boolean`; optional. Default: `true`.
- **`timeout_seconds`** — `number`; optional. Default: `30`. Constraints: `{"exclusiveMinimum": 0}`.
- **`binding`** — `object`; optional.

## AppDefinition

One App inside an Environment.

- **`name`** — `string`; required.
- **`kind`** — `"python" | "mcp" | "openapi" | "replay"`; optional. Default: `"python"`.
- **`description`** — `string`; optional. Default: `""`.
- **`python`** — `string | null`; optional. Default: `null`.
- **`config`** — `object`; optional.
- **`actions`** — `array of AppAction`; optional. Default: `[]`.
- **`secrets`** — `array of Secret`; optional. Default: `[]`.
- **`credentials`** — `array of Secret`; optional. Default: `[]`.
- **`state_schema`** — `object`; optional.
- **`has_reset`** — `boolean`; optional. Default: `false`.
- **`has_snapshot`** — `boolean`; optional. Default: `false`.
- **`control`** — `"owned" | "sandboxed" | "live" | "replayed"`; optional. Default: `"owned"`.

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
- **`harness_timeout`** — `"infrastructure_error" | "agent_failure"`; optional. Default: `"infrastructure_error"`.
- **`min_tasks_for_interval`** — `integer`; optional. Default: `5`. Constraints: `{"minimum": 2}`.

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
- **`delivery`** — `"descriptor" | "source" | "inline" | "resolver" | "blob"`; optional. Default: `"descriptor"`.
- **`content`** — `string | null`; optional. Default: `null`.
- **`resolver`** — `string | null`; optional. Default: `null`.

## Runtime

Where an Environment runs: Docker, a trusted local process, or a remote sandbox.

- **`provider`** — `string`; optional. Default: `"docker"`. Constraints: `{"minLength": 1}`.
- **`ref`** — `string | null`; optional. Default: `null`. Slug of the project Runtime this configuration was copied from. The machine fields hold that Runtime's settings as of the copy; credentials come from the project Runtime when a Job starts.
- **`placement`** — `object`; optional.
- **`variables`** — `array of RuntimeVariable`; optional. Default: `[]`.
- **`image`** — `string | null`; optional. Default: `null`.
- **`snapshot`** — `string | null`; optional. Default: `null`.
- **`declarative_image`** — `DeclarativeImage | null`; optional. Default: `null`.
- **`build_context`** — `string | null`; optional. Default: `null`.
- **`dockerfile`** — `string | null`; optional. Default: `null`.
- **`network`** — `NetworkMode`; optional. Default: `"public"`.
- **`allowed_hosts`** — `array of string`; optional. Default: `[]`. Hosts the Runtime may reach when network is 'allowlist'.
- **`compute`** — `ResourceRequirements`; optional. CPU, memory, storage, and process limits for the Runtime.
- **`packages`** — `RuntimePackages`; optional. Packages installed in the Runtime before an episode. In environment.yaml, list Python ones under python_packages. On the local Runtime they must already be installed.
- **`read_only_root`** — `boolean`; optional. Default: `false`.
- **`targets`** — `array of ExecutionTarget`; optional. Constraints: `{"uniqueItems": true}`.
- **`persistent`** — `boolean`; optional. Default: `false`.
- **`compose`** — `boolean`; optional. Default: `false`.
- **`extra_capabilities`** — `array of SandboxCapability`; optional. Default: `[]`. Constraints: `{"uniqueItems": true}`.
- **`timeout_seconds`** — `number`; optional. Default: `900`. Constraints: `{"exclusiveMinimum": 0}`.
- **`build_timeout_seconds`** — `number`; optional. Default: `600`. Constraints: `{"exclusiveMinimum": 0}`.
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

How long one episode may run.

- **`max_turns`** — `integer | null`; optional. Default: `null`. Turns the Agent may take. Null, the default, means no cap. Set any positive number to stop the run after that many actions.
- **`max_seconds`** — `number`; optional. Default: `600`. Constraints: `{"exclusiveMinimum": 0}`. Seconds the episode may run. The default is 600, ten minutes.
- **`max_cost_usd`** — `number | null`; optional. Default: `null`. Optional spending cap, in USD. Unset means no cost cap.

## ExecutionTarget

Execution isolation class.

Allowed values: `"local" | "docker" | "remote"`.


## ExternalAgent

An agent that already runs as a service of its own.

- **`url`** — `string`; required.
- **`signing_key`** — `string`; required.
- **`version`** — `string`; optional. Default: `""`.
- **`ca_bundle`** — `string | null`; optional. Default: `null`.

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
- **`env_vars`** — `array of string`; optional. Default: `[]`. Names of environment variables passed through to the Harness process.
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

## NetworkMode

Requested sandbox network policy.

Allowed values: `"public" | "no-network" | "allowlist" | "public" | "no-network" | "allowlist"`.


## Party

How many Agents may share one episode of the Environment, such as 2 to 8 at poker.

- **`min`** — `integer`; optional. Default: `2`. Constraints: `{"maximum": 100, "minimum": 2}`.
- **`max`** — `integer`; optional. Default: `2`. Constraints: `{"maximum": 100, "minimum": 2}`.
- **`isolation`** — `"isolated" | "shared"`; optional. Default: `"isolated"`. ``isolated``: each seat's Harness runs as its own OS user, and the Apps are the only thing the seats share; needs Docker or Daytona. ``shared``: every seat runs as one user and can read and write the others' files and the Environment's, for a team that works on the same files, or to try a party on the local Runtime. A shared seat could also act for another seat.

## ResourceRequirements

Optional compute limits.

- **`cpu`** — `number | null`; optional. Default: `null`.
- **`memory_mb`** — `integer | null`; optional. Default: `null`.
- **`pids`** — `integer | null`; optional. Default: `null`.
- **`disk_mb`** — `integer | null`; optional. Default: `null`.
- **`storage_mb`** — `integer | null`; optional. Default: `null`.

## RubricCriterion

One Agent or Human rubric criterion.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`description`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`min_score`** — `number`; optional. Default: `0`.
- **`max_score`** — `number`; optional. Default: `1`.

## RuntimePackages

Packages installed in the Runtime before an episode, by package manager.

- **`python`** — `array of string`; optional. Default: `[]`.

## RuntimeVariable

A launch-time variable declaration. Values are supplied to Job, never saved here.

- **`name`** — `string`; required. Constraints: `{"pattern": "^[A-Z_][A-Z0-9_]*$"}`.
- **`description`** — `string`; optional. Default: `""`.
- **`required`** — `boolean`; optional. Default: `true`.
- **`secret`** — `boolean`; optional. Default: `false`.
- **`format`** — `"text" | "url" | "integer" | "json"`; optional. Default: `"text"`.

## SandboxCapability

Individual controls a provider can enforce.

Allowed values: `"image" | "build" | "resources" | "network_none" | "network_allowlist" | "upload" | "download" | "timeout" | "cancel" | "persistence" | "compose" | "read_only_root" | "working_directory" | "environment" | "log_capture"`.


## Secret

A named value an App needs, which it never stores itself.

- **`name`** — `string`; required. Constraints: `{"pattern": "^[A-Z_][A-Z0-9_]*$"}`.
- **`required`** — `boolean`; optional. Default: `true`.
- **`description`** — `string`; optional. Default: `""`.
- **`scopes`** — `array of string`; optional. Default: `[]`.

## VerifierRuntime

Machine for a verifier that needs its own sandbox.

- **`provider`** — `string`; optional. Default: `"docker"`. Constraints: `{"minLength": 1}`.
- **`image`** — `string | null`; optional. Default: `null`.
- **`network`** — `NetworkMode`; optional. Default: `"public"`.
- **`allowed_hosts`** — `array of string`; optional. Default: `[]`.
- **`compute`** — `ResourceRequirements`; optional.
- **`timeout_seconds`** — `number`; optional. Default: `60`. Constraints: `{"exclusiveMinimum": 0}`.
