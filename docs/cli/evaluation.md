---
route: /docs/cli/evaluation
title: CLI guide
order: 120
description: Create a project, validate and push its resources, run Tasks and Benchmarks, and inspect, rerun, and review the resulting Jobs.
audience: all
nav: true
nav_group: Interfaces
---
# CLI guide

The CLI works on a project directory: a `project.yaml` file with one directory per
resource beside it, such as `environments/wordle/` or `tasks/crane/`. Commands
name resources by their directory name, and most resource commands default to the
resource directory you are in. Commands that print data, such as `validate`,
`show`, `list`, and `run`, accept `--json` for machine-readable output.

Projects written for Plural 0.14 or earlier use a different layout; see
[Migrate to 0.15](../migration/projects.md).

## Create a project

```bash
plural project init support-eval
cd support-eval
plural env init support-queue
plural verifier init correct-category
plural task init ticket-1 -e support-queue -v correct-category
plural benchmark init support-triage
plural benchmark add ticket-1 -b support-triage
plural agent init careful -m openai/gpt-5.6-luna
```

`plural project init` works offline. Each resource `init` command writes a
template with places marked `PLURAL-TODO` for you to fill in; a new Environment
and Verifier need real behavior before a run means anything. The
[support queue tutorial](../tutorials/support-queue.md) provides both. Without
`-m`, `agent init` leaves the model for you to choose from `plural models list`.
A new Environment uses the `docker` runtime, so Docker must be running when you
run it; the `local` runtime avoids Docker but is a trusted subprocess on your
machine, not a sandbox.

`validate` checks a resource and everything it depends on without uploading
anything, and reports every `PLURAL-TODO` that is still unfinished. `show` prints
the local copy of a resource, or the hosted one when there is no local copy. A
local copy that is not valid yet is reported as an error instead:

```bash
plural benchmark validate support-triage
plural task show ticket-1
plural project show support-eval
```

## Run

A run selects exactly one source, a Task (`-t`) or a Benchmark (`-b`), and
exactly one way to act: a catalog model (`-m`) or a saved Agent (`-a`).

```bash
plural run -t ticket-1 -m openai/gpt-5.6-luna
plural run -b support-triage -a careful
plural run -b support-triage -m openai/gpt-5.6-luna -h codex
```

`-m` without `-h` uses `native`, Plural's built-in tool loop. `-h` names a
Harness in `harnesses/` or a built-in one such as `codex` or `claude-code`. Add
`--dry-run` to validate the inputs and print the plan, including the version
and content hash of every input, without running anything. `--attempts N` plans
N independent Trials per Task, and `--concurrency N` runs up to N Trials at once.
Both default to 1.

Every run is a new Job. A local run executes on this machine and records the Job
under `.plural/jobs/<job-id>/` in the project. A run that calls a live model
needs an API key: `plural auth login --api-key-stdin`, `PLURAL_API_KEY`, or your
own `OPENAI_API_KEY` for `openai/` models. A browser login is enough for hosted
commands, but the model gateway does not accept it. `--dry-run` needs none, and
neither does an Agent with `auth_mode: none`.

## Jobs, Trials, and reviews

```bash
plural job list
plural job show JOB_ID
plural job rerun JOB_ID
plural trial show TRIAL_ID
plural trial rerun TRIAL_ID
plural review list
plural review submit TRIAL_ID --verifier policy-review --score 2 \
  --feedback "Meets policy."
```

`job list` shows local and hosted Jobs, labeled by where they ran. `job show` and
`trial show` look for a local record first and then ask the hosted project.
`job rerun` runs a Job again with the exact pinned inputs it used and creates a
new Job linked to the original. `trial rerun` runs one Trial again as a new
one-Trial Job. `review list` shows Trials waiting for a HumanVerifier score, and
`review submit` records one; add `--hosted` to either for hosted review
assignments. Submissions are append-only. See [Jobs](../running/jobs.md) and
[Reviews](../running/reviews.md).

## Models

```bash
plural models list
plural models list --provider openai
```

