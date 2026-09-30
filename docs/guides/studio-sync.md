---
route: /docs/guides/studio-sync
title: "Push and pull resources"
order: 300
description: "Share your project with your team by pushing it to a private hosted project as saved revisions, pull revisions back, and keep plural.lock in step."
audience: all
nav: false
---
# Push and pull resources

Your project lives on your computer. **Pushing** a resource, such as a Task or an
Agent, saves an unchangeable snapshot of it, called a **revision**, in your private
hosted project, where your team can see it and run it. **Pulling** brings a
revision's editable files back into a checkout.

You never need to push anything to run locally. Push when you want Plural to run
Jobs for you, or when you want your team to see your work in the web app.

> **Good to know:** Pushing never makes anything public. Sharing a Benchmark on the
> public Hub is a separate, explicit step.

## Bind a checkout to a hosted project

First, connect this folder to a hosted project:

```bash
plural auth login
plural project init support-eval --push
```

`--push` creates a private hosted project and registers the local project as it
is; no local file is overwritten. If a hosted project with that name already
exists, the command stops. Pass `--connect` to bind to it, or `--name` to
create a different one. The command records the binding in
`.plural/project.json`, which is not committed, and selects the project as your
[scope](../cli/evaluation.md#hosted-projects). Every push and pull from this
checkout goes to the bound project.

Before any push, the CLI compares your scope with the binding. If your scope
selects a different project or account, the push is refused before anything is
uploaded. Run `plural auth scope -p support-eval`, or `plural auth scope .` for
account scope, and retry. Scope only selects a destination; it never grants
permissions your credential does not already have. An API key limited to one
project reaches only that project, whatever scope you select.

## Push

```bash
plural project push
plural benchmark push support-triage --with-deps
plural agent push careful
```

`plural project push` pushes every local resource, dependencies first. It prints
the plan and asks before uploading; `--yes` skips the question. Changed content
becomes the next numbered revision, such as `#4`, and unchanged content reuses the
revision that already holds it. Old revisions stay, so earlier Jobs still point at
what they ran. Hosted resources that are not in this checkout are left as they are.

A few rules keep revisions trustworthy:

- **You never bump anything.** The hosted project numbers revisions itself, so
  editing a file and pushing is enough. Give a revision a version people can cite
  only when you want one; see [Release a version](#release-a-version).
- **Someone else's newer work is protected.** Each push says which revision it was
  edited from. When someone pushed a newer one in between, the push is refused
  before anything is uploaded; pull their revision and reapply your change, or pass
  `--force` to add yours on top.
- **Dependencies come first.** A push validates the resource and plans the whole
  dependency graph before it writes anything. If a dependency is not pushed yet
  or has changed locally, the push stops with nothing uploaded. `--with-deps`
  pushes those dependencies too, dependencies first, so a revision is never saved
  pointing at one that is missing.

A pushed revision is usable in its private project immediately. Sharing a
Benchmark on the public Hub is described in
[Benchmark publications](../architecture/benchmark-publications.md).

### How revisions are identified

A revision is identified by its content hash, which the CLI and the service compute
the same way from what the resource contains. Names, titles, and versions are left
out, so renaming a resource or releasing it under a version keeps its hash. Pushing
content the resource already holds, such as undoing an edit, makes that earlier
revision current again instead of creating a duplicate. The full rules are in
[Revision identity](../architecture/revision-identity.md).

### Release a version

A number such as `#4` names a revision within one resource. When you want a name
people can cite, such as `1.2.0` in a paper or a changelog, release it:

```bash
plural benchmark release support-triage 1.2.0
```

`release` pushes the resource and its dependencies if they changed, then gives the
resulting revision that version. A version names one revision forever, and
publishing a Benchmark requires one. A `version:` line in a manifest asks for the
same thing on its next push: the new revision gets that version when no other
revision has it yet, and otherwise the push says which revision already does.

## Packages

Each revision stores the resource's source files as a package, addressed by the
SHA-256 of the archive bytes. The service recomputes that digest on upload and
rejects a mismatch, and `pull` verifies it again before writing anything.

The CLI refuses to upload files that look like credentials, such as `.env` files,
private keys (`id_rsa`, `*.pem`, `*.key`), `.netrc`, and `credentials.json`.
Remove the file, or list it in the resource's `.pluralignore`. It also refuses a
resource directory that contains a symbolic link, and a package over 100 MiB
compressed. The service repeats the credential check and rejects archives with
absolute paths, `..` components, or links. Keep secrets in Environment secret
references, not in resource directories.

`.pluralignore` sits in the resource directory, beside its manifest. Each line is
one file path relative to that directory, such as `data/raw.csv`; lines starting
with `#` are comments. Entries match exact file paths only: patterns such as
`*.csv` and directory names such as `data/` are not supported, so list each file.
`.git`, `.plural`, and `__pycache__` are always left out.

## The lock file

`plural.lock` records, for every pushed resource, its revision number, release
version if any, content hash,
package digest, dependencies, and hosted resource and revision IDs, together with
the hosted project those IDs belong to. Commit it. Plural writes it after each
push and pull; do not edit it by hand. Entries recorded for another hosted
project are never used as dependency pins.

## Pull

```bash
plural benchmark pull support-triage
plural benchmark pull support-triage --revision 1.2.0 --with-deps
```

A pull restores the current revision, or the one `--revision` names by number,
release version, or content hash, along
with any dependency this project does not have yet. `--with-deps` also replaces
dependencies you already have with the exact revisions it pins.

Your edits are never overwritten silently. If local files differ from the
revision, the pull stops, changes nothing, and names the directory. Commit or
move your edits, or pass `--force` to replace the directory; the previous copy is
kept under `.plural/backups/`.

`plural run` pulls the Task, Benchmark, or Agent it names when only the hosted
project has it, so `plural run -t ui-task -m openai/gpt-5.6-luna` works on a Task
created in the web app without a separate pull.

### Revisions without a source package

Revisions created in the web app, or pushed before Plural 0.15, have no source
package. A Task, Agent, or Benchmark is only data, so a pull writes its manifest
and instructions from the stored definition. The directory is the hosted slug,
such as `tasks/ui-task/`, and `title:` keeps the display name, such as `UI Task`,
so the pulled files match the hosted revision exactly. To rename it later, change
`title:` and push; the hosted resource is renamed and its revision is unchanged. An
Environment, Verifier, or Harness carries code and still cannot be pulled without
a package; push it again from its source directory. See
[Migrate to 0.15](../migration/projects.md).

## Run pushed resources

```bash
plural run -b support-triage -a careful --track
plural job push JOB_ID
plural run -b support-triage -a careful --hosted --follow
```

- `--track` runs here and records the Job in the hosted project as it runs.
- `job push` records a local Job that already finished.
- `--hosted` submits the Job for hosted infrastructure to run.

A hosted Job pins exact revisions, so `--track` and `--hosted` first push
whatever the run needs that the hosted project does not hold: its source, its
Agent or Harness, and their dependencies. A resource whose files changed becomes
its next numbered revision, and the command prints each one. If someone changed a
resource in the hosted project since this checkout last synced it, the run stops
before uploading anything; pull it first.

`job push` uploads nothing new: the revisions a finished Job ran must already be
hosted, so restore those files and push them if they are not. See
[Jobs](../running/jobs.md) for execution and the
[Python SDK](../sdk/evaluation.md) for programmatic use.
