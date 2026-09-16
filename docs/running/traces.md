---
route: /docs/running/traces
title: Traces and Trials
order: 90
description: Follow actions, observations, artifacts, and scores back to the exact run.
audience: all
nav: false
outcome: You can inspect a recorded episode and separate execution failures from performance failures.
---
# Traces and Trials

A **Trial** is one Agent on one Task for one planned attempt. A **Trace** is the record of behavior during that episode: model calls, actions, observations, and other events captured by the selected Harness or tracing integration.

The Trial result adds the scoring outcome and receipt. Keep both: the score tells you how the agent performed, and the trace helps explain why.

## Inspect one local run

After the [quickstart](../getting-started.md), copy the Job and Trial IDs from its result:

```bash
plural job show JOB_ID
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID
```

`plural run --offline` creates its store next to the source YAML. Inspection commands default to `.plural/jobs` in your working directory; supply `--store` if those locations differ. Its main files are:

```text
.plural/jobs/JOB_ID/
  config.json                         resolved Job definition
  lock.json                           revision lock
  events.jsonl                        orchestration progress
  result.json                         Job result
  trials/TRIAL_ID/
    result.json                       current Trial result
    selected.json                     selected successful execution, if any
    executions/0/
      receipt.json                    identities and artifact hashes
      result.json                     this execution's result
      logs/                           captured execution and verifier logs
      artifacts/
        manifest.json                 paths, hashes, media types, sizes, and roles
```

Execution directories are numbered from zero. Later retries append their own directories. Planned attempt numbers in the Trial are one-based; they are different from execution indices.

## Read the support episode

In the selected execution's `artifacts/`, open `trajectory.jsonl` to see the native runner's model messages, tool calls, and returned observations. `result.json` records its final response. Compare the action observations with the `correct-category.correct` score in the Trial result.

The native runner's trajectory is a JSONL interaction record. It is not automatically a full schema-v3 SDK Trace, and its trace ID does not by itself upload the record to Plural Intel. The standalone tracing SDK and hosted ingestion have their own contracts. Inspect what your selected integration actually records.

When available, final Environment state, observation, rendering, trajectory, and
Verifier results are copied into the execution artifacts and listed in the
manifest. Missing runtime data remains absent. Preserve additional files
explicitly rather than assuming every runtime file survives teardown.

## Diagnose in order

1. Check the execution status. If the process failed, inspect the runtime error before judging the agent's reasoning.
2. Check the Task and revision identities. Confirm this is the world and scoring rule you intended to test.
3. Read the first observation and the actions that followed. Look for missing information, repeated tool errors, or a misunderstood response.
4. Check why the loop stopped: terminal state, turn budget, timeout, or an explicit result.
5. Compare final state and artifacts with the verifier's feedback. A plausible answer may still leave the world in the wrong state.

A verifier failure may mean evidence was missing rather than that the agent performed poorly. Keep execution completeness visible when summarizing a benchmark.

## Capture your own application

Plural's tracing SDK can record model calls and application events outside a package Job. This is useful when moving from production behavior toward a repeatable evaluation. Export spans to an existing collector through [OpenTelemetry](../reference/integrations.md#plural-intel-ci-and-opentelemetry), and keep the [evaluation contract](../architecture/evaluation-contract.md) as the record-format reference.

Capture useful evidence, not just final prose. Record tool inputs and outcomes, relevant observations, model identity, errors, and the artifacts needed by your scoring rule. Fields such as usage and latency depend on the integration actually recording them; do not infer them from an empty trace.

## Read hosted records

In Plural Intel, open the Job, choose a Trial, and follow its trace and artifact references. Hosted records depend on evidence being uploaded or ingested; a local filesystem path cannot be opened by another user's browser.

Use the Trial receipt to identify Environment, Task, Agent, Harness, and Verifier revisions. Receipts currently label trust as `self_reported`; artifact hashes identify content, but do not independently prove the truth of every event recorded by a custom harness.

## Reuse evidence responsibly

Reading a stored episode does not rerun the model. Re-executing the Task creates new behavior and may incur costs. Do not promise deterministic replay of remote services or stochastic models just because their earlier trace exists.

Selected traces can become datasets or training examples. Preserve their Task provenance, scoring status, and data permissions. Ordinary message transcripts cannot substitute for the exact token records required by train mode. See [Training](training.md).

Treat captured files according to their contents. Hidden schema fields are not automatically scrubbed from every custom artifact, log, or model message. The [verifiers guide](../project/verifiers.md) explains Episode scoring boundaries.

If the episode needs a human score, continue to [Reviews](reviews.md).
