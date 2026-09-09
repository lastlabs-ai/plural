# Glossary

| Term | Definition |
| --- | --- |
| **Trace** | Ordered record of one interaction or episode, plus an optional outcome. |
| **Step** | One entry in a trace: a `Decision`, `LLMCall`, `ToolCall`, or `Event`. |
| **Decision** | One model turn: observation, model context/output, parsed action, tool results, reward events. |
| **Credit** | Late reward attached to an episode or one decision (`trace.credit`). |
| **Return** | Discounted sum of future rewards from a decision (`trace.returns`). How research inherits credit from a later outcome. |
| **Outcome** | Labels, scores, reward, and feedback attached to a trace. |
| **Sink** | Destination that persists traces (JSONL, SQLite, OTel, …). |
| **Environment** | Versioned simulator (`class WordleEnv(Environment[Obs, State])`) with instructions, tools, and scorers that produces scored traces. |
| **Observation** | Per-action view the agent can observe (`Observation` / subclass). Built by `observe`; returned by `reset` / `step`. |
| **State** | Persistent environment object on `env.state`. Nested models live here. Mark secrets with `hidden()`. |
| **Task** | One case an environment can run (`TaskData`). Seeds the env via `setup`; may carry a goal. |
| **Rollout** | One execution of a task through an environment. Synonym: **episode**. |
| **Episode** | Gymnasium name for a rollout. One episode emits one Trace. |
| **Fingerprint** | Hash of an environment's configured behavior, including callable implementations and explicit `fingerprint_payload()`. Compatibility key stored on traces and benchmark manifests. |
| **TaskDataset** | Ordered, content-hashed snapshot of `TaskData` records supplied to a benchmark. |
| **Dataset / TraceDataset** | Named, content-hashed snapshot of rollout or production traces for analysis, training, and export. It is not a benchmark task input. |
| **Benchmark** | Reusable eval on one environment: a task set plus a primary metric. `.run()` produces a `Report`; the host stores the definition and each run. |
| **AgentSpec** | One model/routing configuration pinned to one Environment identity and exactly one Harness binding. Distinct from the hosted `RemoteAgent` alias exported as `Agent`. |
| **HarnessPackage** | Content-addressed external agent-loop manifest plus source. |
| **HarnessBinding** | Exact Harness name, revision, and SHA-256 digest allowed by an Environment and used by an Agent/Trial. |
| **Job** | Complete locked execution of Agents × selected tasks × independent attempts. `JobSpec` is configuration; `execution.Job` runs it. |
| **Trial** | One Agent, task, and one-based independent attempt. Retries retain its Trial ID. |
| **Attempt** | Independent benchmark repetition created by `n_attempts`; creates a distinct Trial. |
| **Retry** | Re-execution after a retryable failure; does not create a distinct Trial. |
| **JobLock** | Immutable package/task/runtime provenance captured during deterministic planning. |
| **Receipt** | Per-Trial execution provenance and hashes. Currently self-reported, not signed attestation. |
| **Verifier** | Separate no-network process that scores hidden evaluator input and declared artifacts. |
| **Artifact** | Exact declared regular file downloaded, hashed, and stored for evidence/regrade. |
| **SandboxProvider** | Async process lifecycle/isolation provider (`local`, Docker, Daytona, or plugin). |
| **Routing policy** | Object that orders model/provider routes for a request. |
| **Provider** | Adapter that speaks a vendor API and returns normalized types. |
| **Catalog** | Offline model metadata (context, pricing, modalities). |
