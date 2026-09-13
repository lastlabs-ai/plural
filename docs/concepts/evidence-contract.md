---
route: /docs/concepts/evidence-contract
title: "Evidence contract"
order: 145
description: "A Verifier declares the Environment observation, state, and artifacts it needs. Pin-time rejects a Task that cannot satisfy those paths."
audience: all
nav: false
---
# Evidence contract

Verifiers are reusable. They must not silently score the wrong world.

Every Verifier kind carries an `EvidenceContract`:

- `artifacts` — Trial files the scorer needs (load alias:
  `required_artifacts`)
- `observation_paths` / `state_paths` — JSON pointers into
  `observation_schema` / `state_schema`
- `include_hidden_state` — verifier sandbox only; never sent to the Agent

## Pin-time

`Task` rejects a Verifier when a path is absent from the Environment schemas.
An irrelevant Verifier is a validation error, not a zero at runtime.
`plural validate REF` runs the same check.

## Runtime

`.plural/verifier-input.json` includes `environment_view: {observation,
state}` filtered to the contract. Hidden fields never enter
the Task's Agent-visible payload or the Agent tool prompt. Agent-judge
prompts and the human review queue receive the same view.
