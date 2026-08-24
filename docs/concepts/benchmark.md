# Benchmark

A `Benchmark` runs the same environment tasks across model or policy targets and returns aggregate statistics plus reproducible per-case provenance.

```python
from enroute import Benchmark, TaskDataset

dataset = TaskDataset.load("data/refund-tasks.jsonl")
report = Benchmark(
    env,
    models=["openai/gpt-4o-mini", "anthropic/claude-sonnet-4"],
    client=client,
    repeats=3,
    concurrency=8,
).run(dataset=dataset)
```

`dataset=` accepts `TaskDataset`, not a trace `Dataset`. You can alternatively pass `tasks=[...]`, or omit both to use `env.iter_tasks()`.

## Cases and provenance

Every `(target, task_id, repeat)` job produces a `CaseResult`. Successful cases include trace/episode ids and kind, stop reason, reward and named scores, episode metrics, terminal flags, and the runtime fingerprint used for that case. Failed cases retain `failure_type`, `failure_message`, and runtime fingerprint when runtime construction completed.

Case order follows target, task order, then repeat; it does not depend on concurrent completion order. `RunManifest` records run timestamps/status, the actual worker environment name/version/fingerprint, runtime fingerprints, ordered targets and task ids, repeats, concurrency, package version, and task provenance.

`task_set` always includes an order-sensitive content hash and identifies whether tasks came from a `TaskDataset`, an explicit list, or `env.iter_tasks()`. `task_dataset` retains the named dataset identity when applicable. `Report.manifest` is optional so reports written before manifests existed still load.

## Aggregates

`ModelStats` reports:

- successful `n`, `failures`, and failure counts by exception type;
- mean reward and named scorer means;
- sample reward standard deviation and descriptive normal-approximation 95% interval;
- mean/p50/p95 **episode-total** latency;
- mean and total **episode-total** model cost.

The uncertainty fields are descriptive summaries, not significance tests. They are `None` when fewer than two rewards are available.

## Correctly paired win rates

Pairwise win rates align models by the same `(task_id, repeat)` slot. They do not compare results by thread completion order. Ties contribute half a win:

`win_rate = (wins + 0.5 × ties) / compared`

If either aligned case failed or has no reward, that slot is excluded. `WinRatePair` exposes `wins`, `losses`, `ties`, `compared`, and `excluded`, so the denominator is auditable.

## Arbitrary synchronous policies

Use factories when targets are not Enroute model ids:

```python
report = Benchmark.from_policies(
    env,
    {
        "rules-v1": lambda: RulesPolicy(),
        "scripted": lambda: ScriptedPolicy([...]),
    },
    repeats=2,
    concurrency=4,
).run(dataset=dataset)
```

Each job calls its factory and receives a fresh policy instance. This prevents mutable policy state from leaking across tasks or repeats.

## Fresh environments and runtimes

By default each job uses `env.spawn()`. Its generic reconstruction cannot safely reproduce required subclass constructors or stateful dynamic tools, scorers, or task-provider closures that capture the original environment. Override `spawn()` or pass a factory:

```python
benchmark = Benchmark.from_policies(
    template,
    {"rules": lambda: RulesPolicy()},
    environment_factory=lambda: SupportEnv(ruleset="2026-08"),
    runtime_factory=lambda: SandboxRuntime(image="support-tools:v3"),
)
```

Both factories run once per job. Use `runtime_factory` for a fresh sandbox, remote executor, or custom tool runtime. `Runtime.call(...)` remains a synchronous public-alpha extension point. Worker environments must report one consistent identity; runtime identities are collected in `manifest.runtime_fingerprints` and attached to individual cases. Default local identities cover registered tool implementations. Generic custom runtime identities cover the `call()` implementation and stable configured state unless an explicit `fingerprint()` is provided.

## Persist policy benchmark traces

`Benchmark.from_policies()` has no client writer. Its case trace ids identify in-memory results but are durable only when you supply `trace_writer=`:

```python
from enroute import JSONLSink, TraceWriter

writer = TraceWriter(JSONLSink("policy-episodes.jsonl"))
try:
    report = Benchmark.from_policies(
        env,
        {"rules": lambda: RulesPolicy()},
        trace_writer=writer,
    ).run(dataset=dataset)
finally:
    writer.close()
```

The writer records successful episode traces and failed episode traces produced after an episode starts. The caller owns the writer and must flush or close it.

## Regression comparison

`report.compare(baseline, tolerance=0.02)` compares mean rewards by matching target name. By default it first validates available environment fingerprints, runtime fingerprints, task-set hashes, ordered task ids, and repeats. Pass `allow_incompatible=True` only when that provenance mismatch is intentional. If either legacy report has no manifest, comparison proceeds using the reward data that is available.

A target is a regression only when its decrease is greater than the non-negative absolute `tolerance`. The result contains per-target deltas and a `regressions` list.
