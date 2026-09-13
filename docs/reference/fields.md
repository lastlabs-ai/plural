---
route: /docs/reference/fields
title: "Field catalog"
order: 205
description: "Every authoring and execution field, generated from the current Plural models."
audience: all
nav: false
---
# Field catalog

Use this catalog after the conceptual guides. It is generated from the executable Pydantic models, including nested types. Required fields have no usable default. Custom cross-field validators also apply; the [definition guide](definitions.md) explains the important relationships.

These are the public SDK fields used by Python and YAML. JSON Schema alone does not describe every runtime capability check or side effect.

[Download the complete schemas](../assets/project-schemas.json).

## Find a contract

- [Environment](#environment)
- [Task](#task)
- [DeterministicVerifier](#deterministicverifier)
- [AgentVerifier](#agentverifier)
- [HumanVerifier](#humanverifier)
- [Agent](#agent)
- [Benchmark](#benchmark)
- [Capability](#capability)
- [DeclarativeImage](#declarativeimage)
- [EnvironmentResource](#environmentresource)
- [EnvironmentRuntime](#environmentruntime)
- [EvidenceContract](#evidencecontract)
- [ExecutionLimits](#executionlimits)
- [ExecutionTarget](#executiontarget)
- [FileDeclaration](#filedeclaration)
- [Guardrail](#guardrail)
- [HarnessBinding](#harnessbinding)
- [HarnessCapability](#harnesscapability)
- [HarnessDefinition](#harnessdefinition)
- [HarnessPackage](#harnesspackage)
- [HarnessPolicy](#harnesspolicy)
- [NativeAction](#nativeaction)
- [NetworkMode](#networkmode)
- [PackageSource](#packagesource)
- [ResourceRequirements](#resourcerequirements)
- [RewarderDefinition](#rewarderdefinition)
- [RubricCriterion](#rubriccriterion)
- [SecretReference](#secretreference)
- [VerifierRuntime](#verifierruntime)

## Environment

Schema-v2 Environment. Tasks, Verifiers, and mode are intentionally absent.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`description`** — `string`; optional. Default: `""`.
- **`overview`** — `string`; optional. Default: `""`.
- **`readme`** — `string`; optional. Default: `""`.
- **`actions`** — `array of NativeAction`; optional. Default: `[]`.
- **`reset_command`** — `array of string`; optional. Default: `[]`.
- **`observation_schema`** — `object`; optional.
- **`state_schema`** — `object`; optional.
- **`rewarders`** — `array of RewarderDefinition`; optional. Default: `[]`.
- **`guardrails`** — `array of Guardrail`; optional. Default: `[]`.
- **`resources`** — `array of EnvironmentResource`; optional. Default: `[]`.
- **`runtime`** — `EnvironmentRuntime`; optional.
- **`secrets`** — `array of SecretReference`; optional. Default: `[]`.
- **`harness_policy`** — `HarnessPolicy`; optional.
- **`limits`** — `ExecutionLimits`; optional.
- **`metadata`** — `object`; optional.
- **`source`** — `PackageSource | null`; optional. Default: `null`.

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
- **`resources`** — `array of EnvironmentResource`; optional. Default: `[]`.
- **`initial_state`** — `object`; optional.
- **`reset_options`** — `object`; optional.

## DeterministicVerifier

Deterministic command verifier.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`info`** — `JSON value`; optional. Default: `null`.
- **`criteria`** — `array of RubricCriterion`; optional. Default: `[]`.
- **`evidence`** — `EvidenceContract`; optional.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`metadata`** — `object`; optional.
- **`kind`** — `"deterministic"`; optional. Default: `"deterministic"`.
- **`check`** — `array of string`; required. Constraints: `{"minItems": 1}`.
- **`runtime`** — `VerifierRuntime`; optional.
- **`result_path`** — `string`; optional. Default: `"verifier-result.json"`.
- **`evidence_required`** — `boolean`; optional. Default: `true`.

## AgentVerifier

Model-judge verifier with its own runtime and connectivity policy.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; optional. Default: `"0.1.0"`.
- **`info`** — `JSON value`; optional. Default: `null`.
- **`criteria`** — `array of RubricCriterion`; required. Constraints: `{"minItems": 1}`.
- **`evidence`** — `EvidenceContract`; optional.
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
- **`evidence`** — `EvidenceContract`; optional.
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
- **`harness`** — `HarnessPackage | null`; optional. Default: `null`.
- **`auth_mode`** — `"environment" | "api_key" | "oauth" | "none"`; optional. Default: `"environment"`.
- **`secret_names`** — `array of string`; optional. Default: `[]`.
- **`metadata`** — `object`; optional.

## Benchmark

A semantic version that pins an ordered set of Tasks.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`version`** — `string`; required.
- **`tasks`** — `array of Task`; required. Constraints: `{"minItems": 1}`.
- **`primary_metric`** — `string`; optional. Default: `"reward"`.
- **`description`** — `string`; optional. Default: `""`.
- **`metadata`** — `object`; optional.

## Capability

Individual controls a provider can enforce.

Allowed values: `"image" | "build" | "resources" | "network_none" | "network_allowlist" | "upload" | "download" | "timeout" | "cancel" | "persistence" | "compose" | "read_only_root" | "working_directory" | "environment" | "log_capture"`.


## DeclarativeImage

Portable subset of Daytona's declarative image builder.

- **`base`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`pip_packages`** — `array of string`; optional. Default: `[]`.
- **`environment`** — `object`; optional.
- **`workdir`** — `string | null`; optional. Default: `null`.

## EnvironmentResource

Data or application supplied by an Environment.

- **`kind`** — `"data" | "application" | "file"`; required.
- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`path`** — `string | null`; optional. Default: `null`.
- **`uri`** — `string | null`; optional. Default: `null`.
- **`digest`** — `string | null`; optional. Default: `null`.
- **`content_type`** — `string`; optional. Default: `""`.
- **`config`** — `object`; optional.

## EnvironmentRuntime

Immutable Environment-owned provider, placement, network, and compute.

- **`provider`** — `string`; optional. Default: `"docker"`. Constraints: `{"minLength": 1}`.
- **`placement`** — `object`; optional.
- **`image`** — `string | null`; optional. Default: `null`.
- **`snapshot`** — `string | null`; optional. Default: `null`.
- **`declarative_image`** — `DeclarativeImage | null`; optional. Default: `null`.
- **`build_context`** — `string | null`; optional. Default: `null`.
- **`dockerfile`** — `string | null`; optional. Default: `null`.
- **`network`** — `NetworkMode`; optional. Default: `"none"`.
- **`network_allowlist`** — `array of string`; optional. Default: `[]`.
- **`resources`** — `ResourceRequirements`; optional.
- **`read_only_root`** — `boolean`; optional. Default: `false`.
- **`targets`** — `array of ExecutionTarget`; optional. Constraints: `{"uniqueItems": true}`.
- **`persistent`** — `boolean`; optional. Default: `false`.
- **`compose`** — `boolean`; optional. Default: `false`.
- **`extra_capabilities`** — `array of Capability`; optional. Default: `[]`. Constraints: `{"uniqueItems": true}`.
- **`timeout_seconds`** — `number`; optional. Default: `300`. Constraints: `{"exclusiveMinimum": 0}`.
- **`allow_unsafe_local`** — `boolean`; optional. Default: `false`.

## EvidenceContract

What a Verifier needs from the Environment and Trial artifacts.

- **`artifacts`** — `array of string`; optional. Default: `[]`.
- **`state_paths`** — `array of string`; optional. Default: `[]`.
- **`observation_paths`** — `array of string`; optional. Default: `[]`.
- **`include_hidden_state`** — `boolean`; optional. Default: `false`.

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

## HarnessBinding

Exact harness revision.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`revision`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`digest`** — `string`; required.

## HarnessCapability

A capability requested by an agent harness.

Allowed values: `"shell" | "file_read" | "file_edit" | "code_execution" | "web_search" | "browser" | "network_fetch" | "mcp" | "subagents" | "persistence"`.


## HarnessDefinition

Versioned executable harness contract.

- **`schema_version`** — `"2"`; optional. Default: `"2"`.
- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`revision`** — `string`; optional. Default: `"0.1.0"`. Constraints: `{"minLength": 1}`.
- **`description`** — `string`; optional. Default: `""`.
- **`protocol`** — `"plural-harness-v1" | "acp"`; optional. Default: `"plural-harness-v1"`.
- **`protocol_adapter`** — `"acp-client-v1" | null`; optional. Default: `null`.
- **`implementation`** — `"declared" | "runnable"`; optional. Default: `"declared"`.
- **`command`** — `array of string`; optional. Default: `[]`.
- **`requirements`** — `array of string`; optional. Default: `[]`.
- **`capabilities`** — `array of HarnessCapability`; optional. Default: `[]`. Constraints: `{"uniqueItems": true}`.
- **`supported_models`** — `array of string`; optional. Default: `["*"]`.
- **`auth_modes`** — `array of "environment" | "api_key" | "oauth" | "none"`; optional. Default: `["environment"]`.
- **`secret_names`** — `array of string`; optional. Default: `[]`.
- **`environment_names`** — `array of string`; optional. Default: `[]`.
- **`healthcheck`** — `array of string | null`; optional. Default: `null`.
- **`trajectory_path`** — `string | null`; optional. Default: `null`.
- **`outputs`** — `array of FileDeclaration`; optional. Default: `[]`.
- **`artifacts`** — `array of FileDeclaration`; optional. Default: `[]`.
- **`supports_tito`** — `boolean`; optional. Default: `false`.
- **`tito_path`** — `string | null`; optional. Default: `null`.

## HarnessPackage

Content-addressed harness definition and source.

- **`definition`** — `HarnessDefinition`; required.
- **`source`** — `PackageSource`; required.

## HarnessPolicy

Environment ceiling for a Trial's optional Agent harness.

- **`mode`** — `"allow_all" | "allowlist"`; optional. Default: `"allow_all"`.
- **`allowed_harnesses`** — `array of HarnessBinding`; optional. Default: `[]`.
- **`allowed_capabilities`** — `array of HarnessCapability | null`; optional. Default: `null`.
- **`denied_capabilities`** — `array of HarnessCapability`; optional. Default: `[]`. Constraints: `{"uniqueItems": true}`.

## NativeAction

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

Allowed values: `"none" | "restricted" | "full"`.


## PackageSource

Immutable package source.

- **`kind`** — `"local" | "oci" | "archive"`; required.
- **`uri`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`digest`** — `string | null`; optional. Default: `null`.
- **`trusted`** — `boolean`; optional. Default: `false`.
- **`unsafe_local`** — `boolean`; optional. Default: `false`.

## ResourceRequirements

Optional compute limits.

- **`cpu`** — `number | null`; optional. Default: `null`.
- **`memory_mb`** — `integer | null`; optional. Default: `null`.
- **`pids`** — `integer | null`; optional. Default: `null`.
- **`disk_mb`** — `integer | null`; optional. Default: `null`.

## RewarderDefinition

A train-only state-transition rewarder.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`description`** — `string`; optional. Default: `""`.
- **`kind`** — `"command" | "python"`; optional. Default: `"command"`.
- **`command`** — `array of string`; optional. Default: `[]`.
- **`implementation_digest`** — `string`; optional. Default: `""`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`timeout_seconds`** — `number`; optional. Default: `30`. Constraints: `{"exclusiveMinimum": 0}`.

## RubricCriterion

One deterministic human or agent rubric criterion.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`description`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`weight`** — `number`; optional. Default: `1`. Constraints: `{"exclusiveMinimum": 0}`.
- **`min_score`** — `number`; optional. Default: `0`.
- **`max_score`** — `number`; optional. Default: `1`.

## SecretReference

A named secret injected by a runtime without embedding its value.

- **`name`** — `string`; required. Constraints: `{"minLength": 1}`.
- **`required`** — `boolean`; optional. Default: `true`.
- **`target`** — `"environment" | "harness" | "verifier"`; optional. Default: `"environment"`.

## VerifierRuntime

Verifier-owned runtime and connectivity, independent of the Environment.

- **`provider`** — `string`; optional. Default: `"docker"`. Constraints: `{"minLength": 1}`.
- **`image`** — `string | null`; optional. Default: `null`.
- **`network`** — `NetworkMode`; optional. Default: `"none"`.
- **`network_allowlist`** — `array of string`; optional. Default: `[]`.
- **`resources`** — `ResourceRequirements`; optional.
- **`timeout_seconds`** — `number`; optional. Default: `60`. Constraints: `{"exclusiveMinimum": 0}`.
