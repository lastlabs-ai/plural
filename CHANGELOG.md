# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.10.0] - 2026-09-10

### Added

- Schema-v2 `Environment`, `Task`, deterministic/agent/human `Verifier`,
  `AgentDefinition`, cross-environment `BenchmarkDefinition`, `Job`, `Trial`,
  and retrying `TrialExecution` contracts with immutable revision hashes.
- Environment-directed bounded execution, append-only live progress events,
  human-review waits, train-only Rewarders, and artifact-backed exact TITO
  records.
- Canonical parent/revision publishing APIs and CLI workflows for authoring,
  validating, running, watching, reviewing, and publishing the complete graph.

### Changed

- Environments now own actions, hidden state and observations, resources,
  runtime/network/secrets policy, and train-only Rewarders. Tasks inject one
  Environment revision and weighted Verifier revisions.
- Jobs select either a Task or Benchmark and expand Agents × Tasks × attempts;
  Environment placement remains authoritative while Job concurrency and retry
  settings control scheduling.
- `plural run` now validates and synchronizes the complete canonical revision
  graph, submits a hosted Job with stable idempotency, and watches hosted events
  by default. `--offline` and `--private` explicitly retain local execution.
- Trace schema v3 records exact provenance, run mode, verifier/review outcomes,
  reward events, and artifact references.

### Removed

- Environment-owned tasks/final scorers, `AgentTemplate`/`AgentInstance`,
  `TaskData`/`TaskDataset`, the legacy Benchmark runner, and parallel v1/v2
  execution paths.

## [0.9.0] - 2026-09-09

### Changed

- Foundation rewrite: environments own native actions and runtime; harnesses
  are stamped and capability-restricted; agents split into templates and
  instances; traces are schema 2.0.0 (`Turn` / `ActionStep`).
- `@tool` is `@action`. `AgentSpec` and `EnvironmentCommand` are deleted.
- Secure defaults: `network=none`, local excluded. Unsatisfiable requirements
  fail in `resolve_effective_policy()` before launch.
- Declared harnesses (`hermes`, `claude-code`, `codex`, `cursor`) cannot run.
  The native runner (`native.chat.v1`, `native.actions.v1`) is the only
  runnable executor.

### Removed

- Backward-compatible aliases, `_migrate_legacy_trace`, and v1 trace schema.

## [0.8.0] - 2026-09-09

### Added

- `hidden()` marks a `State` field as agent-invisible. The flag is stored on
  the JSON Schema as `x-plural-hidden` so studio can show visibility.
- Alpha v1 package domain for immutable Environment, Harness, Agent, Benchmark,
  Job, Trial, lock, receipt, verifier, artifact, retry, and runtime contracts.
- `plural` Typer CLI for device auth/context, package scaffolding and
  validation, deterministic dry runs, local job persistence/control, and
  runtime inspection. Job registration and result upload are opt-in
  (`--sync` / `plural job upload`). Organization and project listing are
  not implemented yet.
- Provider-neutral Harness JSONL protocol, built-in chat/tool/code profiles,
  narrow ACP v1 and separately installed Claude Code/Codex/Hermes adapters,
  deterministic archive retrieval, and exact artifact contracts.
- Local development, Docker, Daytona, and entry-point sandbox providers with
  capability preflight, cancellation, cleanup, isolated verifier regrade, and
  self-reported execution receipts.
- Generated package/CLI JSON Schemas, generated CLI command reference, drift
  checks, security/operations/migration documentation, and offline execution
  examples.

### Changed

- `Observation` is the per-action view returned by `reset` / `step`.
  `State` is the persistent environment object; durable structures live there.
- `Benchmark` is a reusable definition (`name`, `primary_metric`). Each
  `.run()` is a report attached as a hosted run. Win rates compare the
  chosen metric. Pushing a report uploads episode traces with `run_group_id`.
