# Run evaluations in CI

Start with a working local [SDK evaluation](../tutorials/sdk-walkthrough.md) or
[package job](../tutorials/cli-walkthrough.md). Commit the source, task definitions,
and intended package references. Keep credentials in your CI system's secret
settings and store results as CI artifacts.

## SDK regression checks

The support tutorial writes `report.json`. Keep a reviewed `baseline.json` and
run its comparison snippet after the evaluation. `Report.compare` checks task,
environment, and runtime compatibility where provenance is available. Reject
unexpected incompatibility instead of silently disabling the check.

For a routine job:

```bash
python compare_support.py
python check_regression.py
```

Save the tutorial's comparison snippet as `check_regression.py`. Install the
same package version and project dependencies in CI as in the baseline run.
Use fixed task versions and sufficient repeats. Investigate failure counts as
well as mean reward; a passing threshold should not hide missing cases.

## Package execution checks

Inject `PLURAL_API_KEY`, `PLURAL_GATEWAY_URL`, and, for hosted sync,
`PLURAL_PROJECT`. Start with validation:

```bash
plural env validate environment
plural harness validate harness
plural benchmark validate benchmark.yaml --environment environment
plural run job.yaml --dry-run --format json > plan.json
plural runtime doctor docker
```

Run the reviewed package using a Docker-capable runner:

```bash
plural run job.yaml --runtime docker --unsafe-local --format json > result.json
```

The local-source flag is for the reviewed mutable harness used in the tutorial.
For release evaluations, bind a digest-pinned archive instead; follow
[harness packaging](harnesses.md). Your runner must be able to reach the model
endpoint, and its runtime image must contain required dependencies.

Persist `.plural/jobs`, `plan.json`, and `result.json` even on failure. These
files can contain task data and artifacts; apply the same retention and access
rules as your inputs. Avoid putting generated reports inside the hashed
source package directories.

## Exit status is not a score gate

Exit `0` means the command completed; dry runs and successful unscored runs
also return zero. Exit `1` means at least one trial did not succeed. Exit `2`
means a usage/configuration/handled error; interrupted execution returns `130`.

For scored jobs, add your own reward threshold check over the stored report.
Use `JobStore.load_spec`, `read_job_result`, and `Job.report` from the
[Python job guide](../sdk/package-jobs.md), then inspect case failures and
rewards or compare with a compatible baseline. Missing scores should fail a
quality gate that requires scoring.

## Upload without losing local evidence

Use `--sync` only when the CI job should publish to Plural Intel. A sync failure
is best-effort and does not necessarily make local execution fail. If publication
is required, verify the hosted record and benchmark run after the upload.
Recover with `plural job upload JOB_ID` from the retained store.

Use `job resume` / `job retry` for interrupted execution of the same locked
configuration. Do not edit a stored lock to make a changed task set resume.
See [job recovery](jobs.md) and [sync](studio-sync.md).
