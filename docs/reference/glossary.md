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
- **Environment:** the world the AI works in, such as the Wordle game or a support
  desk. It sets what the AI can do and see. *Precisely:* the world, with actions,
  state, observations, resources, runtime, and policy.
- **Observation:** what the AI is shown about the world, like the colored tiles in
  Wordle. *Precisely:* the information the agent receives from that world, and the only
  part of a step the model sees.
- **State:** the full truth about the world, including things the AI must not see,
  such as the secret word. *Precisely:* the world's internal data, including fields not
  meant for the agent.
- **Native action:** a move the world itself offers, such as `guess` in Wordle.
  *Precisely:* an operation implemented by the Environment and marked `@action`.
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
  *Precisely:* the artifacts and Observation or State fields a Verifier asks for.
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

## Scores, rewards, and training

- **Score:** the grade a Verifier gives the finished work, usually between 0 and 1. It
  is the only thing a leaderboard ranks on. *Precisely:* the number a Verifier
  produces, aggregated onto the Trial. It is the only thing a Benchmark ranks on.
- **Reward:** a small bit of credit for one move, used to train models. It never counts
  toward the score, and the AI never sees it. *Precisely:* per-step credit for one state
  transition, recorded on the episode and never part of a score.
  `Trial.step_reward_total` is the episode's total.
- **Rewarder:** a rule, attached to the world, that hands out rewards after every move.
  *Precisely:* an Environment-declared reward signal, run inside every step.
- **Stop reason:** why an attempt ended, such as the game finishing or the AI running
  out of turns. *Precisely:* how one episode ended, one of `plural.STOP_REASONS`, such
  as `environment_terminated`, `agent_finished`, or `max_turns`.
- **TITO:** an exact copy of the text sent to and received from the model, kept so a
  training system can learn from it. Short for "tokens in, tokens out". *Precisely:*
  exact tokens in and tokens out, with aligned provenance for training.

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
