---
route: /docs/reference/glossary
title: Glossary
order: 220
description: Short definitions for the objects you author and the records a Job produces.
audience: all
nav: false
nav_group: Reference
---
# Glossary

- **Project:** a directory containing `project.yaml`, with one subdirectory per resource, such as `tasks/ticket-1/`.
- **Environment:** the world, with actions, state, observations, resources, runtime, and policy.
- **Observation:** the information the agent receives from that world, and the only part of a step the model sees.
- **State:** the world's internal data, including fields not meant for the agent.
- **Native action:** an operation implemented by the Environment and marked `@action`.
- **Runtime:** the execution machine and its dependencies, connectivity, and limits. `local` is a trusted subprocess, not a sandbox.
- **SandboxProvider:** an implementation of Runtime lifecycle and controls.
- **Model provider:** an endpoint implementation that answers model requests.
- **Resource:** a file or data input declared by an Environment or Task; not a run output.
- **Task:** instructions and public information pinned to one Environment and one or more Verifiers.
- **Verifier:** a deterministic, agent, or human scorer attached to a Task.
- **Evidence contract:** the artifacts and Observation or State fields a Verifier asks for.
- **Agent:** instructions, model configuration, and optionally a Harness. With no Harness, an Agent uses `native`, Plural's built-in tool loop.
- **Harness:** the executable interaction loop around the model. `Harness` is the base class you subclass; `HarnessDefinition` is the flattened public schema for a packaged Harness.
- **Harness grant:** the capabilities one Harness keeps in one Environment after the Environment's policy is applied.
- **Benchmark:** a versioned collection of Tasks used for comparison. It ranks on the Verifier score.
- **Job:** one run of a Task or Benchmark with Agents, mode, attempts, and scheduling configuration. Every `plural run` creates a new Job.
- **Trial:** one Agent × one Task × one planned attempt.
- **Execution:** one actual execution of a Trial, including a retry after failure.
- **Rerun:** a new Job that runs the exact inputs of an earlier Job or Trial, linked to it by `rerun_of_job_id` or `rerun_of_trial_id`.
- **Trajectory:** normalized episode messages, actions, observations, and related events.
- **Trace:** a tracing-SDK or hosted observability record; not every trajectory is a Trace.
- **Artifact:** a captured output file, identified by path and content hash.
- **Receipt:** the Trial's recorded identities, runtime, timing, and integrity information.
- **Review:** a person's scoring submission for a pending human Verifier.
- **Score:** the number a Verifier produces, aggregated onto the Trial. It is the only thing a Benchmark ranks on.
- **Reward:** per-step credit for one state transition, recorded on the episode and never part of a score. `Trial.step_reward_total` is the episode's total.
- **Rewarder:** an Environment-declared reward signal, run inside every step.
- **Stop reason:** how one episode ended, one of `plural.STOP_REASONS`, such as `environment_terminated`, `agent_finished`, or `max_turns`.
- **TITO:** exact tokens in and tokens out, with aligned provenance for training.
- **Version:** a semantic version of an authored resource; its content hash identifies the resolved content.
- **Push:** saving a resource to its hosted project as an immutable revision that stays private to the project.
- **Revision:** one pushed version of a resource. It never changes after it is saved.
- **Scope:** the account or hosted project that hosted commands go to. It never changes what your credential may do.
- **Publication:** an explicit action in the web app that makes a Benchmark release and chosen results public.
- **Leaderboard:** a comparison derived from Agent results on a Benchmark under a stated aggregation rule.
