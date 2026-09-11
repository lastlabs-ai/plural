---
route: /docs/quickstart
title: "Quickstart: plan a schema-v2 evaluation"
order: 30
description: "Plan a complete schema-v2 evaluation graph locally, then inspect its deterministic Job and Trial identities."
audience: all
---
# Quickstart: plan a schema-v2 evaluation

Install Plural, then create a complete typed graph without credentials:

```python
from plural import (
    AgentBinding,
    AgentDefinition,
    DeterministicVerifier,
    EnvironmentDefinition,
    JobSpec,
    TaskDefinition,
    TaskJobSource,
    WeightedVerifier,
)

environment = EnvironmentDefinition(name="offline")
verifier = DeterministicVerifier(
    name="correct",
    command=("python", "verify.py"),
)
task = TaskDefinition(
    task_id="hello",
    instructions="Return a greeting.",
    environment=environment,
    verifiers=(WeightedVerifier(verifier=verifier),),
)
agent = AgentDefinition(name="candidate", model="openai/gpt-4.1-mini")
job = JobSpec(
    source=TaskJobSource(task=task),
    agents=(AgentBinding(agent=agent),),
    mode="eval",
)

plan = job.plan()
print(plan.job_id, plan.trial_count)
```

The Environment owns runtime placement, network, actions, typed state and
observation, resources, secrets, and train-only Rewarders. The Task pins that
Environment and one or more weighted Verifier revisions. The Agent is not
Environment-bound.

To author the same graph with YAML:

```bash
plural env init environment --name offline
plural verifier init verifier.yaml --name correct
plural task init task.yaml --id hello \
  --environment environment --verifier verifier.yaml
plural agent init agent.yaml --model openai/gpt-4.1-mini
plural run task.yaml --agent agent.yaml --mode eval --dry-run
```

Use `plural job watch JOB_ID --json` for durable events. Retries append
TrialExecutions beneath a Trial. Human Verifiers yield `awaiting_review`.

Eval mode disables Rewarders and TITO capture but runs final Verifiers. Train
mode enables Rewarders and requires exact TITO support; records are stored as
hashed artifacts.

Continue with the [Python walkthrough](tutorials/sdk-walkthrough.md) or
[CLI walkthrough](tutorials/cli-walkthrough.md).