- Legacy `Benchmark.repeats` and `TaskDataset` remain compatible. New
  `JobSpec.n_attempts` names independent Trial repetitions; execution retries
  are tracked separately without changing Trial identity.

## [0.7.4] - 2026-09-02

### Added

- Environment `description`, `readme`, `guardrails`, and `skills` with empty
  defaults. Observation and state JSON schemas come from the generic models.
- Hosted environment manifests now include those schemas, guardrails, skills,
  overridden hooks, and the default context policy.

## [0.7.3] - 2026-09-02

### Added

- `Client.create(x)` and `Client.update(x)` for environments, traces, and
  benchmarks. Environments, agents, and benchmarks are addressed by
  project-unique slug; traces stay id-based.
- `env.create(client)` and `env.update(client)` aliases.

### Changed

- Duplicate environment, agent, or benchmark slugs now conflict instead of
  being uniquified with a suffix.
- `client.push` / `env.push` upsert by slug instead of creating a new row
  when the name already exists.

## [0.7.2] - 2026-09-02

### Added

- `Client.push(x)` syncs a local `Environment`, `Trace`, `Benchmark` (after
  `run()`), or `Report` to the hosted project. Agents are created with
  `client.agents.create(...)` and are not pushable.
- `env.push(client)` remains as an alias for `client.push(env)`.

## [0.7.1] - 2026-09-02

### Added

- Studio APIs on `Client` for hosted environments, agents, benchmarks, and
  traces. Account API keys require `project=` or `PLURAL_PROJECT`; project
  keys already know the project.
- `Environment.push(client)` creates or updates a local environment on a
  Plural project.
- `client.agents.get(...).invoke(prompt)` reads a hosted agent and calls it
  through the gateway.

## [0.6.1] - 2026-08-26

### Added

- `Client.is_authenticated()` probes each configured provider and reports
  whether credentials are accepted.

### Changed

- The high-level client is now `Client`. Import it with
  `from plural import Client`. `Plural` remains as a backward-compatible alias.

## [0.6.0] - 2026-08-25

### Changed

- Rename the library, GitHub repository, and PyPI project from `enroute` to
  `plural`. The project now lives at `lastlabs-ai/plural`. The client is
  `Plural`, errors are `PluralError`, environment policies are `PluralPolicy`,
  and the default env var / trace directory are `PLURAL_API_KEY` and `.plural`.
  `ENROUTE_API_KEY` is still read as a fallback.

## [0.5.1] - 2026-08-24

### Fixed

- Refresh model catalog list prices for DeepSeek V4 Flash, Gemini 3.7 Flash,
  GPT-5.6, and GPT-5.6 Sol.

## [0.5.0] - 2026-08-24

### Added

- Wordle `--host mlx` / `--mlx` talks to `mlx_lm.server` on
  `http://127.0.0.1:8080/v1`. Live runs print the harness the policy saw
  and write `wordle-summary.json` plus the full episode trace.
- Runnable offline benchmark examples now cover both model IDs and arbitrary
  policy factories with versioned `TaskDataset` inputs, persisted episode
  traces, and Markdown/JSON reports.
- Library and Twitter example guides, plus deterministic Twitter
  `wait_for_engagement` for an achievable delayed-likes task.
- Executable Wordle, Library, and Twitter notebooks covering environment
  authoring, scored traces, training returns, versioned tasks, and benchmarks.
- Synchronous environment policy APIs: the `Policy` protocol,
  `EnroutePolicy`, `ScriptedPolicy`, and `Environment.run_episode()`.
  `Benchmark.from_policies()` accepts named fresh-policy factories for
  arbitrary policy comparisons without an Enroute client.
- Explicit episode lifecycle and stop APIs: `EpisodeState`, `EpisodeError`,
  `StopReason`, and `Environment.episode_state`. Invalid reset/step/messages/
  close sequences are guarded.
- Deterministic replay APIs: `replay_actions()`, `verify_replay()`,
  `ReplayResult`, and `ReplayMismatch`, with fingerprint, observation,
  transition, snapshot, and final-stop verification.
