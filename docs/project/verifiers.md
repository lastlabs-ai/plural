---
route: /docs/project/verifiers
title: Verifiers
order: 55
description: Score a completed Episode with a function, a model judge, or a human rubric.
audience: all
nav: true
nav_group: Build
outcome: You can attach a Verifier that scores the full final episode.
---
# Verifiers

A Verifier scores one completed Episode. The function sees the final
Observation, the full internal State, the trajectory, artifacts, and usage.
State is never shown to the Agent.

```python
from plural import DeterministicVerifier, Episode, VerifierOutput

def solved(episode: Episode) -> VerifierOutput:
    guesses = episode.state.get("guesses") or []
    return VerifierOutput(
        reward=float(bool(episode.observation.get("solved"))),
        scores={"guesses": float(len(guesses)), "tokens": float(episode.usage.total_tokens or 0)},
        evidence=[f"{len(guesses)} guesses"],
    )

verifier = DeterministicVerifier(name="solved", check=solved)
```

YAML stores a resolvable reference or a command:

```yaml
kind: deterministic
name: solved
check:
  python: verify.py:solved
```

A command argv remains valid for existing command verifiers.

## Bind time

`Task(..., environment=env, verifiers=[verifier])` fails unless the Environment
can run and each Verifier `check` is a callable, a `path.py:object` reference,
or a command. The error names the Task, the Environment, the Verifier, the
rule, and the fix.

## When to use which kind

- **DeterministicVerifier** — a function or command over the Episode. Use this
  when the score is exact.
- **AgentVerifier** — a catalog model that judges the Episode against criteria.
  Agent judges receive the same Episode. They need network unless you set
  `network="no-network"`.
- **HumanVerifier** — a rubric for a person to score after the Trial.

Verifier Runtime defaults to a public network, independent of the Environment.
