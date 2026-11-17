---
route: /docs/reference/glossary
title: Glossary
order: 220
description: Plain definitions for every word Plural uses, from the pieces you build to the records a run produces, each with a precise note for power users.
audience: all
nav: false
nav_group: Reference
---
# Glossary

Every word Plural uses, in plain language. Each entry starts with an everyday
explanation. The *Precisely* note after it is for readers who need the exact rule.
For the bigger picture, read [Core concepts](../getting-started/concepts.md).

## The pieces you build

- **Project:** the folder that holds everything you build, with one subfolder for each
  piece. *Precisely:* a directory containing `project.yaml`, with one subdirectory per
  resource, such as `tasks/ticket-1/`.
- **App:** one system the AI works with, such as the Wordle game, a CRM behind an MCP
  server, or an HTTP API. *Precisely:* a named bundle of actions and private State,
  written in Python or connected as an `mcp`, `openapi`, or `replay` App, with
  the names of the secrets it needs.
- **Environment:** the world the AI works in, such as the Wordle game or a support
  desk. *Precisely:* one or more Apps, plus the Runtime, resources, Harness policy, and
  limits they share.
- **Action:** a move an App offers, such as `guess` in Wordle or an MCP server's tool.
  *Precisely:* an operation an App declares, such as a FastMCP tool or a method marked
  `@action`. The Agent sees it under its own name; only a name two Apps share is
  prefixed with the App's, such as `crm__search`.
- **Observation:** what the AI is shown after a move, like the colored tiles in
  Wordle. *Precisely:* what an action returns, and the only part of a step the model
  sees.
- **State:** an App's full truth, including things the AI must not see, such as the
  secret word. *Precisely:* an App's internal data, including fields not meant for the
  agent. A Verifier reads its snapshots.
- **Control level:** how far Plural can trust an App to start each attempt fresh.
  *Precisely:* `owned`, `sandboxed`, `live`, or `replayed`, derived from the App's kind
  and settings. A Benchmark refuses a `live` App that can change state, and training
  refuses every `live` App.
- **Runtime:** where the world runs, such as a sealed container or your own computer.
  *Precisely:* the execution machine and its dependencies, connectivity, and limits.
  `local` is a trusted subprocess, not a sandbox.
- **SandboxProvider:** the plug-in that starts, controls, and stops a Runtime.
  *Precisely:* an implementation of Runtime lifecycle and controls.
- **Model provider:** a company or server that actually answers a model request.
  *Precisely:* an endpoint implementation that answers model requests.
- **Resource:** a file the world or an assignment starts with, such as a word list or
  a policy document. It is an input, never something a run produces. *Precisely:* a
  file or data input declared by an Environment or Task; not a run output.
- **Task:** one assignment in a world, such as "the secret word is CRANE".
  *Precisely:* instructions and public information pinned to one Environment and one or
  more Verifiers.
- **Verifier:** the grader that marks the finished work. It can be code, an AI judge,
  or a person. *Precisely:* a deterministic, agent, or human scorer attached to a Task.
- **Evidence contract:** the list of things a grader needs to see to do its job.
  *Precisely:* the artifacts and observation or State fields a Verifier asks for.
- **Agent:** the contestant: a model plus the instructions you give it. *Precisely:*
  instructions, model configuration, and optionally a Harness. With no Harness, an Agent
  uses `native`, Plural's built-in tool loop.
- **Harness:** how the contestant plays: the loop that shows the model what it can see,
  asks what to do, and carries out the move. *Precisely:* the executable interaction
  loop around the model. `Harness` is the base class you subclass; `HarnessDefinition`
  is the flattened public schema for a packaged Harness.
- **Harness grant:** what a Harness is still allowed to do in a particular world, after
  that world's rules are applied. *Precisely:* the capabilities one Harness keeps in one
  Environment after the Environment's policy is applied.
- **Benchmark:** the exam: a fixed set of assignments with a leaderboard. *Precisely:* a
  versioned collection of Tasks used for comparison. It ranks on the Verifier score.

## Runs and their records

- **Job:** one run you start, such as "run these two Agents on this exam". *Precisely:*
  one run of a Task or Benchmark with Agents, mode, attempts, and scheduling
  configuration. Every `plural run` creates a new Job.
- **Trial:** one attempt by one Agent at one assignment. *Precisely:* one Agent × one
  Task × one planned attempt.
- **Execution:** one actual go at a Trial. If a Trial is retried after a failure, the
  retry is another execution of the same Trial. *Precisely:* one actual execution of a
  Trial, including a retry after failure.
- **Rerun:** a repeat of an earlier run with exactly the same inputs, even if you have
  edited your files since. *Precisely:* a new Job that runs the exact inputs of an
  earlier Job or Trial, linked to it by `rerun_of_job_id` or `rerun_of_trial_id`.
