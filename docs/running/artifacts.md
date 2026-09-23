---
route: /docs/running/artifacts
title: Artifacts and evidence
order: 88
description: Read trajectories, final state, and scoring evidence to understand what happened in a run.
audience: all
nav: true
nav_group: Run
---
# Artifacts and evidence

Artifacts are the files saved from a run. Use them to understand what the agent did, why it received a score, and which configuration produced the result.

Start with the trajectory for the sequence of actions, the final State for what changed, and the Verifier results for the score. The receipt identifies the exact versions used; the manifest lists captured files and their hashes.

A `Resource` describes an input to a Task or Environment. An artifact is an output from an execution.

## Local layout

```text
.plural/jobs/JOB_ID/
  run.json
  config.json
  lock.json
  events.jsonl
  result.json
  trials/TRIAL_ID/
    selected.json
    result.json
    executions/0/
      receipt.json
      result.json
      logs/
      artifacts/
        manifest.json
        trajectory.jsonl
        trajectory.normalized.json
        state.json
        observation.json
        view.json
        verifier-results.json
```

A local `plural run` writes this directory at the project root. `run.json` pins
the version and content hash of every input, which is what `plural job rerun`
reuses. `plural trial show TRIAL_ID` prints a Trial's artifact and log paths.

Only files actually produced or captured are present. The manifest records
each artifact's path, SHA-256, media type, byte size, and optional role.
Receipts bind those hashes to the exact Task, Benchmark, model endpoint,
Environment, Verifiers, Agent, Harness, mode, Runtime, timing, and cost.

Execution receipts, logs, manifests, and artifact bytes are immutable. A retry
adds a new `executions/N/` directory; it does not overwrite the failed
execution. A human review updates `selected.json` and the Trial and Job
`result.json` summaries, and leaves the captured evidence unchanged.

## Episode scoring

A Verifier function receives the completed Episode: final Observation, full
State, trajectory, artifacts, and usage. None of this reaches the agent. A
Verifier that runs a command receives every captured artifact in its scoring
workspace. Isolate untrusted scoring code with its own `VerifierRuntime`.

## Logs, secrets, and trust

Plural replaces the exact values of the credentials it injects, such as the
secrets an Agent grants its Harness and the model API key a Verifier uses, in
the stdout and stderr logs it captures. It matches exact values only, so it
cannot catch a secret that code has encoded or transformed, and it does not
redact custom artifacts, external systems, or anything else your code writes.
State hidden from the agent is not a secret store.

Receipts are unsigned, and a local run's receipt reports `self_reported` trust. Hashes detect
content changes; they do not independently prove that a custom Harness recorded
truthful behavior.

## Import and derive

Use `normalize_trajectory(...)` to read a captured JSON or JSONL trajectory in a common format while keeping the original file. Imported evidence remains unverified; there is no general CLI command for importing arbitrary run directories.

Write analyses and exports as new derived files. Never edit a captured
artifact and retain its old manifest or receipt.