Signed in, `plural models list` shows only the models your organization permits.
Organization admins can restrict models, and the hosted service enforces that
restriction on runs and gateway calls as well as on this list. Signed out, it
shows the bundled catalog without any organization policy.

## Hosted projects

Local runs need no hosted project. To share resources with your team or run on
hosted infrastructure, sign in and push:

```bash
plural auth login
plural project init support-eval --push
plural benchmark push support-triage --with-deps
plural agent push careful
plural run -b support-triage -a careful --hosted --follow
```

`plural project init --push` creates the hosted project. If that name already
exists, pass `--connect` to bind to it or `--name` to create a different one.
`plural project push` then uploads every local resource. The hosted project is
private. The command records the binding in `.plural/project.json` and selects
the project as your scope. A push creates an immutable, private revision that is
usable in that project immediately; pushing never makes anything public, and
sharing is a separate action in the Plural web app. A push validates first,
uploads nothing unless the whole push can succeed, and refuses files that look
like credentials, such as `.env` or private keys. `--hosted` requires every
input of the run to be pushed already with identical content, and `--follow`
streams hosted progress until the Job finishes. See
[Push and pull resources](../guides/studio-sync.md).

`plural auth status` shows which credential is in use, a browser login or an API
key, and the current scope. `plural auth scope` shows or changes where hosted
commands go:

```bash
plural auth scope
plural auth scope -p support-eval
plural auth scope .
plural auth scope --org acme
```

`-p` selects an existing hosted project, `.` or `--account` selects account
scope, and `--org` switches between organization accounts (`personal` selects
your own). A new scope is checked with the service before it is saved; if the
check fails, the previous scope stays in place. Scope selects a destination and
never changes what your credential may do. An API key limited to one project
can only reach that project. Credentials are stored in your OS keyring or a
private file in your user config directory, never in the project.

## Command reference

<!-- generated-cli-reference -->
This section is generated from the Typer application. Run `uv run python scripts/generate_cli_reference.py` after changing the CLI.

### `plural`

```text

 Usage: plural [OPTIONS] COMMAND [ARGS]...

 Build, push, and run Plural projects.

 Start with `plural project init <name>`, add resources with `plural
 <env|task|verifier|harness|agent|benchmark> init <name>`, and run them with `plural run --task
 <name> --model <model>`.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.                          │
│ --show-completion             Show completion for the current shell, to copy it or customize the │
│                               installation.                                                      │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ run        Run one Task or Benchmark with a model or a saved Agent. Every run is a new Job.      │
│ auth       Sign in, sign out, and choose the hosted account or project commands use.             │
│ project    Create, register, and inspect projects.                                               │
│ env        Create, validate, push, pull, and inspect Environments.                               │
│ verifier   Create, validate, push, pull, and inspect Verifiers.                                  │
│ harness    Create, validate, push, pull, and inspect Harnesses.                                  │
│ task       Create, validate, push, pull, and inspect Tasks.                                      │
│ agent      Create, validate, push, pull, and inspect Agents.                                     │
│ benchmark  Create, validate, push, pull, and inspect Benchmarks.                                 │
│ job        List, inspect, and rerun Jobs.                                                        │
│ trial      Inspect and rerun Trials.                                                             │
│ review     List and submit human reviews.                                                        │
│ models     List the models you may run.                                                          │
│ session    Export and redeploy portable agent sessions.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent`

```text

 Usage: plural agent [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Agents.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a saved Agent: a model, instructions, and an optional Harness.                  │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
│ serve     Reserved: serve an Agent as an endpoint (not available yet).                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent init`

```text

 Usage: plural agent init [OPTIONS] {name}

 Create a saved Agent: a model, instructions, and an optional Harness.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Agent name. [required]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --model    -m      <str>  Catalog model id.                                                      │
│ --harness          <str>  Harness name.                                                          │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent list`

```text

 Usage: plural agent list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent pull`

```text

 Usage: plural agent pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version          <str>  Version to restore.                                                    │
│ --with-deps               Also restore the exact dependency revisions it pins.                   │
│ --force                   Replace local files that differ. The old copy is kept under            │
│                           .plural/backups.                                                       │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent push`

