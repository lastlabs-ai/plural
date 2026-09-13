---
route: /docs/operations/troubleshooting
title: Troubleshooting
order: 260
description: Find the failing stage and resolve installation, policy, execution, or scoring problems.
audience: all
nav: false
outcome: You can diagnose a run without confusing a runtime failure with a low score.
---
# Troubleshooting

Start by identifying the stage that failed: installation, graph validation, runtime preflight, Agent execution, scoring, or review. Retrying a configuration error rarely helps.

## The command is missing or belongs to an older version

Activate the environment where you installed the current source checkout. Run `python -m pip show plural` and `plural --help`. These docs use schema-v2 authoring commands; the public PyPI release can lag behind the checkout. Follow [Getting started](../getting-started.md) to install the matching source.

## A YAML field is rejected

Definitions reject unknown fields. Environment cannot own `tasks`, `verifier`, or `mode`. Task has `instructions`, not a separate `goal` field. Eval/train mode belongs on Job. See the [definition reference](../reference/definitions.md) and [migration guide](../migration/v1.md).

## A referenced file cannot be found

Paths in Task, Benchmark, and Job files resolve relative to the file that contains them. Check the containing directory and filename. An absolute path on your laptop is not automatically available in a remote sandbox.

## A verifier evidence path fails validation

Check the Environment's observation/state schema for the exact property. Use supported object paths and explicitly permit hidden state on the Verifier. Required artifact names are checked when the Trial produces artifacts, not inferred from schema properties.

## The runtime cannot enforce a policy

Run `plural providers doctor`. The local provider cannot block networking or enforce resource limits. The built-in Docker provider does not support restricted network allowlists. A cloud target cannot consume a local Docker build context. Use a provider that supports the requirements; do not silently weaken the policy.

## The model cannot authenticate or connect

The native Harness needs its declared secret granted on the Agent and supplied to the execution process. CLI device login does not automatically forward credentials to the model subprocess. Check the selected model ID and endpoint: a direct provider may accept a different ID from a multi-provider gateway.

`OPENAI_BASE_URL` configures the native compatible model endpoint; `PLURAL_GATEWAY_URL` takes precedence when set. Model connectivity is separate from the hosted project API endpoint. `--offline` does not block network requests.

## The native loop stops at its turn limit

Read the trajectory. The model may be repeating an invalid action or failing to produce a final response. Fix the action feedback and Task stopping instructions before simply raising the budget. The support starter resets the Environment for the Task, then needs categorize and a final confirmation.

## The verifier script or result is missing

`plural verifier init` writes a definition, not its implementation. Supply the script. A neighboring `python script.py` command can be inlined by the loader, but imported modules and data files are not automatically bundled. The scorer must write its declared result path as valid JSON and include evidence when required.

## Execution succeeded but reward is zero

That can be a legitimate evaluation outcome. Inspect the final state and verifier feedback. A correctly executed agent can still choose the wrong category. Preserve zero-scoring completed Trials in your comparison.

## A review is pending

Use `plural review list JOB_ID` for local Jobs or `plural review hosted-list` for hosted assignments. Submit all required rubric criteria in their declared ranges. A pending human score withholds the final reward; it is not a runtime timeout.

## Train mode reports unsupported TITO

The selected Harness cannot supply exact token capture. Use eval mode for ordinary transcripts, or implement the required token record and artifact contract in a compatible Harness. Do not fabricate token data or enable `supports_tito` without the implementation.

## A Harness digest no longer matches

The package changed after its Agent binding was created, or the wrong source was materialized. Rebuild the intended package and update the binding deliberately. Keep generated files out of the source tree. Do not bypass integrity checks to make a stale comparison run.

## Local results do not appear in Plural Intel

A local store and a hosted Job are separate. A trace ID alone does not upload the trace or artifacts. Use the supported synchronization or hosted submission workflow, with materializable sources, project credentials, and policy-compatible runtimes.

## There is no deterministic replay

Reading a stored trajectory is different from rerunning a model or external service. Revisions identify the experiment; they cannot guarantee identical model outputs or remote system state. See [Traces](../running/traces.md).
