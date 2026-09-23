---
route: /docs/architecture/evaluation-contract
title: Evaluation contract
order: 1900
description: Maintainer contract for the public evaluation domain, lifecycle, auditability, and parity between Python, project files, and the CLI.
audience: maintainers
nav: false
---
# Evaluation contract

This document is the implementation contract for Plural's evaluation foundation.
The Python SDK defines the semantics. A project stores each resource as a
directory with a YAML manifest, and the CLI loads, validates, pushes, and runs
those same objects.

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

| Concept | Python | Manifest | CLI noun | Identity |
| --- | --- | --- | --- | --- |
| Environment | `Environment` | `environments/<name>/environment.yaml` | `env` | name, version, content hash |
| Runtime | `Runtime` | `runtime:` in `environment.yaml` | none | content hash |
| Agent | `Agent` | `agents/<name>/agent.yaml` | `agent` | name, version, content hash |
| Harness | `Harness` | `harnesses/<name>/harness.yaml` | `harness` | name, version, content hash |
| Verifier | `DeterministicVerifier`, `AgentVerifier`, `HumanVerifier` | `verifiers/<name>/verifier.yaml` | `verifier` | name, version, content hash |
| Task | `Task` | `tasks/<name>/task.yaml` | `task` | name, version, content hash |
| Benchmark | `Benchmark` | `benchmarks/<name>/benchmark.yaml` | `benchmark` | name, required semantic version, content hash |
| Job | `Job` | none; output only | `run`, `job` | a new id for every run |
| Trial | returned by a Job | none; output only | `trial` | Agent, Task, independent attempt |

Shareable definitions use `name` and `version`. Versions are ordinary semantic
versions such as `1.0.0`; protocol and schema versions never appear in public
names or constructors. Environment, Agent, Verifier, and Task default to
`0.1.0`. A Benchmark requires an explicit version because it is the unit users
push, compare, and share.

## Ownership

- An Environment owns its overview and README, typed State and Observation,
  actions, transition Rewarders, shared resources, secret references, Runtime,
  Harness policy, limits, and rendering output.
- A Runtime owns the image or build, compute, filesystem, network, runtime
  variable declarations, persistence, and placement constraints. Secret values
  are never serialized.
- An Agent owns a catalog model ID, instructions, optional provider preference,
  optional Harness, and metadata. It does not own an Environment or Task.
- A Harness is one optional Agent execution strategy. Packaging, binding,
  capability grants, and digests are derived internally from that one value.
- A Verifier owns its information, criteria, evidence requirements, Runtime,
  and `check` behavior. Deterministic, agent, and human Verifiers share one
  result contract.
- A Task owns instructions, goals, information, metadata, one Environment,
  Verifiers, task resources, initial state, and reset options.
- A Benchmark owns an ordered list of pinned Tasks, its scoring rules, and its
  primary metric, which is always the Verifier `score`.
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
5. produce the Agent-visible observation, the only part of the transition the
   model sees;
6. run every declared Rewarder against the transition and record the reward on
   the episode, never in the model's context;
7. repeat until the Environment terminates or truncates, the Agent finishes, or
   a budget truncates the episode;
8. persist the trajectory, state, observation, rendering, logs, and artifacts;
9. run Task Verifiers against filtered evidence;
10. aggregate scores into the Trial and Benchmark result.

Rewarders credit one transition and are recorded on the episode in every mode;
`Trial.step_reward_total` is the episode's total. Verifiers assess completed
Trials and are the only source of a score, and a reward never contributes to
one. They do not share lifecycle hooks or result types. An episode's stop reason
is one of `plural.STOP_REASONS`.

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
hash in order. Pushing the same Benchmark name and version with different
content fails. Adding, removing, updating, or reordering Tasks requires a new
Benchmark version.

`Benchmark.diff(other)` is the single structured diff and reports added,
removed, updated, reordered, and configuration changes. The SDK, hosted API,
and web app use this same result. `Benchmark.export()` returns the Benchmark and its
complete pinned dependency graph. There are no floating task queries, nested
Benchmarks, inheritance, or mutable pushed revisions. Sharing a Benchmark on the
public Hub is a separate, explicit publication described in
[Benchmark publications](benchmark-publications.md).

## SDK, project files, and CLI parity

Python objects and project directories resolve to the same frozen execution
graph. `plural.project.Workspace` loads a resource directory into the same
public object a Python caller would construct, and `plural run` builds an
ordinary `Job` from it.

- Python field names, defaults, nesting, and validation define the contract.
- Manifests use those exact names and values. There is no separate `TaskFile`,
  `BenchmarkFile`, or `JobFile` domain, and no Job manifest: every run creates
  a new Job.
- Resources refer to one another by name within a project. A run pins every
  input to its version and content hash, and a pushed revision pins each
  dependency by revision id.
- CLI flags only select resources or explicitly override SDK fields such as
  attempts and concurrency. The CLI has no independent defaults or validators.
- The SDK and the hosted service compute the same content hash, so pushing
  unchanged content reuses the existing revision. A push is private to its
  project; public sharing is always a separate action.
- Package JSON Schema, CLI help, and field documentation are generated from SDK
  model metadata.

## Beginner flow

From inside the Wordle example project, Python objects and project resources
combine freely:

```python
from plural import Agent, Benchmark, Job, Task
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
task = Task(
    name="easy-01",
    instructions="Guess the hidden word.",
    environment=workspace.get("env", "wordle"),
    verifiers=[workspace.get("verifier", "solved")],
    initial_state={"secret": "crane"},
)
benchmark = Benchmark(name="wordle", version="1.0.0", tasks=[task])
agent = Agent(model="openai/gpt-5.6-luna", instructions="Solve efficiently.")
result = Job(benchmark, agents=[agent]).run()
```

The equivalent project directories use the same field names and values. An
Agent with no Harness uses `native`; a custom Harness is one additional value on
the Agent. Advanced runtime, routing, hosted, and
training options are introduced only when needed.

## Implementation rules

- Keep content locks, capability preflight, sandbox isolation, evidence
  filtering, retries, resume, redaction, and structured events.
- Prefer the smaller coherent API over speculative extension points.
- Internal specs may retain protocol versions and detailed bindings, but those
  names are not exported from `plural`.
- Generated files are regenerated from code and never edited as a source.
- The standalone package must pass its release gate before hosted code changes.