```text

 Usage: plural agent push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 Pushing unchanged content reuses the existing revision. Without
 --with-deps, every dependency must already be pushed with identical
 content. Nothing is uploaded unless the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent serve`

```text

 Usage: plural agent serve [OPTIONS] [name]

 Reserved: serve an Agent as an endpoint (not available yet).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Agent to serve.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent show`

```text

 Usage: plural agent show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent validate`

```text

 Usage: plural agent validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth`

```text

 Usage: plural auth [OPTIONS] COMMAND [ARGS]...

 Sign in, sign out, and choose the hosted account or project commands use.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ login   Sign in with your browser (or store an API key).                                         │
│ logout  Revoke and remove the stored credential for this profile.                                │
│ status  Check the credential with the service and show the current scope.                        │
│ scope   Show or change where hosted commands go by default.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth login`

```text

 Usage: plural auth login [OPTIONS]

 Sign in with your browser (or store an API key).

 A browser login acts as you: it reaches every account and project your
 roles allow. Credentials are stored in your OS keyring or a private file
 in your user config directory, never in a project.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --no-browser                   Print the URL only.                                               │
│ --api-key-stdin                Store an API key read from standard input instead.                │
│ --from-env                     Store PLURAL_API_KEY from the environment. The value is not       │
│                                printed.                                                          │
│ --env-file             <path>  Read PLURAL_API_KEY from this file. Other variables in the file   │
│                                are ignored.                                                      │
│ --api-url              <str>   Hosted service URL.                                               │
│ --help                         Show this message and exit.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth logout`

```text

 Usage: plural auth logout [OPTIONS]

 Revoke and remove the stored credential for this profile.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth scope`

```text

 Usage: plural auth scope [OPTIONS] [.]

 Show or change where hosted commands go by default.

 Scope selects a destination; it never changes what your credential may
 do. The new scope is checked with the service before it is saved, and a
 failed check leaves the previous scope in place.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   [.]      <str>  `.` selects account scope. Omit to show the current scope.                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --account                 Select account scope.                                                  │
│ --project  -p      <str>  Select an existing hosted project by name.                             │
│ --org              <str>  Switch to an organization account (slug or id), or `personal`.         │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth status`

```text

 Usage: plural auth status [OPTIONS]

 Check the credential with the service and show the current scope.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark`

```text

 Usage: plural benchmark [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Benchmarks.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a new Benchmark from the standard template.                                     │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
│ add       Add a Task to a Benchmark (a local edit until you push).                               │
│ remove    Remove a Task from a Benchmark (a local edit until you push).                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark add`

```text

 Usage: plural benchmark add [OPTIONS] {task}

 Add a Task to a Benchmark (a local edit until you push).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <str>  Task to add. [required]                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --benchmark  -b      <str>  Benchmark to edit. Defaults to the one you are in.                   │
│ --push                      Push the Benchmark afterwards.                                       │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark init`

```text

 Usage: plural benchmark init [OPTIONS] {name}

 Create a new Benchmark from the standard template.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Benchmark name. [required]                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark list`

```text

 Usage: plural benchmark list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark pull`

```text

 Usage: plural benchmark pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version          <str>  Version to restore.                                                    │
│ --with-deps               Also restore the exact dependency revisions it pins.                   │
│ --force                   Replace local files that differ. The old copy is kept under            │
│                           .plural/backups.                                                       │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark push`

```text

 Usage: plural benchmark push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 Pushing unchanged content reuses the existing revision. Without
 --with-deps, every dependency must already be pushed with identical
 content. Nothing is uploaded unless the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark remove`

```text

 Usage: plural benchmark remove [OPTIONS] {task}

 Remove a Task from a Benchmark (a local edit until you push).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    task      <str>  Task to remove. [required]                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --benchmark  -b      <str>  Benchmark to edit. Defaults to the one you are in.                   │
│ --push                      Push the Benchmark afterwards.                                       │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark show`