- `TaskDataset` for versioned benchmark inputs, plus the `TraceDataset` alias
  and declarative `TraceFilter` for rollout/production trace collections.
- Benchmark provenance/report types: `CaseKey`, `CaseResult`, `WinRatePair`,
  `ModelStats`, `RunManifest`, `TaskSetMetadata`, and `TaskDatasetMetadata`.
  Reports now include per-case provenance, failure buckets, descriptive reward
  uncertainty, and run metadata.
- Benchmark environment/runtime factories: `environment_factory` creates a
  fresh environment when `spawn()` cannot reproduce required constructors or
  stateful dynamic closures, while `runtime_factory` creates a fresh
  synchronous sandbox, remote, or custom runtime for each job.
- Optional `trace_writer` persistence for `Benchmark.from_policies()`.
  Successful and failed episode traces are recorded when a caller-owned writer
  is supplied.
- Trace lineage and classification fields: `trace_kind`, `parent_trace_id`,
  `episode_trace_id`, and `stop_reason`; decisions now include `decision_id`
  and zero-based `index`. `TraceContext` links optional child LLM-call traces
  to an episode.
- Text-action helpers `TEXT_ACTION`, `normalize_action()`, `is_text_action()`,
  and `is_tool_action()`; text-only responses are recorded as `respond`
  actions and stop with `policy_stop`.
- Public `ActionResult` and the `Environment.apply_action()` author hook for
  scalar, text, and custom action semantics.
- `trace_json_schema()` for loading the packaged canonical JSON Schema.
  `scripts/generate_trace_schema.py` generates and checks identical packaged,
  repository, and documentation mirrors from the Python `Trace` model.

### Changed

- After each `step`, the next observation is appended to `env.messages()`
  so the policy sees the same board the decision recorded, not only the
  last tool JSON.
- `Environment.step()` is now framework-owned and rejects subclass overrides.
  It centrally records responses and decisions, manages tool messages/errors,
  merges `ActionResult.info`, and advances lifecycle state. Tool environments
  retain the default dispatch behavior; custom actions override
  `apply_action()`.
- Environment types live in their own modules (`task`, `step`, `rollout`,
  `episode`, `tool`, `action`). `from enroute.environments.env import
  TaskData` still works.
- `Environment.snapshot()` now returns `None` by default. State is persisted
  only when an environment explicitly returns a trace-safe snapshot.
- `Environment.fingerprint()` now hashes tool, scorer, and hook implementation
  bodies, configured callable-object/closure state, and
  `fingerprint_payload()`, in addition to `max_turns`, instructions, type
  contracts, schemas, weights, and standard environment fields.
- Environment authors can override `fingerprint_payload()` for
  behavior-affecting constructor or external configuration that is not
  represented elsewhere. Payloads must be deterministic and must not contain
  secrets.
- Environment rollout persists exactly one episode trace by default.
  `record_llm_traces=True` opts into separately persisted, linked child LLM
  traces; policy calls otherwise remain inside episode decisions.
- `TaskData.expected` is scorer-only and is no longer copied into episode
  trace metadata. Deterministic replay that needs this hidden value must
  receive the original `TaskData` explicitly.
- `Trace.transitions(source=...)` now aligns reward selection with
  `decision_rewards()` / `returns()`: `outcome`, `events`, or `both`.
- Trace dataset content hashes now cover full canonical trace serialization
  (`hash_version="2"`), and loads verify supported manifest hash versions.
  Task dataset hashes cover complete tasks, including sensitive `expected`
  labels and metadata, in task order, with required integrity-checked
  manifests. `content_hash` is a snapshot identity,
  `current_content_hash` recomputes current mutable content, and `save()`
  refreshes the snapshot.
- `Benchmark.run(dataset=...)` now consumes `TaskDataset`. Trace datasets are
  rollout/production outputs for analysis, export, and training artifacts.
