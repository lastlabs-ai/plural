# Run package jobs from Python

The CLI and this API use the same `JobSpec`, package bindings, trial identities,
and durable store. Start with the [CLI walkthrough](../tutorials/cli-walkthrough.md)
so `job.yaml` and its referenced files exist.

## Load and inspect without executing

```python
from pathlib import Path
from plural.cli.scaffold import load_job

spec = load_job(Path("job.yaml"))
plan = spec.plan()
print(plan.job_id, plan.trial_count)
for trial in plan.trials:
    print(trial.trial_id, trial.agent_name, trial.task_id, trial.attempt)
```

`plan()` validates identities and expands the task/agent matrix. It does not
check remote credentials, start a runtime, or call a model. Use the async
`Job.preflight()` to check runtime requirements before execution.

## Execute and save a report

For the trusted unverified local example, save `run_job.py`:

```python
import asyncio
from pathlib import Path
from plural import Job, JobSpec, JobStore
from plural.cli.scaffold import load_job

async def main():
    loaded = load_job(Path("job.yaml"))
    payload = loaded.model_dump(mode="json")
    payload["runtime"].update(provider="local", unsafe_local=True)
    spec = JobSpec.model_validate(payload)

    def progress(trial, result):
        print(trial.task_id, result.status)

    job = Job(spec, store=JobStore(Path(".plural/jobs")), progress=progress)
    await job.preflight()
    result = await job.run()
    report = job.report(result)
    Path("package-report.json").write_text(report.to_json(), encoding="utf-8")
    print(result.job_id)
    print(report.to_markdown())

asyncio.run(main())
```

This makes paid calls with the model-backed harness. It does not sync to Plural
Intel. In a notebook use `await main()`. For a verified job configure Docker or
Daytona in `job.yaml` and use the loaded specification unchanged; the local
provider cannot run an isolated verifier. A job without a verifier has no
quality reward even when execution succeeds.

## Construct a specification in code

You can keep configuration in Python instead of separate YAML files:

```python
from pathlib import Path
from plural import AgentBinding, AgentTemplate, BenchmarkDefinition, JobSpec, RuntimeSpec
from plural.cli.scaffold import load_environment

# These files come from the CLI tutorial. This is the native path: no harness.
environment = load_environment(Path("environment"))
template = AgentTemplate(
    name="candidate",
    model="openai/gpt-4o-mini",
    environment=environment.identity,
    secret_names=("PLURAL_API_KEY",),
)
benchmark = BenchmarkDefinition(
    name="support-smoke",
    environment=environment.identity,
    task_ids=tuple(task.task_id for task in environment.tasks),
)
spec = JobSpec(
    environment=environment,
    benchmark=benchmark,
    agents=(AgentBinding(template=template),),
    n_attempts=2,
    concurrency=2,
    per_agent_concurrency=2,
    runtime=RuntimeSpec(provider="docker"),
)
print(spec.plan().trial_count)
```

A stamped template also needs `harness`, `harness_package`, and a
`HarnessStamp` from `resolve_harness_stamp()`. Declared harnesses (`hermes`,
`claude-code`, `codex`, `cursor`) can be stamped but cannot run. The only
runnable executors are `native_chat_v1()` and `native_actions_v1()`. Local
execution additionally requires `environment.runtime.allow_unsafe_local=True`,
`LOCAL` in `targets`, and `RuntimeSpec(unsafe_local=True)` — or
`plural run --unsafe-local`. A frozen specification should be rebuilt and
validated when changed; do not alter identity fields merely to make a stale
dependency pass.

## Resume, cancel, and regrade

Use the job ID printed by the completed or interrupted run:

```python
import asyncio
from plural import Job, JobStore

async def resume(job_id):
    store = JobStore()
    spec = store.load_spec(job_id)
    return await Job(spec, store=store).run(resume=True)

# Replace with a stored ID before running:
# result = asyncio.run(resume("JOB_ID"))
```

`run(resume=True)` skips successful trials and resumes other trials under the
stored retry policy. `await job.cancel()` requests cancellation and cancels
active sandboxes owned by that Job instance. `await job.regrade()` reruns only
the locked verifier over existing artifacts. See [job operations](../guides/jobs.md)
for prerequisites and how the CLI equivalents differ.

`JobStore` provides `list_jobs()`, `load_spec()`, `load_lock()`,
`read_job_result()`, and `trial_results()` for local inspection. Advanced callers
can run a single `Trial`; prefer `Job` for scheduling, retries, and aggregation.

## Runtime and extension points

Pass `provider=` for a configured `SandboxProvider`, `registry=` for a provider
registry, or `environ=` to control the environment from which named secrets are
granted. Never serialize credential values into the job specification.
Use [provider plugins](../guides/provider-plugins.md) when implementing a new
execution backend. The [API reference](../reference/api.md) documents the full
models, store, and execution signatures.
