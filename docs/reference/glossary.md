---
route: /docs/reference/glossary
title: "Glossary"
order: 220
description: "Short definitions for the objects you author and the records a Job produces."
audience: all
nav: true
nav_group: Reference
---
# Glossary

| Term | Meaning |
| --- | --- |
| **Environment** | The world: actions, hidden state, observation, Rewarders, resources, secrets, runtime. |
| **Action** | An Environment command that returns an observation. |
| **Harness** | Agent-side wrapper around the LLM: loop, tools, how it calls Environment actions. |
| **HarnessGrant** | Per-Trial tool policy: which harness capabilities are granted or denied. |
| **EvidenceContract** | Artifacts and paths a Verifier needs from the Environment. |
| **Agent** | Model, instructions, routing, optional Harness. Not bound to an Environment. |
| **Task** | Instructions and public info that pin one Environment and weighted Verifiers. |
| **Verifier** | Deterministic, agent-judge, or human scorer. Own runtime. |
| **Benchmark** | Ordered Tasks, possibly across Environments. |
| **Job** | Task or Benchmark × Agents × attempts, plus mode and scheduling. |
| **Trial** | One Agent × Task × attempt. |
| **Trace** | The episode record: turns, observations, artifacts, Verifier results. |
| **Review** | A human Verifier pause at `awaiting_review`. |
| **Rewarder** | Train-only signal on the Environment. Ignored in eval. |
