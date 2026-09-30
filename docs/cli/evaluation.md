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

The `plural` command-line tool (CLI) runs Plural from your terminal. With it you set
up a project, check your work, run models against your Tasks, and read back the
scores. This page is for anyone comfortable typing commands; it starts with the few
you need and ends with a complete reference for power users.

## What the CLI is

Everything you build in Plural lives in a **project**. On your computer, that is a
folder with a `project.yaml` file and one subfolder per resource, such as
`environments/wordle/` or `tasks/crane/`. The CLI reads and writes that folder.

Commands name a resource by its folder name. Most resource commands also work with no
name at all, and then act on the resource folder you are in. If words like Task,
Agent, or Benchmark are new, read [Core concepts](../getting-started/concepts.md)
first.

## The commands most people need

Most days you only need these:

```bash
plural project init support-eval
plural task validate ticket-1
plural run -t ticket-1 -m openai/gpt-5.6-luna
plural job list
plural job show JOB_ID
```

In order: create a project, check a Task is ready, run it with one model, list your
runs, and open one to see its scores. Every run is recorded as a **Job**, and each
attempt inside it is a **Trial**. A live run needs a Plural API key; see
[Run](#run).

Commands that print data, such as `validate`, `show`, `list`, and `run`, accept
`--json` for machine-readable output.

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

This builds the support queue example: a world (the Environment), a grader (the
Verifier), one ticket to work (the Task), an exam that holds it (the Benchmark), and a
contestant (the Agent).

`plural project init` works offline. Each resource `init` command writes a template
with places marked `PLURAL-TODO` for you to fill in. A new Environment and Verifier
need real behavior before a run means anything; the
[support queue tutorial](../tutorials/support-queue.md) provides both. Without `-m`,
`agent init` leaves the model for you to choose from `plural models list`.

> **Good to know:** A new Environment uses the `docker` runtime, so Docker must be
> running when you run it. The `local` runtime avoids Docker, but it is a trusted
> subprocess on your machine, not a sandbox.

To check your work, use `validate` and `show`. `validate` checks a resource and
everything it depends on without uploading anything, and reports every `PLURAL-TODO`
that is still unfinished. `show` prints the local copy of a resource, or the hosted
one when there is no local copy. A local copy that is not valid yet is reported as an
error instead:

```bash
plural benchmark validate support-triage
plural task show ticket-1
plural project show support-eval
```

## Run

`plural run` answers two questions: *what* to run and *who* runs it. Pick exactly
one of each:

- **What:** one Task (`-t`) or a whole Benchmark (`-b`).
- **Who:** a catalog model (`-m`) or a saved Agent (`-a`).

```bash
plural run -t ticket-1 -m openai/gpt-5.6-luna
plural run -b support-triage -a careful
plural run -b support-triage -m openai/gpt-5.6-luna -h codex
```

Every run is a new Job. A local run executes on this machine and records the Job
under `.plural/jobs/<job-id>/` in the project.

A run that calls a live model sends every call through the Plural gateway, so it
needs a Plural API key: `plural auth login --api-key-stdin` or `PLURAL_API_KEY`. A
browser login is enough for hosted commands, but the model gateway does not accept
it. `--dry-run` needs no key, and neither does an Agent with `auth_mode: none`.

### Run options

These options change what a run does. Most people only reach for `--dry-run` and
`--attempts`.

- **`-h HARNESS`** picks the Harness, the loop that decides what the model does next.
  `-m` without `-h` uses `native`, Plural's built-in tool loop. `-h` names a Harness
  in `harnesses/` or a built-in one such as `codex` or `claude-code`.
- **`--dry-run`** validates the inputs and prints the plan, including the version and
  content hash of every input, without running anything.
- **`--attempts N`** plans N independent Trials per Task. It defaults to 1.
- **`--concurrency N`** (or `-n N`) runs up to N Trials at once. It defaults to
  `auto`, which sizes it from this machine, the Runtime, and where the model runs;
  see [Attempts and concurrency](../guides/jobs.md#attempts-and-concurrency).
- **`--plural-version`** selects the Plural installed in Docker and remote sandboxes:
  a version, or `latest`. By default it is this CLI's own code; see
  [Plural inside Docker and remote sandboxes](../guides/jobs.md#plural-inside-docker-and-remote-sandboxes).
- **`--hosted`**, **`--follow`**, and **`--track`** decide where the run happens and
  where it is recorded; see [Hosted projects](#hosted-projects).

Add `@` and a revision to a Task, Benchmark, or Agent to run that exact pushed
revision, such as `plural run -b support-triage@1.0.0 -a careful` or
`plural run -b support-triage@3 -a careful`, even after your files have moved on.
After `@`, give a revision number, a release version, or a content hash. The revision
is restored under `.plural/versions` without touching your files; see
[Calling a revision by name](../project/updating.md#calling-a-revision-by-name).

## Jobs, Trials, and reviews

After a run, these commands let you look back at what happened, run it again, or add
a human's score.

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

- `job list` shows local and hosted Jobs, newest first, labeled by where they ran.
- `job show` and `trial show` look for a local record first and then ask the hosted
  project. `trial show` includes the Verifier's evidence and the Trial's artifacts.
  Add `--follow` to either to stream progress until it finishes.
- `job rerun` runs a Job again with the exact pinned inputs it used and creates a new
  Job linked to the original. `trial rerun` runs one Trial again as a new one-Trial
  Job. Add `--track` to either to record a local rerun in the hosted project as it
  runs.
- `review list` shows Trials waiting for a HumanVerifier score, and `review submit`
  records one. Use one `--score criterion=value` per rubric criterion, or a bare value
  for a one-criterion rubric. Add `--hosted` to either for hosted review assignments.
  Submissions are append-only.

See [Jobs](../running/jobs.md) and [Reviews](../running/reviews.md).

## Models

To see which models you can run, list them:

```bash
plural models list
plural models list --provider openai
plural models list --all
```

Outside an organization, and when you are signed out, it shows the whole catalog.
`--provider` narrows the list to one provider.

Signed in to an organization, `plural models list` shows the models your organization
offers: its own endpoints and private models, and any an admin has explicitly
allowed. `--all` shows the whole catalog and marks models your organization does not
permit, which the hosted service refuses on runs and gateway calls. The same list,
with prices, is in the model Catalog in the web app.

## Hosted projects

Local runs need no hosted project. A hosted project is a private copy of your project
on Plural, which lets your team share resources and lets Plural's infrastructure run
Jobs for you. To use one, sign in and push:

```bash
plural auth login
plural project init support-eval --push
plural benchmark push support-triage --with-deps
plural agent push careful
plural run -b support-triage -a careful --hosted --follow
```

> **Good to know:** Pushing never makes anything public. The hosted project is
> private, and sharing is a separate action in the Plural web app.

`plural project init --push` creates the hosted project. If that name already exists,
pass `--connect` to bind to it or `--name` to create a different one. The command
records the binding in `.plural/project.json` and selects the project as your scope.
`plural project push` then uploads every local resource.

A push creates an immutable, private revision that is usable in that project
immediately. A push validates first, uploads nothing unless the whole push can
succeed, and refuses files that look like credentials, such as `.env` or private
keys. Changed content becomes the resource's next numbered revision, and
`plural <kind> release NAME VERSION` names one with a version people can cite. See
[Push and pull resources](../guides/studio-sync.md).

`--hosted` runs the Job on hosted infrastructure, and `--follow` streams hosted
progress until the Job finishes. Before submitting, `--hosted` pushes any input of
the run that the hosted project does not hold yet, as a new numbered revision of any
input whose files changed, and an input someone else changed in the hosted project since you last synced
stops the push before anything is uploaded.

A run on this machine can be recorded in the hosted project too, without hosted
infrastructure running it:

```bash
plural run -b support-triage -a careful --track
plural job push JOB_ID
```

`--track` records the Job while it runs, and pushes missing inputs first the same way
`--hosted` does. `job push` records a local Job that already finished; it pins the
revisions that Job ran, so push those first. Both produce the same hosted Job, so
pushing a tracked Job again uploads only what the hosted Job does not hold yet. The
Environment's Runtime still decides where Trials execute, so a tracked run against a
Daytona Environment runs remotely. See
[Jobs](../running/jobs.md#local-tracked-and-hosted).

### Sign-in and scope

There are two ways to sign in. A browser login acts as you, and is enough for hosted
commands. An API key is what model calls need:

```bash
plural auth login
plural auth login --api-key-stdin
plural auth login --from-env
plural auth status
```

`--api-key-stdin` reads the key from standard input, `--from-env` stores
`PLURAL_API_KEY` from your environment without printing it, and `--env-file PATH`
reads `PLURAL_API_KEY` from a file. `plural auth logout` revokes and removes the
stored credential. `plural auth status` shows which credential is in use, a browser
login or an API key, and the current scope.

`plural auth scope` shows or changes where hosted commands go:

```bash
plural auth scope
plural auth scope -p support-eval
plural auth scope .
plural auth scope --org acme
```

`-p` selects an existing hosted project, `.` or `--account` selects account scope, and
`--org` switches between organization accounts (`personal` selects your own). A new
scope is checked with the service before it is saved; if the check fails, the
previous scope stays in place.

Scope selects a destination and never changes what your credential may do. An API key
limited to one project can only reach that project. Credentials are stored in your OS
keyring or a private file in your user config directory, never in the project.

## Portable sessions

`plural session export` bundles an Agent's session, from a hosted Trial
(`--trial TRIAL_ID`) or from local files (`--agent`, `--environment`, `--state`), into a
directory you can move elsewhere. `plural session import BUNDLE` redeploys that bundle
as a separate instance directory. The reference below lists every option.

## Command reference

The rest of this page is for power users and scripts: the full help text of every
command and option, exactly as the CLI prints it. Two commands are listed but
reserved for later, and print that they are not available yet: `plural agent serve`
and `plural trial rescore`.

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
│ release   Label the revision matching your files with a release version, pushing it first.       │
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

 Name a retained revision as name@REVISION or with --revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --revision   -r      <str>  Revision to restore: a number, version, or hash.                     │
│ --with-deps                 Also replace dependencies you already have with the exact revisions  │
│                             it pins. Missing dependencies are always restored.                   │
│ --force                     Replace local files that differ. The old copy is kept under          │
│                             .plural/backups.                                                     │
│ --json                      Print machine-readable JSON.                                         │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent push`

```text

 Usage: plural agent push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --force              Add a revision even though the hosted resource moved since you last synced. │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent release`

```text

 Usage: plural agent release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource name. Defaults to the resource directory you are in.           │
│                          [required]                                                              │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
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
 name@REVISION shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
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
│ release   Label the revision matching your files with a release version, pushing it first.       │
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

 Name a retained revision as name@REVISION or with --revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --revision   -r      <str>  Revision to restore: a number, version, or hash.                     │
│ --with-deps                 Also replace dependencies you already have with the exact revisions  │
│                             it pins. Missing dependencies are always restored.                   │
│ --force                     Replace local files that differ. The old copy is kept under          │
│                             .plural/backups.                                                     │
│ --json                      Print machine-readable JSON.                                         │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark push`

```text

 Usage: plural benchmark push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --force              Add a revision even though the hosted resource moved since you last synced. │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark release`

```text

 Usage: plural benchmark release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource name. Defaults to the resource directory you are in.           │
│                          [required]                                                              │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
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
 name@REVISION shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
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
│ release   Label the revision matching your files with a release version, pushing it first.       │
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

 Name a retained revision as name@REVISION or with --revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --revision   -r      <str>  Revision to restore: a number, version, or hash.                     │
│ --with-deps                 Also replace dependencies you already have with the exact revisions  │
│                             it pins. Missing dependencies are always restored.                   │
│ --force                     Replace local files that differ. The old copy is kept under          │
│                             .plural/backups.                                                     │
│ --json                      Print machine-readable JSON.                                         │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env push`

```text

 Usage: plural env push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --force              Add a revision even though the hosted resource moved since you last synced. │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env release`

```text

 Usage: plural env release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource name. Defaults to the resource directory you are in.           │
│                          [required]                                                              │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural env show`

```text

 Usage: plural env show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.
 name@REVISION shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
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
│ release   Label the revision matching your files with a release version, pushing it first.       │
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

 Name a retained revision as name@REVISION or with --revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --revision   -r      <str>  Revision to restore: a number, version, or hash.                     │
│ --with-deps                 Also replace dependencies you already have with the exact revisions  │
│                             it pins. Missing dependencies are always restored.                   │
│ --force                     Replace local files that differ. The old copy is kept under          │
│                             .plural/backups.                                                     │
│ --json                      Print machine-readable JSON.                                         │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness push`

```text

 Usage: plural harness push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --force              Add a revision even though the hosted resource moved since you last synced. │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness release`

```text

 Usage: plural harness release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource name. Defaults to the resource directory you are in.           │
│                          [required]                                                              │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness show`

```text

 Usage: plural harness show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.
 name@REVISION shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
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
│ push   Record a finished local Job in the hosted project, with every Trial execution.            │
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

### `plural job push`

```text

 Usage: plural job push [OPTIONS] {job_id}

 Record a finished local Job in the hosted project, with every Trial execution.

 The hosted Job pins the pushed revisions the local Job ran, so push those
 first. Pushing again, or pushing a Job that was tracked, uploads only what
 the hosted Job does not hold yet.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Finished local Job to record in the hosted project. [required]           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
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
│ --track          Record a local rerun in the hosted project as it runs.                          │
│ --json           Print machine-readable JSON.                                                    │
│ --help           Show this message and exit.                                                     │
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

 Signed in to an organization, this lists the models the organization offers:
 its own endpoints and private models, and any it explicitly allows. `--all`
 lists the whole catalog and marks models the organization does not permit.
 Outside an organization, or signed out, it lists the whole catalog.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --provider        <str>  Only this provider.                                                     │
│ --all                    Every catalog model, not only the ones your organization offers.        │
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

 Each changed resource becomes a new numbered revision, dependencies first.
 Existing revisions are never overwritten or deleted, and versions never
 block a push. Label a revision with `plural <kind> release NAME VERSION`.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --yes      -y             Push without asking.                                                   │
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

 Runs execute on this machine, in the Runtime each Environment declares
 (local, docker, or a remote provider such as daytona), and stay local
 unless you pass --track. --hosted submits to hosted workers instead.

 name@version runs that exact pushed version even after your files have
 moved on. It is restored under .plural/versions without touching them.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --task            -t      <str>               Task to run: a name, or name@version for a         │
│                                               retained version.                                  │
│ --benchmark       -b      <str>               Benchmark to run: a name, or name@version for a    │
│                                               retained version.                                  │
│ --model           -m      <str>               Catalog model id.                                  │
│ --harness         -h      <str>               Harness for --model. Default: native (Plural's     │
│                                               built-in tool loop).                               │
│ --agent           -a      <str>               Saved Agent to run: a name, or name@version.       │
│ --hosted                                      Run on hosted infrastructure. Inputs the hosted    │
│                                               project lacks are pushed first.                    │
│ --track                                       Run here, and record the Job in the hosted project │
│                                               as it runs. Inputs the hosted project lacks are    │
│                                               pushed first.                                      │
│ --attempts                <int range> [x>=1]  Advanced: Trials per Task (default 1).             │
│ --concurrency     -n      <str>               Trials to run at once: a number, or auto to size   │
│                                               it from this machine, the runtime, and where the   │
│                                               model runs.                                        │
│                                               [default: auto]                                    │
│ --plural-version          <str>               Plural to install in Docker and remote sandboxes:  │
│                                               a version, or latest. Default: this CLI's own      │
│                                               code.                                              │
│ --dry-run                                     Advanced: validate and show the plan without       │
│                                               running.                                           │
│ --follow                                      With --hosted, stream progress.                    │
│ --json                                        Print machine-readable JSON.                       │
│ --help                                        Show this message and exit.                        │
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
│ release   Label the revision matching your files with a release version, pushing it first.       │
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

 Name a retained revision as name@REVISION or with --revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --revision   -r      <str>  Revision to restore: a number, version, or hash.                     │
│ --with-deps                 Also replace dependencies you already have with the exact revisions  │
│                             it pins. Missing dependencies are always restored.                   │
│ --force                     Replace local files that differ. The old copy is kept under          │
│                             .plural/backups.                                                     │
│ --json                      Print machine-readable JSON.                                         │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task push`

```text

 Usage: plural task push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --force              Add a revision even though the hosted resource moved since you last synced. │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task release`

```text

 Usage: plural task release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource name. Defaults to the resource directory you are in.           │
│                          [required]                                                              │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task show`

```text

 Usage: plural task show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.
 name@REVISION shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
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
│ --track          Record a local rerun in the hosted project as it runs.                          │
│ --json           Print machine-readable JSON.                                                    │
│ --help           Show this message and exit.                                                     │
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
│ release   Label the revision matching your files with a release version, pushing it first.       │
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

 Name a retained revision as name@REVISION or with --revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --revision   -r      <str>  Revision to restore: a number, version, or hash.                     │
│ --with-deps                 Also replace dependencies you already have with the exact revisions  │
│                             it pins. Missing dependencies are always restored.                   │
│ --force                     Replace local files that differ. The old copy is kept under          │
│                             .plural/backups.                                                     │
│ --json                      Print machine-readable JSON.                                         │
│ --help                      Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier push`

```text

 Usage: plural verifier push [OPTIONS] [name]

 Validate and push an immutable, private revision to the bound project.

 The hosted project numbers revisions. Pushing content it already holds
 reuses that revision. Without --with-deps, every dependency must
 already be pushed with identical content. Nothing is uploaded unless
 the whole push can succeed.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name. Defaults to the resource directory you are in.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-deps          Also push local dependencies that are not hosted yet.                       │
│ --force              Add a revision even though the hosted resource moved since you last synced. │
│ --json               Print machine-readable JSON.                                                │
│ --help               Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier release`

```text

 Usage: plural verifier release [OPTIONS] {name} {version}

 Label the revision matching your files with a release version, pushing it first.

 A version names one revision forever, so collaborators and Jobs can
 refer to it as name@VERSION.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name         <str>  Resource name. Defaults to the resource directory you are in.           │
│                          [required]                                                              │
│ *    version      <str>  Release version, MAJOR.MINOR.PATCH. [required]                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Print machine-readable JSON.                                                     │
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural verifier show`

```text

 Usage: plural verifier show [OPTIONS] [name]

 Show a resource: the local copy if there is one, otherwise the hosted one.

 An invalid local copy is an error, not a reason to show the hosted one.
 name@REVISION shows that revision: the working copy when it holds
 exactly that content, otherwise the retained hosted revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   name      <str>  Resource name, or name@REVISION for a retained revision: a number (@3), a     │
│                    release version (@1.0.0), or a content hash (@sha256:...). Defaults to the    │
│                    resource directory you are in.                                                │
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
