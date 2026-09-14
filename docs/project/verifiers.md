---
route: /docs/project/verifiers
title: "Verifiers"
order: 50
description: "Score completed Trials with deterministic commands, model judges, or human review using one evidence contract."
audience: all
nav: true
nav_group: Build
outcome: You can attach deterministic, Agent, and Human Verifiers to Tasks.
---
# Verifiers

Verifiers assess completed Trials. They do not run the Environment transition
loop and are separate from train-mode Rewarders. Every Task needs at least one.

## Deterministic Verifier

Use deterministic code when success can be computed from state or artifacts.
It is fastest, cheapest, and easiest to audit.

```python
from pathlib import Path
from plural import EvidenceContract
from plural.verifiers import DeterministicVerifier, VerifierRuntime

verify = Path("verifiers/correct.py").read_text(encoding="utf-8")
correct = DeterministicVerifier(
    name="correct-category",
    check=("python", "-c", verify),
    evidence=EvidenceContract(
        observation_paths=("category", "done"),
        state_paths=("expected",),
        include_hidden_state=True,
    ),
    runtime=VerifierRuntime(provider="docker", network="none"),
)
```

The command must write `result_path` (`verifier-result.json` by default) with a
finite `reward`, optional `scores`, nonempty `evidence` when
`evidence_required=True`, and optional `feedback`. Declare required artifact
paths through `evidence.artifacts`.

## Agent Verifier

Use a model judge for semantic quality that code cannot capture reliably:

```python
from plural import AgentVerifier, RubricCriterion

judge = AgentVerifier(
    name="response-quality",
    model="openai/gpt-5.6-luna",
    instructions="Score only from the supplied ticket and response.",
    criteria=(
        RubricCriterion(
            name="helpful",
            description="The response gives a correct, actionable next step.",
            min_score=0,
            max_score=4,
        ),
    ),
)
```

An Agent Verifier has its own catalog-backed `model`, optional `provider` and
`fallback_models`, instructions, criteria, and Runtime (network is `full` by
default). Its judge prompt includes the Task, final Harness result, contracted
`environment_view`, and bounded UTF-8 content or names for artifacts requested
by its evidence contract. It must return the normal finite `VerifierOutput`
shape with evidence. Calibrate it on known good and bad cases, pin it like any
other Verifier, and avoid letting it see answer keys it does not need.

## Human Verifier

Use Human review for subjective, high-stakes, policy, or calibration decisions:

```python
from plural import HumanVerifier, RubricCriterion

review = HumanVerifier(
    name="policy-review",
    instructions="Check policy compliance and customer safety.",
    criteria=(
        RubricCriterion(
            name="compliance",
            description="The response follows the current support policy.",
            min_score=0,
            max_score=2,
        ),
    ),
)
```

A Human Verifier pauses the Trial at `awaiting_review`. The submission is
appended later. It leaves receipts, logs, manifests, and artifact bytes
unchanged while execution, Trial, and Job result projections advance.

## Criteria, evidence, and weighting

Each `RubricCriterion` has `name`, `description`, `weight=1`,
`min_score=0`, and `max_score=1`. Criterion weights normalize scores within a
human review. Verifier `weight=1` controls the weighted average final Trial
reward.

`EvidenceContract` can select:

- `observation_paths`: Agent-visible final fields.
- `state_paths`: internal final fields.
- `include_hidden_state`: explicit permission for hidden selected State.
- `artifacts`: exact required output paths for a deterministic Verifier, or
  artifact names and bounded readable prompt content for an Agent Verifier.

Paths are JSON Pointers; `category` and `/category` are equivalent. Only
selected State/Observation fields enter `environment_view`, but all captured
artifacts are currently staged in the command Verifier workspace. The contract
is not a filesystem ACL, arbitrary artifact safety boundary, or reviewer
authorization policy.

Put Verifiers directly on a Task:

```python
task = Task(..., verifiers=[correct])
```

Prefer deterministic checks for objective facts, use Agent judges for bounded
semantic rubrics, and reserve Human review for judgments worth the latency.
Require evidence that another person can use to explain the score.
