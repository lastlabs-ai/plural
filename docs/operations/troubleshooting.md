---
route: /docs/operations/troubleshooting
title: "Troubleshooting"
order: 260
description: "Install, hosted access, runtime, and Job failures. Activate the environment where you installed Plural, or use uv run plural."
audience: all
nav: false
---
# Troubleshooting

## Setup and hosted access

**`plural` is not found.** Activate the virtual environment where you installed
Plural, or use `uv run plural`. Check `python -m pip show plural` in the same
environment. See [setup](../getting-started/setup.md).

**CLI login works, but `Client()` says no providers are configured.** The SDK
does not read the CLI credential store. Export `PLURAL_API_KEY` or pass
`api_key=`. For BYOK, pass `providers={...}` explicitly.

**I can call a model, but cannot fetch project objects.** Direct provider keys
do not authorize Plural Intel. Supply a Plural API key and, for an account key,
a project ID. Verify the SDK `base_url` separately from CLI `--api-url` and the
harness's `PLURAL_GATEWAY_URL`.

**`auth status` is successful, but the job cannot call a model.** The external
harness needs a granted secret name in its agent configuration and that secret's
value in the process environment. Stored device login is not automatically
forwarded. Confirm the harness endpoint and model ID too.

**Create returns a conflict.** The slug already exists in this project. Fetch
it and intentionally update it, or choose a new name. A failed update should
not automatically fall back to creating a second object.

**A fetched environment has no `rollout` method.** Hosted environment reads
return metadata dictionaries. Install the author's source to run locally, or
restore complete package definitions and matching sources when supplied. See
[object retrieval](../guides/push-to-plural.md).

**`agent list` does not show my Intel agents.** The CLI lists local configuration
files. Use `client.agents.list()` for hosted agents. `org list` and `project list`
currently report unsupported backend functionality; use known project IDs.

## SDK results and traces

**Score is missing or zero.** No Verifier means no quality score. Zero means
the configured check did not award credit, not necessarily an execution
failure. Do not apply exact-answer verification to unlabeled production work
without changing how that case is evaluated.

**Trace content is blank.** Content capture is off by default. For approved
synthetic/debug data, set `capture_content=True`. Close/flush the client before
reading newly queued traces. A sampled-out trace will not be in the sink.

**Late labels did not update JSONL.** JSONL is append-only. Use SQLite for
persistent label updates by ID; flush pending trace writes before attaching a
label to an already-written record.

**A Trace dataset hash is stale.** Keep the JSONL file with its manifest and
save a new snapshot after intentional changes. Trace datasets are analysis
outputs, not Task or Benchmark Job sources.

**A custom environment cannot be copied for comparison.** Supply
`environment_factory=` or implement `spawn()` when your environment constructor
needs extra arguments or registered closures capture mutable state.

## Package execution

Start with package validation, a dry run, and provider health:

```bash
plural env validate environment
plural harness validate harness
plural verifier validate verifier.yaml
plural task validate task.yaml
plural benchmark validate benchmark.yaml
plural run job.yaml --dry-run
```

Common failures:

- **Revision identity is stale** — the Environment, Task, Verifier, Agent, or
  Harness changed. Recreate dependent revision files and then the Job source.
- **Harness source lock mismatch** — package files changed after binding.
  Rebuild/publish, add the new digest to the Environment, and recreate Agents.
- **`lock_incompatible`** — the same job ID/store contains a different complete
  config or lock. Do not edit stored files; use the original config or create a
  newly identified Job.
- **Local execution refused** — set provider `local`, `network: full`, and
  `allow_unsafe_local: true` on a trusted Environment, or use an isolated
  provider.
- **Missing declared harness secrets** — export every Agent-granted name. Do
  not add undeclared names to the Agent; add them to the package manifest and
  regenerate the binding.
- **Runtime unavailable/capability error** — install the optional dependency,
  start Docker, configure Daytona, or remove a requirement
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
- **Regrade refused** — every Trial needs a successful source receipt and
  pinned Verifier revisions.
- **Cancellation appears delayed** — in-process callers should invoke
  `await job.cancel()`; cancellation is not a CLI command.
- **Auth fails or expires** — confirm `--api-url`, use `--no-browser` when
  appropriate, and verify the service implements the documented device
  endpoints. Hosted publication/sync can refresh stored device credentials, but there is
  no general background refresh loop. Reauthenticate when auth checks expire.

Process exit `1` means a run returned at least one non-success Trial. Exit `2`
means usage/validation/configuration or another handled command error. Inspect
the JSON `error_code`, persisted attempt logs, receipt effective policy, and
provider diagnostics; avoid posting unredacted artifacts or config directories
in bug reports.