```text

 Usage: plural benchmark show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark validate`

```text

 Usage: plural benchmark validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env`

```text

 Usage: plural env [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Environments.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a new Environment from the standard template.                                   │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env init`

```text

 Usage: plural env init [OPTIONS] {name}

 Create a new Environment from the standard template.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Environment name. [required]                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env list`

```text

 Usage: plural env list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env pull`

```text

 Usage: plural env pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version          <str>  Version to restore.                                                    │
│ --with-deps               Also restore the exact dependency revisions it pins.                   │
│ --force                   Replace local files that differ. The old copy is kept under            │
│                           .plural/backups.                                                       │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env push`

```text

 Usage: plural env push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 Pushing unchanged content reuses the existing revision. Without
 --with-deps, every dependency must already be pushed with identical
 content. Nothing is uploaded unless the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env show`

```text

 Usage: plural env show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env validate`

```text

 Usage: plural env validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness`

```text

 Usage: plural harness [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Harnesses.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a new Harness from the standard template.                                       │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness init`

```text

 Usage: plural harness init [OPTIONS] {name}

 Create a new Harness from the standard template.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Harness name. [required]                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness list`

```text

 Usage: plural harness list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness pull`

```text

 Usage: plural harness pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version          <str>  Version to restore.                                                    │
│ --with-deps               Also restore the exact dependency revisions it pins.                   │
│ --force                   Replace local files that differ. The old copy is kept under            │
│                           .plural/backups.                                                       │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness push`

```text

 Usage: plural harness push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 Pushing unchanged content reuses the existing revision. Without
 --with-deps, every dependency must already be pushed with identical
 content. Nothing is uploaded unless the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness show`

```text

 Usage: plural harness show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness validate`

```text

 Usage: plural harness validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job`

```text

 Usage: plural job [OPTIONS] COMMAND [ARGS]...

 List, inspect, and rerun Jobs.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list   List Jobs, newest first, labeled local or hosted.                                         │
│ show   Show a Job and its Trials (local first, then hosted).                                     │
│ rerun  Run a Job again with the exact inputs it used. Creates a new, linked Job.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job list`

```text

 Usage: plural job list [OPTIONS]

 List Jobs, newest first, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only local Jobs.                                                               │
│ --hosted          Only hosted Jobs.                                                              │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job rerun`

```text

 Usage: plural job rerun [OPTIONS] {job_id}

 Run a Job again with the exact inputs it used. Creates a new, linked Job.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job to run again with its original pinned inputs. [required]             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job show`

```text

 Usage: plural job show [OPTIONS] {job_id}

 Show a Job and its Trials (local first, then hosted).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job id. [required]                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --follow          Stream progress until it finishes.                                             │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural models`

```text

 Usage: plural models [OPTIONS] COMMAND [ARGS]...

 List the models you may run.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list  List models your account may use.                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural models list`

```text

 Usage: plural models list [OPTIONS]

 List models your account may use.

 Signed in, the hosted service returns only the models your organization
 permits, and enforces that list when a run starts. Signed out, the bundled
 catalog is shown without any organization policy.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --provider        <str>  Only this provider.                                                     │
│ --json                   Print machine-readable JSON.                                            │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural project`

```text

 Usage: plural project [OPTIONS] COMMAND [ARGS]...

 Create, register, and inspect projects.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init  Create a project in ./<name>, or register the project you are in.                          │
│ show  Show a project, local copy first, then hosted.                                             │
│ push  Push every local resource to the bound hosted project.                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural project init`

```text

 Usage: plural project init [OPTIONS] {name}

 Create a project in ./<name>, or register the project you are in.

 Without --push this works offline. With --push, an existing local project
 is registered as it is; no local file is overwritten. A hosted project
 that already has this name is left alone unless --connect is set.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Project name: lowercase letters, digits, and hyphens. [required]           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --push                  Create a hosted project with this name and select it as your scope.      │
│ --connect               Bind to the hosted project that already has this name. Requires --push.  │
│ --name           <str>  Hosted project name, when it should differ from the local project.       │
│                         Requires --push.                                                         │
│ --help                  Show this message and exit.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural project push`

