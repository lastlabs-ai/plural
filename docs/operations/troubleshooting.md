# Troubleshooting

Start with package validation, a dry run, and provider health:

```bash
plural env validate environment
plural harness validate harness
plural benchmark validate benchmark.yaml --environment environment
plural run job.yaml --dry-run
plural runtime doctor docker
```

Common failures:

- **Environment identity is stale** — tasks, instructions, policy, source, or
  another Environment field changed. Recreate the Benchmark and Agent pins,
  then recreate the Job file.
- **Harness source lock mismatch** — package files changed after binding.
  Rebuild/publish, add the new digest to the Environment, and recreate Agents.
- **`lock_incompatible`** — the same job ID/store contains a different complete
  config or lock. Do not edit stored files; use the original config or create a
  newly identified Job.
- **Local execution refused** — pass `--unsafe-local` only for trusted
  development code or use Docker/Daytona.
- **Missing declared harness secrets** — export every Agent-granted name. Do
  not add undeclared names to the Agent; add them to the package manifest and
  regenerate the binding.
- **Runtime unavailable/capability error** — run `runtime doctor`; install the
  optional dependency, start Docker, configure Daytona, or remove a requirement
  only if the security policy truly permits it.
- **Docker build/image failure** — verify the Environment Dockerfile works for
  UID 65532 and the harness command exists in/uploaded to the image. Daytona
  declarative images and snapshots cannot be used by Docker.
- **Restricted network rejected** — Docker/local do not implement allowlists;
  Daytona requires a non-empty domain/CIDR allowlist.
- **Harness protocol failure** — stdout must contain only valid protocol JSON
  lines ending in exactly one terminal event; logs belong on stderr. Result
  paths must be declared and created.
- **Evidence missing/verifier failed** — the harness omitted a required
  artifact, the verifier did not write its configured result path, emitted
  non-finite values/no evidence, timed out, or exited nonzero.
- **Resume does not rerun success** — expected behavior. Successful Trial IDs
  are reused; retries target non-successful Trials.
- **Regrade refused** — every Trial needs a successful source receipt and the
  Environment needs a verifier.
- **Cancellation appears delayed** — CLI `job cancel` writes a durable marker
  for pending launches but does not IPC into another active CLI. In-process
  callers should invoke `await job.cancel()`.
- **Hosted sync failed** — local results remain under `.plural/jobs`. Confirm
  authentication and API compatibility, then replay with
  `plural job upload <job_id> --store <path>`.
- **Auth fails or expires** — confirm `--api-url`, use `--no-browser` when
  appropriate, and verify the service implements the documented device
  endpoints. No client-side refresh loop is wired into CLI commands yet.

Process exit `1` means a run returned at least one non-success Trial. Exit `2`
means usage/validation/configuration or another handled command error. Inspect
the JSON `error_code`, persisted attempt logs, receipt effective policy, and
provider doctor output; avoid posting unredacted artifacts or config directories
in bug reports.