- Benchmark manifests use the identity of the environments actually created
  for worker jobs, include an order-sensitive `task_set` hash for task
  datasets, explicit tasks, and environment-provided tasks, and record
  `runtime_fingerprints`. Stale mutated `TaskDataset` inputs are rejected.
- Pairwise benchmark win rates are now aligned by `(task_id, repeat)` rather
  than concurrent completion order. Failed or unscored pairs are excluded
  and counted; ties count as half a win.
- Benchmark cost and latency statistics aggregate episode-total metrics.
  `Report.compare()` accepts a non-negative absolute reward `tolerance`,
  validates compatible environment/runtime/task provenance by default, and
  supports `allow_incompatible=True`. `Report.manifest` remains optional when
  loading legacy reports.
- Default content redaction now also removes environment task input, state
  snapshots, decision observations, decision request/response content, and
  text-action payloads.
- Every `StopReason` now enters the `stopped` lifecycle state; only
  `messages()` and `close_episode()` remain valid until close. Policy, action,
  step, and scorer exceptions close the trace as `failed` with stop reason
  `failure`.
- Pre-1.0/v0.4 traces without `trace_kind` are migrated on load. Episode kind
  and lineage are inferred, and missing decision indexes/ids are generated
  deterministically. Replay now rejects traces marked as redacted.

## [0.4.0] - 2026-08-21

### Added

- Gym-shaped environments: subclass `Environment`, decorate methods with
  `@tool`, and use `reset` / `step` / `close_episode` alongside `rollout()`.
  One rollout is one episode; the model is passed in, not baked into the
  environment. The default `step` dispatches tools and records a decision.
- Episode traces: optional `Decision` steps (observation, model context, parsed
  action, tool results, reward events) plus `initial_state`, `final_state`,
  `model`, `metrics`, `terminated`, `truncated`, and `environment_fingerprint`.
  `Trace.transitions()` flattens an episode for downstream analysis. Production
  `llm` / `tool` / `event` steps still round-trip.
- Simulated Twitter account example (`examples/environment/twitter`) with
  person-complete tools and pluggable goals.
- `Trace.credit()` (late reward on the episode or one decision) and
  `Trace.returns(gamma=…)` for discounted credit assignment. Reward is not
  assumed per decision — research-then-answer uses a terminal scorer; likes
  that arrive later use `credit`.
- Library example (`examples/environment/library`): search / read / answer,
  the start-to-finish RL handoff.
- Wordle example (`examples/environment/wordle`): `WordleEnv` owns the secret,
  official word lists, `guess`, board observations, and rewards. The model
  is only the policy. The example plays via `reset` / `step` (Gymnasium /
  OpenEnv); `rollout()` stays as convenience.
- `Observation` and `State` types (`Environment[ObsT, StateT]`). Nested
  `@tool` calls are recorded as `ToolCallStep.children` for hierarchical
  credit later. Library `research` is the demo.

### Changed

- `World` / `BaseWorld` / `world=` are gone. Write
  `class WordleEnv(Environment[WordleObservation, WordleState])` and put
  episode data on `self.state`. `Rollout.env` replaces `Rollout.world`.
  Concurrent episodes use `env.spawn()` (Benchmark does this automatically).
  Drive agents with `reset` / `step` / `rollout`; `observe` is an author hook.

## [0.3.4] - 2026-08-18

### Added

- `StreamDelta.reasoning_started` and `reasoning_finished` mark the bounds of a
  thinking block, including when Anthropic encrypts the tokens and sends empty
  `thinking_delta` events. A UI can show a thinking indicator the same way
  Cursor does, even when there is no readable text. Anthropic requests ask for
  adaptive thinking by default so those bounds actually arrive.

## [0.3.3] - 2026-08-18

### Added

