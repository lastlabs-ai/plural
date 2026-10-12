# Harness execution examples

Run from the repository root:

```bash
uv run python examples/jobs/00_scaffold.py
uv run python examples/jobs/01_local_job.py
uv run python examples/jobs/02_docker_job.py
uv run python examples/jobs/03_daytona_job.py
uv run python examples/jobs/04_attempts_and_concurrency.py
uv run python examples/jobs/05_resume.py
uv run python examples/jobs/06_push_plan.py
```

All commands above are credential-free in their default mode. `02` and `03`
validate/plan but require `PLURAL_RUN_DOCKER=1` or
`PLURAL_RUN_DAYTONA=1` for external execution. `00` scaffolds a project in the
standard layout and shows what validation asks you to fill in. `05` demonstrates
durable resume without rerunning successful Trials. `06` previews, offline, the
private revisions `plural benchmark push --with-deps` would upload for the
first-project example, dependencies first.

`minimal_harness/` is a complete custom Harness: `harness.yaml` and a Harness class. Its `run` method receives
the standard Task, Agent, and Environment interfaces and returns a
`HarnessResult`; Plural writes the execution artifacts. `_foundation.py` builds
first-class Task and Verifier versions, an Environment-independent Agent, a
Benchmark source, and an Environment-routed Job.
