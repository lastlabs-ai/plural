---
route: /docs/reference/glossary
title: Glossary
order: 220
description: Short definitions for the objects you author and the records a Job produces.
audience: all
nav: true
nav_group: Reference
---
# Glossary

- **Environment:** the world, with actions, state, observations, resources, runtime, and policy.
- **Observation:** the information the agent receives from that world.
- **State:** the world's internal data, including fields not meant for the agent.
- **Native action:** an operation implemented by the Environment.
- **Runtime:** the execution machine and its dependencies, connectivity, and limits.
- **SandboxProvider:** an implementation of Runtime lifecycle and controls.
- **Model provider:** an endpoint implementation that answers model requests.
- **Resource:** authored Environment or Task input metadata; not a run output.
- **Task:** instructions and public information pinned to one Environment and one or more Verifiers.
- **Verifier:** a deterministic, agent, or human scorer attached to a Task.
- **Evidence contract:** the artifact requirements and observation/state paths requested by a Verifier.
- **Agent:** instructions, model configuration, and optionally a Harness.
- **Harness:** the executable interaction loop around the model.
- **Harness grant:** the effective capability policy for one Agent–Environment combination.
- **Benchmark:** a versioned collection of Task revisions used for comparison.
- **Job:** the selected Task or Benchmark, Agents, mode, attempts, and scheduling configuration.
- **Trial:** one Agent × one Task × one planned attempt.
- **Execution:** one actual execution of a Trial, including a retry after failure.
- **Trajectory:** normalized episode messages, actions, observations, and related events.
- **Trace:** a tracing-SDK or hosted observability record; not every trajectory is a Trace.
- **Artifact:** a captured output file, identified by path and content hash.
- **Receipt:** the Trial's recorded identities, runtime, timing, and integrity information.
- **Review:** a person's scoring submission for a pending human Verifier.
- **Reward:** the scalar quality signal produced by a Verifier or learning integration.
- **Rewarder:** an Environment-declared learning signal, used by supported train execution paths.
- **TITO:** exact tokens in and tokens out, with aligned provenance for training.
- **Version:** a semantic version of an authored object; its content hash identifies resolved content.
- **Leaderboard:** a comparison derived from Agent results on a Benchmark under a stated aggregation rule.