```text

 Usage: plural project push [OPTIONS]

 Push every local resource to the bound hosted project.

 New revisions are added dependencies first. Existing revisions are never
 overwritten or deleted. A resource whose files changed but whose version
 did not is refused until you bump the version or pass --bump.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --yes      -y             Push without asking.                                                   │
│ --bump                    Give each changed resource the next patch version.                     │
│ --force                   Add revisions even if the hosted copy changed since this checkout last │
│                           synced.                                                                │
│ --connect                 Bind to the hosted project that already has this name.                 │
│ --name             <str>  Hosted project name, when this checkout is not bound yet.              │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural project show`

```text

 Usage: plural project show [OPTIONS] {name}

 Show a project, local copy first, then hosted.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Project name. [required]                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only look at local files.                                                      │
│ --hosted          Only look at the hosted project.                                               │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural review`

```text

 Usage: plural review [OPTIONS] COMMAND [ARGS]...

 List and submit human reviews.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list    List Trials waiting for a human score.                                                   │
│ submit  Record a human score. Submissions are append-only.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural review list`

```text

 Usage: plural review list [OPTIONS]

 List Trials waiting for a human score.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosted          Hosted review assignments.                                                     │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural review submit`

```text

 Usage: plural review submit [OPTIONS] {target}

 Record a human score. Submissions are append-only.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    target      <str>  Trial id, or a review assignment id with --hosted. [required]            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --score           <str>  `criterion=value`, or a bare value for a one-criterion rubric.       │
│                             [required]                                                           │
│    --verifier        <str>  Human Verifier (local).                                              │
│    --feedback        <str>  Notes for the record.                                                │
│    --hosted                 Submit a hosted assignment.                                          │
│    --help                   Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural run`

```text

 Usage: plural run [OPTIONS]

 Run one Task or Benchmark with a model or a saved Agent. Every run is a new Job.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --task         -t      <str>               Task to run.                                          │
│ --benchmark    -b      <str>               Benchmark to run.                                     │
│ --model        -m      <str>               Catalog model id.                                     │
│ --harness      -h      <str>               Harness for --model. Default: native (Plural's        │
│                                            built-in tool loop).                                  │
│ --agent        -a      <str>               Saved Agent to run.                                   │
│ --hosted                                   Run on hosted infrastructure using pushed revisions.  │
│ --attempts             <int range> [x>=1]  Advanced: Trials per Task (default 1).                │
│ --concurrency          <int range> [x>=1]  Advanced: Trials to run at once. [default: 1]         │
│ --dry-run                                  Advanced: validate and show the plan without running. │
│ --follow                                   With --hosted, stream progress.                       │
│ --json                                     Print machine-readable JSON.                          │
│ --help                                     Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural session`

```text

 Usage: plural session [OPTIONS] COMMAND [ARGS]...

 Export and redeploy portable agent sessions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ export  Export a session bundle from a hosted trial or local files.                              │
│ import  Redeploy a bundle as a separate instance directory.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural session export`

```text

 Usage: plural session export [OPTIONS]

 Export a session bundle from a hosted trial or local files.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --trial              <str>   Hosted trial id.                                                    │
│ --agent              <path>  Agent YAML or JSON file.                                            │
│ --environment        <path>  Environment YAML or JSON file.                                      │
│ --state              <path>  State JSON file.                                                    │
│ --data               <str>   Data reference to record.                                           │
│ --data-dir           <path>  Directory bundled into data/.                                       │
│ --name               <str>   Snapshot name.                                                      │
│ --out                <path>  Bundle directory. [default: sessions]                               │
│ --help                       Show this message and exit.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural session import`

```text

 Usage: plural session import [OPTIONS] {bundle}

 Redeploy a bundle as a separate instance directory.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    bundle      <path>  Session bundle directory. [required]                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --dest        <path>  Parent directory for the new instance.                                     │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task`

