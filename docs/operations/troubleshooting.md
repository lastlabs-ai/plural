---
route: /docs/operations/troubleshooting
title: Troubleshooting
order: 260
description: Find what you are seeing, in plain words, and the fix for it, from missing commands and refused pushes to key errors and surprising scores.
audience: all
nav: false
nav_group: Operations
outcome: You can diagnose a run without confusing a runtime failure with a low score.
---
# Troubleshooting

Find the heading that matches what you are seeing, then follow the fix beneath it.

It helps to know *where* things went wrong, because a problem at one stage is never
fixed by retrying a later one. A run goes through these stages in order:

1. **Installation**: Plural itself is installed and on your path.
2. **Checking your files**: every resource and the links between them are valid.
3. **Preparing the Runtime**: the place the world runs can do what you asked.
4. **The Agent works**: the model takes its turns.
5. **Grading**: the Verifiers (the graders) score the finished work.
6. **Human review**, if a Task uses a human grader.

Retrying a configuration error rarely helps. Fix the file or setting the error names,
then run again.

> **Good to know:** a low score is not an error. If the run finished and the grader
> gave it a zero, the Agent did the work and got it wrong. See
> [The run finished but the score is zero](#the-run-finished-but-the-score-is-zero).

## Plural says a command does not exist

The command may be missing, or it may belong to an older version of Plural.

Activate the environment where Plural is installed. Run
`python -m pip show plural` and `plural --help`, then compare with the
[CLI command reference](../cli/evaluation.md#command-reference). Projects need
`plural>=0.18.0`.

### Removed commands

Plural 0.15 removed these commands and files:

- `plural init`, `plural validate`, `plural inspect`, and `plural export`: use
  `plural project init`, `plural <kind> validate`, and `plural <kind> show --json`.
- `plural <kind> publish`: a push makes a revision available; there is no
  publish step.
- `plural run FILE` and `job.yaml`: use `plural run -t|-b NAME -m MODEL|-a AGENT`.
- `plural job submit`, `plural job watch`, `plural trial list`, and
  `plural trial watch`: use `plural run --hosted --follow`, `plural job show`,
  and `plural trial show --follow`.
- `plural benchmarks`, `plural models show`, `plural schemas`, and
  `plural login|logout|status`: use `plural benchmark show`,
  `plural models list`, the downloadable
  [project-schemas.json](../assets/project-schemas.json), and
  `plural auth login|logout|status`.

See [Migrate to 0.15](../migration/projects.md) for the full mapping.

## Plural says this folder is not a project

Resource and run commands look for `project.yaml` in the current directory and
its parents. Run them inside the project, or create one with
`plural project init NAME`.

Hosted commands such as `push` also need the folder bound to a hosted project;
`plural project init NAME --push` creates or connects it. If a push says your scope
selects a different project, run `plural auth scope -p NAME` for the bound project,
or `plural auth scope .` for account scope.

## A push, pull, or hosted run is refused

A refused push uploads nothing, so it is safe to fix the cause and try again. The
error names the cause:

- **A version that is already pushed with different content** needs a new
  `version:` in the manifest.
- **A dependency that is not pushed yet, or changed locally**, needs
  `--with-deps` or its own push first.
- **A file that looks like a credential** must be removed or listed in the
  resource's `.pluralignore`, one exact path per line.
- **Content that is already pushed under another version** needs `version:` set
  back to that version.
- **A package over 100 MiB compressed** needs large files listed in `.pluralignore`.

`plural run ... --hosted` pushes any input the hosted project does not hold yet,
as the resource's next numbered revision. It stops, before uploading
anything, when someone else changed that resource in the hosted project since your
checkout synced it; pull their revision first. A pull refuses to overwrite local files that differ from the
revision; pass `--force` to replace them, keeping the old copy under
`.plural/backups/`. See [Push and pull resources](../guides/studio-sync.md).

## A YAML field is rejected

Manifests (the YAML file in each resource folder) reject unknown fields, and
validation names the field. Two common mix-ups:

- An Environment cannot list Tasks or Verifiers; a Task names its Environment and
  Verifiers instead.
- Eval or train mode belongs on a Python `Job`, not in a manifest.

See the [field catalog](../reference/fields.md) and
[YAML and serialization](../interfaces/yaml.md).

## Validation says a template is unfinished

`plural <kind> init` leaves `PLURAL-TODO` placeholders, including in each
Environment's and Benchmark's `README.md`. Validation, `push`, and `run` refuse a
resource until every placeholder is replaced. The error names the file and line.

## A file or resource cannot be found

Paths in a resource manifest, such as `instructions: instruction.md` in `task.yaml`,
resolve relative to that resource's folder.

Tasks, Verifiers, and Benchmarks refer to other resources by name, not by path, so
check that the named folder exists under the matching directory, for example
`environments/support-queue/`.

An absolute path on your laptop is not automatically available in a remote sandbox.

## A Verifier fails when the Task is built or when it scores

Constructing `Task(..., environment=..., verifiers=...)` fails unless the
Environment class lives in a `.py` file and each deterministic Verifier's
`check` is a function, or a `file.py:function` reference, that accepts an
`Episode`, such as `verify.py:verify` in the examples.

The function receives the final Observation, State, trajectory, artifacts, and
usage. If it returns anything other than a `VerifierOutput`, the Trial fails with no
score and a message that names the Verifier.

## The Verifier script or result is missing

Supply the implementation named by `check`. Imported modules and data are not
automatically available in the Verifier Runtime. The scorer must write its
declared result path as valid JSON and include evidence when required.

## The Runtime cannot enforce a policy

This means you asked for a safety control that the chosen Runtime (the place the
world runs) cannot provide.

Inspect `ProviderRegistry().doctors(include_unavailable=True)`. The `local`
provider cannot block networking or enforce resource limits. Docker does not
enforce a host `allowlist`. Daytona cannot build from a local Dockerfile. Use a
provider that supports the requirements; do not weaken policy silently.

If `plural run` says an Environment does not allow a Harness, the Environment's
`harness_policy` uses `mode: allowlist`. Add the Harness to `allowed_harnesses`
(`native` for Plural's built-in loop), or run with an allowed one; see
[Harness and Environment policy](../concepts/harness-policy.md).

## The model cannot sign in or connect

The most common cause is a missing Plural API key.

Every model call goes through the Plural gateway, so a run that calls a live model
needs a Plural API key: one stored with `plural auth login --api-key-stdin`, or an
exported `PLURAL_API_KEY`. A browser login alone is enough for hosted commands but is
not accepted for model calls, so a run can fail with "no Plural API key is available"
right after a successful browser login. You can create a key in the web app under
Keys.

- In Python, pass `Job(..., client=Client())` or `api_key=`.
- An Agent whose Harness never calls a model can set `auth_mode: none` and needs no
  key.
- Check the selected model ID and endpoint: a direct provider may accept a different
  ID from a multi-provider gateway.
- If a model you expect is missing from `plural models list`, your organization's
  model policy may not permit it; the service enforces the same policy when a run
  starts.

`PLURAL_GATEWAY_URL` selects the gateway; `plural run` sets it from your profile. A
provider key or `OPENAI_BASE_URL` in the environment is not used for Agent or
Verifier model calls. Model connectivity is separate from the hosted project API
endpoint. A local run does not block network requests.

## The Agent stops at its turn limit

The built-in `native` loop stops when the Agent reaches its turn limit. Hitting the
limit usually means the Agent got stuck, not that it needed more turns.

Read the trajectory (the step-by-step record of the attempt). The model may be
repeating an invalid action or failing to produce a final response. Fix action
feedback and Task stopping instructions before raising the budget. The support
tutorial requires inspection, categorization, response drafting, and resolution.

## The run finished but the score is zero

That can be a legitimate evaluation outcome. Inspect the final state and Verifier
feedback. A correctly executed Agent can still choose the wrong category. Keep
zero-scoring completed Trials in your comparison.

## A review is still pending

Use `plural review list` for local Trials or `plural review list --hosted` for
hosted assignments. Submit all required criteria in their declared ranges. A
pending human score withholds the final score; it is not a runtime timeout.

## Train mode reports unsupported TITO

TITO is exact token capture: the tokens sent to and received from the model, which
train mode needs. The selected Harness cannot supply it.

Use eval mode for ordinary transcripts, or implement token capture in a Harness that
sets `supports_tito = True` and returns `TITORecord` values; see
[Training and RL](../running/training.md). Do not declare `supports_tito`
without the implementation.

## A Harness digest no longer matches

A digest is a fingerprint of the Harness files. A mismatch means the files changed
after the Agent that uses it was validated or pushed, or a different copy of the
files was used.

Validate the Harness again and push it with the Agent. Keep
generated files out of the source tree. Do not bypass integrity checks to make a
stale comparison run.

## Local results do not appear in Plural Intel

A local Job and a hosted Job are separate, and a local run is not uploaded on its
own. A trace ID alone does not upload the trace or artifacts.

- To run on your machine and record the Job in the hosted project as it runs, use
  `plural run ... --track`.
- To record a Job that already finished locally, use `plural job push`. The
  revisions it ran must already be hosted.
- To run in Plural Intel instead, use `plural run ... --hosted`.

See [Push and pull resources](../guides/studio-sync.md).

## A rerun gives different answers

There is no deterministic replay. Reading a stored trajectory is different from
rerunning a model or external service. Revisions identify the experiment; they cannot
guarantee identical model outputs or remote state. See
[Trials and trajectories](../running/trials.md).
