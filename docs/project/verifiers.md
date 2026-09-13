---
route: /docs/project/verifiers
title: "Verifiers"
order: 50
description: "Score completed Trials with deterministic commands, model judges, or human review using one evidence contract."
audience: all
nav: true
nav_group: Project
outcome: You can attach deterministic, Agent, and Human Verifiers to Tasks.
---
# Verifiers

Verifiers assess completed Trials. They do not run the Environment transition
loop and are separate from train-mode Rewarders.

```python
from plural.verifiers import DeterministicVerifier

correct = DeterministicVerifier(
    name="correct",
    check=("python", "verify.py"),
)
```

`AgentVerifier` owns its judge model, instructions, criteria, and runtime.
`HumanVerifier` owns review instructions and criteria. All three share evidence,
weight, metadata, content identity, and the same result contract.

Put Verifiers directly on a Task:

```python
task = Task(..., verifiers=[correct])
```

Weights are Verifier fields. There is no separate weighted binding object in
public code.
