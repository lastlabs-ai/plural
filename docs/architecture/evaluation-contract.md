---
route: /docs/architecture/evaluation-contract
title: Evaluation contract
order: 1900
description: Maintainer contract for the public evaluation domain, lifecycle, auditability, and Python-YAML-CLI parity.
audience: maintainers
nav: false
---
# Evaluation contract

This document is the implementation contract for Plural's evaluation foundation.
The Python SDK defines the semantics. YAML is its lossless, human-editable
serialization, and the CLI loads and runs the same objects.

## Product boundary

Plural models a reusable progression:

1. define an Environment and its Tasks;
2. compare catalog-backed Agents on a versioned Benchmark;
3. use the resulting quality, cost, and latency evidence for routing;
4. train against the same Environment and Tasks when no Agent is sufficient;
5. rerun the Benchmark to measure improvement.

This package implements the evaluation foundation. Gateway policy and training
algorithms consume its records but are not part of its public domain model.

## Public concepts

| Concept | Python | YAML `kind` | CLI noun | Identity |
| --- | --- | --- | --- | --- |
| Environment | `Environment` | `environment` | `environments` | name, version, content hash |
| Runtime | `Runtime` | nested | nested | content hash |
| Agent | `Agent` | `agent` | `agents` | name, version, content hash |
| Harness | `Harness` | `harness` | `harness` | name, version, content hash |
| Verifier | `DeterministicVerifier`, `AgentVerifier`, `HumanVerifier` | `verifier` | `verifiers` | name, version, content hash |
| Task | `Task` | `task` | `tasks` | name, version, content hash |
| Benchmark | `Benchmark` | `benchmark` | `benchmarks` | name, required semantic version, content hash |
| Job | `Job` | `job` | `jobs` | hash of source, Agents, mode, and attempts |
| Trial | returned by a Job | output only | `trials` | Agent, Task, independent attempt |

Shareable definitions use `name` and `version`. Versions are ordinary semantic
versions such as `1.0.0`; protocol and schema versions never appear in public
names or constructors. Environment, Agent, Verifier, and Task default to
`0.1.0`. A Benchmark requires an explicit version because it is the unit users
publish, compare, and share.

## Ownership

- An Environment owns its overview/readme, typed state and observation, actions,
  transition Rewarders, shared resources, Runtime, limits, and rendering output.
- A Runtime owns image/build/OS, compute, filesystem, network, named secret
  references, persistence, and placement constraints. Secret values are never
  serialized.
- An Agent owns a catalog model ID, instructions, optional provider preference,
  optional Harness, and metadata. It does not own an Environment or Task.
- A Harness is one optional Agent execution strategy. Packaging, binding,
  capability grants, and digests are derived internally from that one value.
- A Verifier owns its information, criteria, evidence requirements, Runtime,
  and `check` behavior. Deterministic, agent, and human Verifiers share one
  result contract.
- A Task owns instructions, goals, information, metadata, one Environment,
  Verifiers, task resources, initial state, and reset options.
- A Benchmark owns an ordered list of pinned Tasks and its primary metric.
- A Job owns a Task or Benchmark source, Agents, eval/train mode, attempts,
  concurrency, and retry policy.
- A Trial is one Agent × Task × independent attempt. Runtime retries are Trial
  executions and do not change Trial identity.

## Lifecycle

An Environment episode follows one transition pipeline:

1. bind the Task and validate task resources and initial state;
2. reset the Environment;
3. invoke an Agent action;
4. update Environment state;
5. produce the Agent-visible observation;
6. run matching transition Rewarders in train mode;
7. repeat until terminal, truncated, or limited;
8. persist the trajectory, state, observation, rendering, logs, and artifacts;
9. run Task Verifiers against filtered evidence;
10. aggregate scores into the Trial and Benchmark result.

Rewarders provide transition-level training signals. Verifiers assess completed
Trials. They do not share lifecycle hooks or result types.

## Model catalog

`Agent.model` is a stable ID in the effective `ModelCatalog`. The effective
catalog is the bundled snapshot plus explicit project entries. A custom model
or endpoint must be registered before use.

An optional provider preference is valid only when that provider is a trusted,
configured endpoint for the selected model. Loading catches unknown
model/provider combinations; execution preflight checks current reachability,
credentials, and policy. Job locks and Trial receipts record the catalog model
and resolved endpoint used.

## Benchmark auditability

A Benchmark version is immutable. It pins each Task's name, version, and content
hash in order. Publishing the same Benchmark name and version with different
content fails. Adding, removing, updating, or reordering Tasks requires a new
Benchmark version.

`Benchmark.diff(other)` is the canonical structured diff and reports added,
removed, updated, reordered, and configuration changes. SDK, CLI, hosted API,
and UI use this same result. Exports include the Benchmark and its complete
pinned dependency graph. There are no floating task queries, nested
Benchmarks, inheritance, or mutable published versions.

## SDK, YAML, and CLI parity

All three entry points resolve to the same frozen execution graph:

```text
Python object ─┐
YAML file ─────┼─> one loader/resolver/validator ─> frozen graph ─> Job
CLI overrides ─┘
```

- Python field names, defaults, nesting, and validation define the contract.
- YAML uses those exact names and values. It has no separate `TaskFile`,
  `BenchmarkFile`, or `JobFile` domain.
- CLI flags only select objects or explicitly override SDK fields. The CLI has
  no independent defaults or validators.
- Inline objects and file references use one resolver. Published objects are
  replaced by immutable name/version/hash pins in locks.
- Python → YAML → Python preserves semantic equality and content hashes.
- JSON Schema, CLI help, and field documentation are generated from SDK model
  metadata.

## Canonical beginner flow

```python
from plural import Agent, Benchmark, Job, Task
from plural.verifiers import DeterministicVerifier

solved = DeterministicVerifier(name="solved", check="python verifier.py")
task = Task(
    name="easy-01",
    instructions="Solve the puzzle.",
    environment=Wordle(),
    verifiers=[solved],
)
benchmark = Benchmark(name="wordle", version="1.0.0", tasks=[task])
agent = Agent(model="openai/gpt-5.6-luna", instructions="Solve efficiently.")
result = Job(benchmark, agents=[agent]).run()
```

The equivalent YAML uses the same field names and values. A custom Harness is
one additional value on the Agent. Advanced runtime, routing, hosted, and
training options are introduced only when needed.

## Implementation rules

- Keep content locks, capability preflight, sandbox isolation, evidence
  filtering, retries, resume, redaction, and structured events.
- Prefer the smaller coherent API over speculative extension points.
- Internal specs may retain protocol versions and detailed bindings, but those
  names are not exported from `plural`.
- Generated files are regenerated from code and never edited as a source.
- The standalone package must pass its release gate before hosted code changes.
