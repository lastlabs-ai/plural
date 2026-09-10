---
route: /docs/guides/write-environment
title: "Write a schema-v2 Environment"
order: 250
description: "Author a typed schema-v2 Environment with actions, hidden state, observations, resources, runtime placement, and immutable manifests."
audience: all
---
# Write a schema-v2 Environment

An `EnvironmentManifest` is an immutable revision of the world in which a
Trial runs. It owns:

- overview and readme;
- native actions;
- typed hidden state and observation schemas;
- train-only Rewarders;
- resources, secrets policy, guardrails, and limits;
- runtime provider, placement, image/build, network, and compute.

It does not own Tasks, Verifiers, or Job mode.

```python
from plural import Environment, Observation, State, action, hidden

class SupportState(State):
    order_status: str = hidden("")

class SupportObservation(Observation):
    order_id: str = ""

class SupportEnvironment(Environment[SupportObservation, SupportState]):
    name = "support"
    revision = "1.0.0"
    overview = "Order lookup runtime."

    @action
    def lookup_order(self, order_id: str) -> dict[str, str]:
        """Look up an order."""
        return {"order_id": order_id, "status": self.state.order_status}

environment = SupportEnvironment().manifest()
```

The digest covers the canonical revision and source digest. Changing runtime,
action schemas, Rewarders, or any other owned field creates a new identity.

## Connect a Task

Create Verifiers independently, then pin them and the Environment on a Task:

```python
from plural import TaskDefinition, WeightedVerifier

task = TaskDefinition(
    task_id="order-a100",
    revision="1.0.0",
    instructions="Return the order status.",
    info={"order_id": "A100"},
    environment=environment,
    verifiers=(WeightedVerifier(verifier=correctness),),
)
```

`info` and metadata are public Agent input. Keep evaluator secrets in
Environment hidden state, secret references, or Verifier-controlled storage.

## Runtime placement

Every Trial uses the runtime on its Task's Environment. A Job cannot replace
provider, placement, network, or resource policy. Cross-Environment Benchmarks
therefore schedule across each selected runtime while respecting global and
per-runtime concurrency bounds.

Use `plural env init`, `plural env validate`, and `plural env show` for the
canonical YAML representation.
