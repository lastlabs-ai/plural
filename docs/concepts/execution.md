# Packages, agents, jobs, and trials

The v1 foundation separates the thing being evaluated from the thing doing the
work.

## Ownership model

An **Environment** owns the task contract: instructions, context, ordered tasks,
declared commands/tools, environment code and source, limits, policy,
capability requirements, and the isolated verifier. Hidden `expected` and
`verifier_input` values are never included in the harness task payload.

A **HarnessPackage** owns one agent-loop implementation. Its manifest declares
the argv entrypoint, protocol, model/auth requirements, secret grants, and exact
output/artifact paths. A content digest plus name and revision becomes a
**HarnessBinding**.

An **AgentSpec** binds one model/routing configuration to one exact Environment
identity and exactly one Harness binding. A Trial never combines multiple
harnesses: it inherits the Agent's single binding.

A **BenchmarkDefinition** is an ordered selection of task IDs tied to one exact
Environment revision/digest. It does not own tasks and cannot silently follow a
new Environment revision.

A **JobSpec** combines the complete Environment manifest, Benchmark, one or
more Agents, scheduling controls, runtime requirements, and retry policy.
Planning expands:

`agents × selected task_ids × n_attempts = trials`

The order is deterministic: Agent order, task order, then attempt number.

## Attempts are not retries

`n_attempts` creates independent `TrialSpec` identities for statistical
repetition. Attempt numbers start at 1 and participate in `trial_id`.

`RetryPolicy.max_retries` repeats execution of the same Trial after configured
transient `ErrorCode` values. Retries do not create a new Trial identity.
`TrialReceipt.retry_count` and `.plural/jobs/.../attempts/<retry>/` make them
auditable. The legacy `Benchmark.repeats` API remains supported and maps to the
same statistical idea; new jobs call it `n_attempts`.

## Locks and durable state

`JobSpec.plan()` records a **JobLock** containing exact environment, benchmark,
task-set, agent and harness hashes plus instructions, commands, policy,
execution limits, source digest, and runtime requirements. Scheduling-only
concurrency and retry settings do not change the trial-set `job_id`, but the
full `spec_hash` and stored config must remain compatible. Resume rejects a
different lock with `lock_incompatible`.

Local state is crash-safe under `.plural/jobs/<job_id>/`: config, lock,
per-retry logs and receipts, immutable artifacts, optional regrades, and the
aggregate result. Successful trials are skipped on resume.

## Receipts, artifacts, and trust

Each Trial has a **TrialReceipt** with package and task digests, runtime/image
identity, provider-confirmed controls, timing, artifact hashes, verifier hash,
and retry count. Receipts are integrity records, not remote attestations:
`trust` is currently always `self_reported`. A local user, Docker daemon,
provider account, or compromised host can alter execution outside Plural's
view.

Harness outputs and artifacts must be declared exact regular files. Plural
hashes downloaded artifacts and stores them immutably. The harness protocol is
forbidden from emitting score, reward, verifier, expected, or scores fields.
When configured, the verifier runs in a fresh sandbox with networking disabled,
receives hidden evaluator input and declared artifacts, and emits a strict
finite score document plus evidence. Regrade reruns only that verifier and
links its receipt to the source receipt.

## Sandbox providers

A **SandboxProvider** implements create, upload, argv execution, exact download,
cancel, and destroy. Preflight compares requested controls with provider
capabilities before launch.

- `local`: unsafe development subprocesses; no process, network, filesystem,
  image, or resource isolation; explicit `unsafe_local` opt-in required.
- `docker`: one hardened container per harness/verifier phase, dropped
  capabilities, no-new-privileges, non-root user, optional no-network/resource
  controls, and forced cleanup. It does not enforce disk limits or domain
  allowlists.
- `daytona`: optional remote SDK provider with image/snapshot/declarative image,
  CPU/memory, and network controls exposed by the adapter. Credentials and the
  external service are required.

Provider plugins use the `plural.sandbox_providers` entry-point group. Provider
claims are enforcement contracts; unsupported requested controls fail rather
than silently degrading.
