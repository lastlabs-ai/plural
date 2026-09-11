---
route: /docs/concepts/environment
title: "Environment"
order: 120
description: "Learn what an Environment revision owns, how observations differ from hidden state, and how runtime placement applies to every Trial."
audience: all
---
# Environment

`EnvironmentDefinition` is a revisioned execution world. It owns:

- overview, readme, and metadata;
- native actions;
- typed hidden state and observable schemas;
- train-only Rewarders;
- guardrails, resources, and secret references;
- runtime provider, placement, image/build, network, compute, and limits;
- the policy ceiling for an optional Agent Harness.

It intentionally does not own Tasks, Verifiers, or Job mode.

## Revision edges

A Task pins one complete Environment revision and weighted Verifier revisions.
AgentDefinition remains independent. During Job planning, optional Harness
compatibility is resolved against each Task Environment and frozen per Trial.

Because a Benchmark can select Tasks from different Environments, one Job may
schedule Trials across multiple providers and placements. The Job controls
bounded scheduling and retry only; it cannot replace Environment runtime
policy.

## Modes

Eval mode ignores Environment Rewarders and disables TITO capture while still
running Task Verifiers. Train mode enables Rewarders and requires exact
artifact-backed TITO support.

```bash
plural env init environment --name support
plural env validate environment
plural env show environment
```

See [native actions](native-actions.md),
[execution capabilities](execution-capabilities.md), and
[Environment authoring](../guides/write-environment.md).
