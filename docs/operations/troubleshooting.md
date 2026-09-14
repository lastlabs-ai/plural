---
route: /docs/operations/troubleshooting
title: Troubleshooting
order: 260
description: Find the failing stage and resolve installation, policy, execution, or scoring problems.
audience: all
nav: true
nav_group: Operations
outcome: You can diagnose a run without confusing a runtime failure with a low score.
---
# Troubleshooting

Start by identifying the stage that failed: installation, graph validation, runtime preflight, Agent execution, scoring, or review. Retrying a configuration error rarely helps.

## The command is missing or belongs to another version

Activate the environment where Plural is installed. Run
`python -m pip show plural` and `plural --help`, then compare with the
[generated CLI reference](../reference/cli-commands.md).

## A YAML field is rejected

Public models reject unknown fields. Environment cannot own Tasks, Verifiers,
or mode. Task uses `instructions` and `goals`; eval/train mode belongs on Job.
See the generated [field catalog](../reference/fields.md).

## A referenced file cannot be found

Paths in Task, Benchmark, and Job files resolve relative to the file that contains them. Check the containing directory and filename. An absolute path on your laptop is not automatically available in a remote sandbox.

## A verifier fails at bind time or scoring

Constructing `Task(..., environment=..., verifiers=...)` fails unless the
Environment is packaged and each DeterministicVerifier `check` is a function
(or a resolvable `path.py:object` / command) that accepts an `Episode`. The
function receives the full final observation, State, trajectory, artifacts,
and usage. If the function returns the wrong shape, the Trial fails closed
with a message that names the Verifier and the expected `VerifierOutput`.

## The runtime cannot enforce a policy

Inspect `ProviderRegistry().doctors(include_unavailable=True)`. The local
provider cannot block networking or enforce resource limits. Docker does not
support restricted allowlists. Daytona cannot consume a local build context.
Use a provider that supports the requirements; do not weaken policy silently.

## The model cannot authenticate or connect

Live Jobs need `Job(..., client=Client())` or `api_key=`. After
`plural auth login`, `plural run` injects an authenticated Client. Check the
selected model ID and endpoint: a direct provider may accept a different ID
from a multi-provider gateway.

`OPENAI_BASE_URL` configures the native compatible model endpoint; `PLURAL_GATEWAY_URL` takes precedence when set. Model connectivity is separate from the hosted project API endpoint. `--offline` does not block network requests.

## The native loop stops at its turn limit

Read the trajectory. The model may be repeating an invalid action or failing to
produce a final response. Fix action feedback and Task stopping instructions
before raising the budget. The support tutorial requires inspection,
categorization, response drafting, and resolution.

## The verifier script or result is missing

Supply the implementation named by `check`. Imported modules and data are not
automatically available in the Verifier Runtime. The scorer must write its
declared result path as valid JSON and include evidence when required.

## Execution succeeded but reward is zero

That can be a legitimate evaluation outcome. Inspect the final state and verifier feedback. A correctly executed agent can still choose the wrong category. Preserve zero-scoring completed Trials in your comparison.

## A review is pending

Use `plural review list JOB_ID` for local Jobs or `plural review hosted-list` for
hosted assignments. Submit all required criteria in their declared ranges. A
pending human score withholds the final reward; it is not a runtime timeout.

## Train mode reports unsupported TITO

The selected Harness cannot supply exact token capture. Use eval mode for
ordinary transcripts, or implement the required token record and artifact
contract in a compatible Harness. Do not declare `tito` without the
implementation.

## A Harness digest no longer matches

The package changed after its Agent binding was created, or the wrong source was materialized. Rebuild the intended package and update the binding deliberately. Keep generated files out of the source tree. Do not bypass integrity checks to make a stale comparison run.

## Local results do not appear in Plural Intel

A local store and a hosted Job are separate. A trace ID alone does not upload the trace or artifacts. Use the supported synchronization or hosted submission workflow, with materializable sources, project credentials, and policy-compatible runtimes.

## There is no deterministic replay

Reading a stored trajectory is different from rerunning a model or external
service. Revisions identify the experiment; they cannot guarantee identical
model outputs or remote state. See [Trials and trajectories](../running/trials.md).
