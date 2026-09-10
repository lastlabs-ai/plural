# Manifest field reference

All v1 models are frozen, reject unknown fields, and use `schema_version: "1"`
where present. Generated JSON Schemas are the exact validation authority.

## `PackageSource`

- `kind`: `local`, `archive`, or `oci`.
- `uri`: non-empty path/URL/reference.
- `digest`: optional only for local; otherwise `sha256:` plus 64 lowercase hex.
- `trusted`: deprecated migration field; never bypasses integrity/unsafe checks.
- `unsafe_local`: explicit unsigned local opt-in; invalid for remote kinds.

## `HarnessManifest` and `HarnessPackage`

- `schema_version`, `name`, `version`, `description`.
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
- `HarnessPackage.manifest` and `.source`: complete package. `content_hash` and
  `package_id` are derived.

`HarnessBinding` contains `name`, `revision`, and required digest.

## `EnvironmentManifest`

- `schema_version`, `name`, `revision`, `description`.
- `instructions`: authoritative harness instructions.
- `context`: arbitrary public context.
- `actions`: unique `NativeAction` values: `name`, `description`, `kind`,
  argv `command` when `kind=command`, `parameters`, `observation_schema`,
  `mutates_state`, `timeout_seconds`.
- `observation_schema`, `state_schema`.
- `guardrails`, `resources`.
- `runtime`: `EnvironmentRuntime` — image/build, network, resources, targets,
  persistence, compose, `allow_unsafe_local`.
- `harness_policy`: `allow_all` or `allowlist`, denied/allowed capabilities.
- `limits`: `max_turns` (1–128), positive `max_seconds`, optional positive
  `max_cost_usd`.
- `tasks`: unique `TaskDefinition` values with `task_id`, public `input`,
  evaluator-only `expected`/`verifier_input`, and public `metadata`.
- `verifier`: optional `VerifierManifest`.
- `source`: optional Environment package source. Execution currently stages
  local sources only.

`VerifierManifest` has argv `command`, optional image, positive timeout,
safe `required_artifacts`, safe `result_path`, and `evidence_required`.
Verifier JSON accepts finite optional `reward`, named finite `scores`, and
`evidence` strings.

## `BenchmarkDefinition`

- `schema_version`, `name`, `description`, `primary_metric`.
- `environment`: exact `EnvironmentIdentity` (`name`, `revision`, `digest`).
- `task_ids`: non-empty, unique, ordered selection owned by that Environment.

`BenchmarkSpec` is an alias. This v1 model is distinct from the compatible
legacy `plural.Benchmark` runner.

## `AgentTemplate`

- `schema_version`, `name`, `model`.
- `routing`: optional `provider`, ordered `fallback_models`, `temperature`, and
  positive `max_tokens`.
- `environment`: exact Environment identity.
- `harness`: optional binding. `None` is the native path.
- `stamp`: required when `harness` is set.
- `harness_package`: optional executable package; must match the binding.
- `secret_names`: granted subset of package-declared names.

Derived `content_hash` and `template_id` include the complete immutable config.

## `JobFile` and `JobSpec`

Human `job.yaml` uses `JobFile`: `schema_version`, paths `environment`,
`benchmark`, and non-empty `agents`; positive `n_attempts`, `concurrency`, and
`per_agent_concurrency`; plus `runtime` and `retry`. Paths resolve relative to
the Job file.

Resolved `JobSpec` embeds complete `environment`, `benchmark`, and `agents`
instead of paths, then carries the same scheduling/runtime/retry fields. It
validates exact Environment identity, task ownership, Agent identities, allowed
Harness bindings, and unique Agents.

`RetryPolicy` fields are non-negative `max_retries` and initial/max backoff,
multiplier at least 1, and `retryable_codes`. Defaults retry rate limits,
provider unavailability, timeout, and runtime unavailability.

`RuntimeSpec` fields:

- `provider`; requested `capabilities`;
- mutually exclusive `image`, `snapshot`, `declarative_image`;
- Docker `build_context` and optional `dockerfile`;
- `resources`: optional positive `cpu`, `memory_mb`, `pids`, `disk_mb`;
- `network`: `none`, `restricted`, or `full`; an allowlist is valid only for
  `restricted`;
- positive `timeout_seconds`, `read_only_root`, and `unsafe_local`.

`DeclarativeImage` has `base`, `pip_packages`, process `environment`, and
optional `workdir`.

## Planning, Trials, and receipts

`TrialSpec` contains `job_id`, `agent_id`, `agent_name`, `task_id`, one-based
`attempt`, exact Environment/Harness bindings, and Runtime. `trial_id` is
derived independently of retries.

`JobLock` records job/spec IDs; Environment, Benchmark, task-set, Agent and
Harness hashes; optional Environment source digest; execution limits;
instructions/commands/policy hashes; and Runtime.

`TrialReceipt` records Trial/Job/retry/attempt identity; Environment, Benchmark,
Agent, Harness, Runtime, image, task, trace, artifact and verifier hashes;
effective capabilities/policy; source-receipt link for regrade; UTC timestamps;
timings; Environment source/instruction/command/limit/policy provenance; and
`trust`, currently only `self_reported`.

`TrialResult` is `succeeded`, `failed`, or `cancelled`, with receipt, optional
reward/scores/trace, and stable error details. Failure requires `error_code`;
success forbids one. `JobResult` contains `job_id`, `plan_hash`, and ordered
Trial results.
