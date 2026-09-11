---
route: /docs/reference/glossary
title: "Glossary"
order: 490
description: "Definitions for the canonical Plural SDK, execution, runtime, tracing, and hosted revision terminology."
audience: all
---
# Glossary

| Term | Meaning |
| --- | --- |
| **Environment** | Revisioned actions, typed hidden state/observation, Rewarders, resources, secrets, and runtime placement. |
| **Native action** | Environment-owned action that returns an observation. |
| **Harness** | Agent-side wrapper around the LLM (instructions, tools, loop). |
| **HarnessGrant** | Per-Trial tool policy: granted and denied harness capabilities. |
| **EvidenceContract** | Paths and artifacts a Verifier needs from an Environment. |
| **Stamp** | Per-Trial compatibility and capability result for a Harness against a Task's Environment. |
| **Model** | The LLM. |
| **AgentDefinition** | Revisioned model, instructions, routing, and optional Harness; never Environment-bound. |
| **Task** | Revisioned instructions/info that pin one Environment and weighted Verifier revisions. |
| **Verifier** | Independent deterministic, agent, or human final evaluator. |
| **Benchmark** | Ordered Task revision selection that may span Environments. |
| **Job** | Task-or-Benchmark source plus Agents, mode, attempts, scheduling, and retry policy. |
| **Trial / episode** | One Agent × Task × independent-attempt slot. |
| **TrialExecution** | One execution or retry under a Trial identity. |
| **ProgressEvent** | Durable append-only Job/TrialExecution state transition. |
| **Trace** | Semantic observations/actions plus pinned revisions, Verifier results, and artifact references. Schema 3.0.0. |
| **Turn** | One model step inside a trace. |
| **ActionStep** | One action invocation plus the observation it returned. |
| **EffectivePolicy** | Five-layer intersection used at preflight. |
| **CapabilityError** | Unsatisfiable requirement, named with a blame layer, raised before launch. |
