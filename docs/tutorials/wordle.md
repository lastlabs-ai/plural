---
route: /docs/tutorials/wordle
title: Wordle
order: 115
description: 'Build Wordle from the seven public SDK concepts, package its action adapter, and run the equivalent generated YAML.'
audience: all
nav: true
nav_group: Tutorials
outcome: You can follow Python, YAML, and CLI parity in a complete local example.
---
# Wordle

`examples/wordle` is the compact puzzle counterpart to the support queue. A
hidden answer stays in State; the Agent sees only marks and remaining guesses.

## Build and validate

```bash
cd examples/wordle
plural validate job.py:job
plural run job.py:job --dry-run
plural validate job.yaml
plural run job.yaml --dry-run
```

The short files each own one concept:

- `wordle.py` defines typed state, observation, and the `guess` action.
- `environment.py` selects `Runtime` and calls `.package(...)`.
- `verifier.py` defines the completed-Trial Verifier.
- `task.py`, `benchmark.py`, `agent.py`, and `job.py` compose public objects.
- `job.yaml` is generated from that public Job.

`Wordle.guess(word)` is the only Agent action. `reset()` chooses the task-bound
secret and `terminated()` stops on success or six guesses. The deterministic
Verifier reads final solved status from its declared evidence view.

`agent.py` explicitly grants `OPENAI_API_KEY` to the native Harness. Supply
that value, then run:

```bash
plural run job.py:job
```

Then inspect the Job and Trial:

```bash
plural job list
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID
```

Check `trajectory.jsonl` for guesses and marks, then compare `state.json`,
`observation.json`, and `verifier-results.json` with the manifest and receipt.

## Small variants

`advanced.py` contains:

- an `AgentVerifier` with an efficiency-and-correctness criterion;
- a `HumanVerifier` using the same criteria;
- a custom Harness declaration;
- a Python Rewarder declaration for guesses remaining.

Attach one of those Verifiers alongside the deterministic `solved` Verifier.
Use deterministic scoring for solved status, an Agent judge for bounded play
quality, and Human review for calibration or subjective strategy analysis.

Create another bundled-model Agent and run both with concurrency:

```bash
plural run benchmark.py:benchmark \
  --agent agent.py:agent \
  --agent advanced.py:custom_agent \
  --attempts 2 \
  --concurrency 2 \
  --dry-run
```

Remove `--dry-run` only after the custom Harness implementation and credentials
are ready. A Harness declaration does not make arbitrary code executable by
itself.

## Train-mode boundary

The beginner and advanced Harnesses do not declare exact TITO, so train mode
fails preflight. See [Training and RL](../running/training.md) for the required
TITO, Rewarder, and external-trainer boundary.

Tests require Python and YAML to produce equal Job plans and hashes and verify
the packaged source digest against the materialized tree. Beginner files use
only the plain public evaluation concepts.