- `Message.reasoning` and `StreamDelta.reasoning` surface thinking-model output,
  read from `/v1/responses` on OpenAI, `reasoning`/`reasoning_content` on other
  OpenAI-compatible hosts, `thinking` blocks on Anthropic, `thought` parts on
  Gemini, and `reasoningContent` on Bedrock. `reasoning_signature` carries the
  host's attestation so a thinking block can be replayed on the next turn.
- OpenAI requests now use `/v1/responses` by default. Chat Completions rejects
  function tools on every current model and never reports reasoning; Responses
  streams both. A request that needs `stop`, `seed`, or a `max_tokens` below 16
  stays on Chat Completions. Pin `transport="chat"` or `transport="responses"`
  to force one endpoint.
- `response_format` now works on every host. Gemini uses its native
  `responseSchema`; Anthropic and Bedrock force a single-tool call whose input
  schema is the requested schema and unwrap the result into message content.
- `tool_choice` is translated for Anthropic and Bedrock.
- A capabilities guide covering streaming, tool calling, structured output, and
  reasoning.

### Changed

- Gemini requests ask for thought summaries (`includeThoughts`) so a thinking
  model is not silent for seconds before the first text delta.

### Fixed

- Anthropic streams now emit tool calls. `content_block_start` and
  `input_json_delta` were dropped, so tool calling silently produced nothing
  when `stream=True`.
- Bedrock streams now emit tool calls and reasoning from `contentBlockStart` and
  `contentBlockDelta`.
- Gemini streams now emit tool calls; `functionCall` parts were dropped.
- Failed streaming requests report the host's error instead of an httpx
  "Attempted to access streaming response content" message, which masked real
  4xx bodies on Anthropic, Google, and Bedrock.
- OpenAI-compatible hosts that 400 on `max_tokens` are retried with
  `max_completion_tokens`, and reasoning models that reject `temperature` or
  `top_p` are retried without them. Both rejections are remembered per model.

## [0.3.1] - 2026-08-18

### Added

- `StreamChunk.to_openai()` so a hosted gateway can emit one OpenAI Chat Completions
  SSE shape from every host. `raw` stays on the chunk for debugging and is not
  part of the client contract.
- Live stream smoke tests that pin `provider.only` for each configured key.

### Fixed

- Anthropic streams now carry `input_tokens` from `message_start` onto the usage
  chunk, so a streamed prompt is billed at the real token count.
- OpenAI-compatible hosts that 400 on `stream_options` are retried without it.

## [0.1.0] - 2026-08-13

### Added

- Initial `enroute` package: unified LLM routing with traces, environments, and benchmarks.
- Native httpx providers for OpenAI-compatible APIs, Anthropic, and Google.
- `Enroute` client with hosted-gateway mode (`ENROUTE_API_KEY`) and BYOK `providers={...}`.
- Routing policies, fallbacks, retries, model catalog, and local cost estimation.
- Tracing with JSONL/SQLite/OTel sinks, redaction, sampling, and late labels.
- Environments (tasks, tools, scorers), versioned datasets, and benchmark reports.
- Docs site (MkDocs) and cookbook-style routing examples.

[Unreleased]: https://github.com/lastlabs-ai/plural/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.8.0
[0.7.4]: https://github.com/lastlabs-ai/plural/releases/tag/v0.7.4
[0.7.3]: https://github.com/lastlabs-ai/plural/releases/tag/v0.7.3
[0.7.2]: https://github.com/lastlabs-ai/plural/releases/tag/v0.7.2
[0.7.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.7.1
[0.6.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.6.1
[0.6.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.6.0
[0.5.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.5.1
[0.5.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.5.0
[0.4.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.4.0
[0.3.4]: https://github.com/lastlabs-ai/plural/releases/tag/v0.3.4
[0.3.3]: https://github.com/lastlabs-ai/plural/releases/tag/v0.3.3
[0.3.1]: https://github.com/lastlabs-ai/plural/releases/tag/v0.3.1
[0.1.0]: https://github.com/lastlabs-ai/plural/releases/tag/v0.1.0
