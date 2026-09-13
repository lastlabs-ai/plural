# Harness execution examples

Run from the repository root:

```bash
uv run python examples/jobs/00_scaffold.py
uv run python examples/jobs/01_local_job.py
uv run python examples/jobs/02_docker_job.py
uv run python examples/jobs/03_daytona_job.py
uv run python examples/jobs/04_attempts_and_concurrency.py
uv run python examples/jobs/05_resume.py
uv run python examples/jobs/06_studio_sync.py
```

All commands above are credential-free in their default mode. `02` and `03`
validate/plan but require `PLURAL_RUN_DOCKER=1` or
`PLURAL_RUN_DAYTONA=1` for external execution. `05` demonstrates durable resume
without rerunning successful Trials. `06` prints the canonical schema-v2 Job
graph for a compatible hosted API—the same graph an authenticated `plural run`
synchronizes before submitting and watching its hosted Job.

`minimal_harness/` is a complete custom Harness. It reads one
request, writes one result plus evidence/trajectory artifacts, and emits one
terminal event. `_foundation.py` builds first-class Task and Verifier versions,
an Environment-independent Agent, a Benchmark source, and an
Environment-routed Job.