- **Trajectory:** the step-by-step story of an attempt: what the AI said, what it did,
  and what it saw back. *Precisely:* normalized episode messages, actions,
  observations, and related events.
- **Trace:** a record from a tracing or monitoring tool. It is related to a trajectory
  but not the same thing. *Precisely:* a tracing-SDK or hosted observability record;
  not every trajectory is a Trace.
- **Artifact:** a file an attempt produced and Plural kept. *Precisely:* a captured
  output file, identified by path and content hash.
- **Receipt:** the attempt's proof of what ran: exactly which versions, where, and for
  how long. *Precisely:* the Trial's recorded identities, runtime, timing, and
  integrity information.
- **Review:** a score a person gives when the grader is human. *Precisely:* a person's
  scoring submission for a pending human Verifier.
- **Trust tier:** how far an attempt's result can be trusted, from how it ran.
  *Precisely:* `verified`, `standard`, or `unverified`, computed for every Trial from its
  isolation, network enforcement, pinned image, sandbox provider conformance, and signed
  host report.
- **Conformance:** a check that a sandbox provider really keeps the promises a
  `verified` result depends on. *Precisely:* 14 probes run in real sandboxes, covering
  isolation, network enforcement, and lifetime, cached per provider version. See
  [Runtimes](../project/runtimes.md#conformance).
- **Integrity finding:** a sign that an attempt may have won by a shortcut instead of
  doing the Task, such as reading a grader file. *Precisely:* a coded finding on a
  Trial with a severity (`info`, `warning`, or `critical`) and the steps it points to.
  It never changes a score unless a Benchmark's `scoring.integrity` rule says so. See
  [Integrity](../operations/integrity.md).
- **Reference policy:** code that solves a Task the way a careful person would, used to
  prove the Task can be solved. *Precisely:* a `reference:` function on a Task or its
  Environment, run by `plural task validate`; it never reaches the Agent.
- **Canary:** a random ID hidden beside a Benchmark's graders. An Agent that writes it
  read a grader or was trained on the Benchmark. *Precisely:* a Benchmark's `canary`,
  kept out of every Agent-visible file and flagged as `canary_seen` when it appears in
  an Agent's output.
- **Verdict:** whether one result is really better than another, or only looks it.
  *Precisely:* `better`, `worse`, `within_noise`, or `not_enough_data`, from a paired
  bootstrap of the difference over the Tasks both results share.

## Scores, rewards, and training

- **Score:** the grade a Verifier gives the finished work, usually between 0 and 1. It
  is the only thing a leaderboard ranks on. *Precisely:* the number a Verifier
  produces, aggregated onto the Trial. It is the only thing a Benchmark ranks on.
- **Reward:** a small bit of credit for one move, used to train models, given by a
  Verifier's `reward` function. It counts toward the score only when that Verifier's
  `check` is `total_reward`, and the AI never sees it. *Precisely:* credit on one target of a
  trajectory (a step, a model call, or a span within one), recorded in the Trial's
  reward ledger. It reaches a score only through `check: total_reward`, which scores
  by that Verifier's own rewards. `Trial.step_reward_total` is the episode's
  total of per-step rewards.
- **Step reward:** a reward for one action, given while the attempt runs.
  *Precisely:* what a Verifier's `reward` function returns after each action, recorded
  with source `step`, the Verifier's name and version, and the step it credits.
- **Hindsight credit:** rewards a Verifier hands out after an attempt is over,
  looking at the whole thing. *Precisely:* what a Verifier's `hindsight` function
  returns for a finished Trial, recorded with source `hindsight`. It runs after `check`
  on every Trial of a Task that lists the Verifier, and on stored Trials with
  `plural verifier apply`.
- **Reward ledger:** every reward one attempt earned, wherever it came from.
  *Precisely:* `rewards.jsonl` in a Trial's artifacts, one record per reward, with its
  source, verifier, version, target, and value.
- **Stop reason:** why an attempt ended, such as the game finishing or the AI running
  out of turns. *Precisely:* how one episode ended, one of `plural.STOP_REASONS`, such
  as `environment_terminated`, `agent_finished`, or `max_turns`.
- **TITO:** an exact copy of the text sent to and received from the model, kept so a
  training system can learn from it. Short for "tokens in, tokens out". *Precisely:*
  exact tokens in and tokens out, with aligned provenance for training.

## Evaluating and improving an Agent

These words name how Plural measures an Agent, and how it finds out why one fails.
Score and reward keep the meanings above. The Inspector is being built now: its
entries say what each word will mean, so that it means one thing from the start.

- **Metric:** one thing you measure about an attempt, such as "price correct" or
  "margin in dollars". *Precisely:* a named measurement a Verifier declares, with a
  kind (`binary`, `score`, `number`, `rating`, or `running`), a direction, and an
  optional unit. A Verifier's `check` produces values at the end of the episode; `None`
  means it does not apply. A metric is never a reward and never enters the reward
  ledger. See [Declare metrics](../project/verifiers.md#declare-metrics).
- **Gate:** a metric an attempt must pass to count as done. *Precisely:* a Verifier
  metric with `gate: true`; a `binary` gate passes at 1, and any other kind passes when
  its value meets its `target`, such as `">= 150"`.
- **Pass:** an attempt passes when every gate that applies to it passes. *Precisely:*
  `TrialResult.passed`; with no gate that applies, the Trial is **not judged** and
  `passed` is `None`.
- **Success rate, pass rate:** two different shares of attempts. *Precisely:* the
  success rate is the share whose score reached the Benchmark's success threshold; the
  pass rate is the share of judged Trials that passed every gate.
- **Running metric:** a metric measured after every move, like the money in the till
  as a simulated business runs. *Precisely:* a metric of kind `running`, produced by a
  Verifier's `measure` hook after each step and reduced to one value by its aggregate,
  such as the final or the lowest value.
- **Held-out set:** Tasks kept back to confirm an improvement on work the Agent was
  never tuned on. *Precisely:* the Tasks under a Benchmark's `heldout:`, which diagnosis
  never looks at. Each run against them, and each reveal of their results, is a
  **peek**, and is counted.
- **Checkpoint:** a saved moment of an attempt that it can be restarted from.
  *Precisely:* everything needed to restart a Trial exactly as it stood after step *k*:
  each App's State and random-number state, the workspace, the step counters, the
  Environment's clock, and the Agent's context. Save one by name with
  `plural trial checkpoint`. See [Checkpoints and forks](../running/forks.md).
- **Fork:** rerunning the rest of an attempt from a Checkpoint, to see whether a
  different Agent would have done better. *Precisely:* a Trial started from another
  Trial's Checkpoint, by another Agent or, as a **control**, by the original one.
  Run with `plural trial fork`.
- **History:** how a Fork's Agent learns what happened before the fork point.
  *Precisely:* `native` (as its own conversation, when it has every tool the history
  used), `transcript` (as text in its first message), or `none`; each Fork Trial
  records which.
- **Forkable:** an Environment whose Apps can all be put back from a Checkpoint.
  A `live` App never can.
- **Harness tool:** a tool a Harness brings itself, such as a shell or a file editor,
  as opposed to an Environment's actions. Each call is a step in the same timeline.
- **Change:** one thing a Fork alters at the fork point, other than the Agent, such as
  an observation, to find a cause. *Precisely:* a plugin registered with
  `@change("name")`. A Fork with a change is **diagnostic**: it explains a cause and is
  never shipped.
- **Inspector:** Plural's agent for finding out why an Agent fails. *Precisely:* an
  Agent built on Plural, with read-only evidence tools over a Job, that runs Forks as
  experiments.
- **Finding:** the Inspector's explanation of one failed attempt. *Precisely:* the
  critical step, a cause dimension (model, context, tools, instructions, Harness,
  environment, grader, task, integrity, or one a project adds), the cause, the evidence
  and the Forks that tested it, and a status (`confirmed`, `inferred`, `refuted`, or
  `inconclusive`).

## Versions and sharing

- **Push:** saving a copy of your work to your private hosted project. It never makes
  anything public. *Precisely:* saving a resource to its hosted project as an immutable
  revision that stays private to the project.
- **Revision:** one saved copy from a push, numbered `#1`, `#2`, `#3` in push order. It
  can never be changed afterwards. *Precisely:* one immutable snapshot of a resource,
  numbered per resource by the hosted project and identified by its content hash.
- **Content hash:** the fingerprint of what a revision contains. *Precisely:* a SHA-256
  over the canonical JSON of its definition, leaving out labels such as name and
  version, with dependencies included by their own hashes. See
  [Revision identity](../architecture/revision-identity.md).
- **Version:** an optional name you give one revision, like `1.0.0`, so people can cite
  it. *Precisely:* a release label that names one revision of a resource forever and
  never affects its content hash. Publishing a Benchmark requires one.
- **Lineage:** where a revision came from: the revision it was edited from, forked
  from, or derived from. *Precisely:* typed `edited_from`, `forked_from`, and
  `derived_from` links recorded by the hosted project.
- **Scope:** which account or hosted project your commands go to. *Precisely:* the
  account or hosted project that hosted commands go to. It never changes what your
  credential may do.
- **Publication:** the step that makes an exam and chosen results public. You take it
  on purpose, in the web app. *Precisely:* an explicit action in the web app that makes
  a Benchmark release and chosen results public.
- **Leaderboard:** the ranking of Agents on an exam. *Precisely:* a comparison derived
  from Agent results on a Benchmark under a stated aggregation rule.
