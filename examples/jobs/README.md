# Package execution examples

Run from the repository root:

```bash
uv run python examples/jobs/00_scaffold.py
uv run python examples/jobs/01_local_job.py
uv run python examples/jobs/02_docker_job.py
uv run python examples/jobs/03_daytona_job.py
uv run python examples/jobs/04_attempts_and_concurrency.py
uv run python examples/jobs/05_resume_and_regrade.py
uv run python examples/jobs/06_studio_sync.py
```

All commands above are credential-free in their default mode. `02` and `03`
validate/plan but require `PLURAL_RUN_DOCKER=1` or
`PLURAL_RUN_DAYTONA=1` for external execution. `05` demonstrates local resume;
setting `PLURAL_RUN_DOCKER=1` also runs verifier-only regrade because the local
provider cannot enforce the verifier's required no-network boundary. `06` only prints the legacy
Studio payload unless `PLURAL_RUN_STUDIO=1` is explicitly set.

`minimal_harness/` is a complete `plural-harness-v1` package. It reads one
request, writes one result plus evidence/trajectory artifacts, and emits one
terminal event. `_foundation.py` binds it to an Environment, Benchmark, Agent,
verifier, and provider-neutral Job.