```text

 Usage: plural task [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Tasks.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a Task with instructions, one Environment, and its Verifiers.                   │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task init`

```text

 Usage: plural task init [OPTIONS] {name}

 Create a Task with instructions, one Environment, and its Verifiers.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Task name. [required]                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --environment  -e      <str>  Environment the Task runs in.                                      │
│ --verifier     -v      <str>  Verifier that scores it. Repeat for more.                          │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task list`

```text

 Usage: plural task list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task pull`

```text

 Usage: plural task pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version          <str>  Version to restore.                                                    │
│ --with-deps               Also restore the exact dependency revisions it pins.                   │
│ --force                   Replace local files that differ. The old copy is kept under            │
│                           .plural/backups.                                                       │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task push`

```text

 Usage: plural task push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 Pushing unchanged content reuses the existing revision. Without
 --with-deps, every dependency must already be pushed with identical
 content. Nothing is uploaded unless the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task show`

```text

 Usage: plural task show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task validate`

```text

 Usage: plural task validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural trial`

```text

 Usage: plural trial [OPTIONS] COMMAND [ARGS]...

 Inspect and rerun Trials.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ show     Show a Trial's result, Verifier evidence, and artifacts (local first, then hosted).     │
│ rerun    Run one Trial again with its pinned inputs, as a new one-Trial Job.                     │
│ rescore  Reserved: score a finished Trial again (not available yet).                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural trial rerun`

```text

 Usage: plural trial rerun [OPTIONS] {trial_id}

 Run one Trial again with its pinned inputs, as a new one-Trial Job.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    trial_id      <str>  Trial to run again. [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural trial rescore`

```text

 Usage: plural trial rescore [OPTIONS] {trial_id}

 Reserved: score a finished Trial again (not available yet).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    trial_id      <str>  Trial id. [required]                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural trial show`

```text

 Usage: plural trial show [OPTIONS] {trial_id}

 Show a Trial's result, Verifier evidence, and artifacts (local first, then hosted).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    trial_id      <str>  Trial id. [required]                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --follow          Stream progress until it finishes.                                             │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier`

```text

 Usage: plural verifier [OPTIONS] COMMAND [ARGS]...

 Create, validate, push, pull, and inspect Verifiers.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a new Verifier from the standard template.                                      │
│ validate  Check a resource and everything it depends on, without uploading.                      │
│ push      Validate and push an immutable, private revision to the bound project.                 │
│ pull      Restore a hosted revision's editable files into this project.                          │
│ show      Show a resource: the local copy if there is one, otherwise the hosted one.             │
│ list      List resources of this kind, labeled local or hosted.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier init`

```text

 Usage: plural verifier init [OPTIONS] {name}

 Create a new Verifier from the standard template.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Verifier name. [required]                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier list`

```text

 Usage: plural verifier list [OPTIONS]

 List resources of this kind, labeled local or hosted.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only list local resources.                                                     │
│ --hosted          Only list hosted resources.                                                    │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier pull`

```text

 Usage: plural verifier pull [OPTIONS] [name]

 Restore a hosted revision's editable files into this project.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --version          <str>  Version to restore.                                                    │
│ --with-deps               Also restore the exact dependency revisions it pins.                   │
│ --force                   Replace local files that differ. The old copy is kept under            │
│                           .plural/backups.                                                       │
│ --json                    Print machine-readable JSON.                                           │
│ --help                    Show this message and exit.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier push`

```text

 Usage: plural verifier push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 Pushing unchanged content reuses the existing revision. Without
 --with-deps, every dependency must already be pushed with identical
 content. Nothing is uploaded unless the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier show`

```text

 Usage: plural verifier show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --local           Only read local files.                                                         │
│ --hosted          Only read the hosted project.                                                  │
│ --json            Print machine-readable JSON.                                                   │
│ --help            Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier validate`

```text

 Usage: plural verifier validate [OPTIONS] [name]

 Check a resource and everything it depends on, without uploading.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```
<!-- /generated-cli-reference -->
