# Glossary

| Term | Meaning |
| --- | --- |
| **Environment** | Primary object: instructions, native actions, schemas, guardrails, resources, runtime. |
| **Native action** | Environment-owned action that returns an observation. |
| **Harness** | Prebuilt loop that can be stamped onto an environment. |
| **Stamp** | Frozen granted/denied capability set for one harness on one environment revision. |
| **Model** | The LLM. |
| **Agent template** | Immutable Model + Environment, optionally + stamped Harness. |
| **Agent instance** | Template plus hosted memory, skills, data, and experience. |
| **Task** | One unit of work on an environment. |
| **Benchmark** | Ordered grouping of tasks. |
| **Job** | Group of trials. |
| **Trial / episode** | One agent run on one task. |
| **Trace** | Record of turns, reasoning, actions, and observations. Schema 2.0.0. |
| **Turn** | One model step inside a trace. |
| **ActionStep** | One action invocation plus the observation it returned. |
| **EffectivePolicy** | Five-layer intersection used at preflight. |
| **CapabilityError** | Unsatisfiable requirement, named with a blame layer, raised before launch. |
