---
route: /docs/tutorials/support-queue
title: Support queue tutorial
order: 150
description: Build and evaluate a realistic customer-support workflow with typed actions, internal State, Episode scoring, multiple Agents, and review variants.
audience: all
nav: true
nav_group: Tutorials
---
# Support queue tutorial

The complete project is `examples/first-project`. It evaluates an Agent that
inspects a ticket, chooses a team, drafts a customer response, and resolves the
case.

## 1. Build the project

```bash
cd examples/first-project
python build.py
plural validate job.yaml
plural run job.yaml --dry-run
```

`build.py` is canonical; it writes Environment, Verifier, Task, Agent,
Benchmark, and Job YAML through `plural.project.dump`.

The Environment has four focused actions:

```python
@action
def inspect_ticket(self) -> dict: ...

@action
def categorize(self, category: str) -> dict: ...

@action
def draft_response(self, message: str) -> dict: ...

@action
def resolve(self) -> dict: ...
```

The expected category lives on State. The Agent sees the ticket and
applicable policy through Observation, but not the answer key. `view()` creates
a compact operator rendering. `policy.md` is represented as an authored
Environment Resource and packaged with the source. The Resource itself is
metadata-only: Plural does not fetch, mount, or load its content. This example
exposes policy text through the Environment's own reset/Observation logic.

The adapter in `environment/commands.py` receives an action name and JSON,
restores `state.json`, invokes `step()`, then persists State, Observation, and
rendering.

## 2. Score actual world state

The deterministic Verifier requests only the fields it needs:

```python
def correct_category(episode: Episode) -> VerifierOutput:
    done = bool(episode.observation.get("done"))
    match = episode.observation.get("category") == episode.state.get("expected")
    drafted = bool(str(episode.observation.get("draft_reply") or "").strip())
    return VerifierOutput(reward=float(done and match and drafted))

verifier = DeterministicVerifier(name="correct-category", check=correct_category)
```

It checks resolved status, category equality, and a nonempty response. This is
stronger than grading the Agent's final claim.

## 3. Run multiple Agents

Run `plural auth login`, then run the three-Task Benchmark against two
catalog-backed Agents:

```bash
plural run benchmark.yaml \
  --agent agents/careful.yaml \
  --agent agents/concise.yaml \
  --concurrency 2
```

This creates six Trials. Add `--attempts 2` for twelve independent samples.
Use `--per-runtime-concurrency` to bound pressure on one Runtime provider.

Model execution can incur charges. The example Runtime is `local` for easy
inspection and is explicitly unsafe; switch to a policy-compatible Docker or
remote provider before running untrusted code.

## 4. Inspect evidence

```bash
plural job list
plural job show JOB_ID
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID
```

Open the selected execution under `.plural/jobs/JOB_ID/trials/TRIAL_ID/`.
Confirm receipt pins, then inspect `trajectory.jsonl`, `state.json`,
`observation.json`, `view.json`, `verifier-results.json`, logs, and
`artifacts/manifest.json`.

## 5. Try other Verifier kinds

Keep the deterministic Verifier for objective resolution. Add an
`AgentVerifier` with criteria for empathy, clarity, and policy-grounded next
steps when semantic response quality matters. Add a `HumanVerifier` for a
small high-risk slice or to calibrate the Agent judge.

Verifier `weight` controls the final weighted average. Avoid replacing an
objective check with a judge merely because a judge is easier to write.

## 6. Prepare train mode honestly

The starter's native Harness does not emit exact TITO, so changing only
`mode: train` fails preflight. Train mode needs a TITO-capable Harness and any
transition Rewarders; training algorithms remain external. Follow the
authoritative [Training and RL](../running/training.md) workflow.
