---
route: /docs/running/artifacts
title: Artifacts and evidence
order: 88
description: The files a run leaves behind. Use them to see what the Agent did, why it got its score, and exactly which setup produced the result.
audience: all
nav: true
nav_group: Run
---
# Artifacts and evidence

**Artifacts** are the files saved from a run. They are the evidence: they show
what the Agent did, why it received its score, and exactly which setup produced
the result.

An artifact is an output of a run. Don't confuse it with a **Resource**, which is
an input, such as a word list the Environment provides.

## Where to start

When you want to understand one attempt, read these in order:

1. **The trajectory**, for the sequence of actions the Agent took.
2. **The final State**, for what actually changed in the world.
3. **The Verifier results**, for the score and the grader's feedback.

Two more files back those up. The **receipt** identifies the exact versions that
were used. The **manifest** lists every captured file and its fingerprint (hash),
so you can tell if anything changed afterwards.

`plural trial show TRIAL_ID` prints the paths of a Trial's artifacts and logs. For
a tracked or hosted Job, you can open the same evidence in the web app under Jobs.

## Local layout

A local `plural run` writes this folder at the project root:

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
        episode.jsonl
        trajectory.json
        result.json
        state.json
        observation.json
        view.json
```

Only files actually produced or captured are present. Here is what the main ones
hold:

- `run.json` pins the version and content hash of every input, which is what
  `plural job rerun` reuses.
- `episode.jsonl` is the episode record: every reset, step, and model call in
  order, with token usage and timing.
- `trajectory.json` is the same episode as an
  [ATIF](traces.md#read-the-support-episode) document of the Agent's turns.
- `result.json` in `artifacts/` is the Harness's final response.
- `state.json`, `observation.json`, and `view.json` are the Environment's final
  State, Observation, and display view.

A Harness that returns its own trajectory events also gets `trajectory.jsonl`, and
anything else the Agent writes is captured beside them. Verifier scores and
evidence are in the Trial's `result.json`, not in an artifact.

## Evidence never changes

Execution receipts, logs, manifests, and artifact bytes are immutable. A retry
adds a new `executions/N/` folder; it does not overwrite the failed execution. A
human review updates `selected.json` and the Trial and Job `result.json`
summaries, and leaves the captured evidence unchanged.

The manifest records each artifact's path, SHA-256, media type, byte size, and
optional role. Receipts bind those hashes to the exact Task, Benchmark, model
endpoint, Environment, Verifiers, Agent, Harness, mode, Runtime, timing, and cost.

## Episode scoring

The grader sees more than the Agent does. A Verifier function receives the
completed Episode: final Observation, full State, trajectory, artifacts, and
usage. None of this reaches the Agent. A Verifier that runs a command receives
every captured artifact in its scoring workspace. Isolate untrusted scoring code
with its own `VerifierRuntime`.

## Logs, secrets, and trust

Plural replaces the exact values of the credentials it injects, such as the
secrets an Agent grants its Harness and the model API key a Verifier uses, in
the stdout and stderr logs it captures. It matches exact values only, so it
cannot catch a secret that code has encoded or transformed, and it does not
redact custom artifacts, external systems, or anything else your code writes.
State hidden from the Agent is not a secret store.

Receipts are unsigned, and a local run's receipt reports `self_reported` trust.
Hashes detect content changes; they do not independently prove that a custom
Harness recorded truthful behavior.

## Import and derive

Use `normalize_trajectory(...)` to read a captured JSON or JSONL trajectory in a
common format while keeping the original file. Imported evidence remains
unverified; there is no general CLI command for importing arbitrary run
directories.

Write analyses and exports as new derived files. Never edit a captured artifact
and retain its old manifest or receipt.
