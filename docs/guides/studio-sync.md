---
route: /docs/guides/studio-sync
title: "Push and pull resources"
order: 300
description: "Push project resources to a private hosted project as immutable revisions, pull them back, and keep plural.lock in step."
audience: all
nav: false
---
# Push and pull resources

A project lives on your machine. Pushing a resource makes an immutable revision of
it usable in a private hosted project, where your team can run it. Pulling
restores a revision's editable files into a checkout. Nothing needs to be pushed
to run locally.

## Bind a checkout to a hosted project

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
the plan and asks before uploading; `--yes` skips the question. Unchanged
content reuses the existing revision. A resource whose files changed under the
same `version` is refused; `--bump` gives each of those the next patch version
and pushes a new revision. Old revisions stay, so earlier Jobs still point at
what they ran. Hosted resources that are not in this checkout are left as they
are. Push refuses when the hosted project has a newer revision this checkout
has not pulled, unless you pass `--force`.

A push validates the resource and plans the whole dependency graph before it
writes anything. If a dependency is not pushed yet or has changed locally, the
push stops with nothing uploaded. `--with-deps` pushes those dependencies too,
dependencies first, so a revision is never saved pointing at one that is missing.

A revision is identified by its version and content hash, which the CLI and the
service compute the same way. Pushing unchanged content reuses the existing
revision instead of creating a duplicate. Pushing different content under a
version that already exists is refused; bump `version:` in the manifest first.
Pushing the same content under a new version is refused too, and the error
names the version that already holds it. A pushed revision is usable in its private project immediately. Pushing
never makes anything public; sharing a Benchmark on the public Hub is a separate,
explicit step described in
[Benchmark publications](../architecture/benchmark-publications.md).

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

`plural.lock` records, for every pushed resource, its version, content hash,
package digest, dependencies, and hosted resource and revision ids, together with
the hosted project those ids belong to. Commit it. Plural writes it after each
push and pull; do not edit it by hand. Entries recorded for another hosted
project are never used as dependency pins.

## Pull

```bash
plural benchmark pull support-triage
plural benchmark pull support-triage --version 1.2.0 --with-deps
```

A pull restores the current revision, or the one named by `--version`.
`--with-deps` also restores the exact dependency revisions it pins. Local files
that differ from the revision are never overwritten silently: the pull stops,
changes nothing, and names the directory. Commit or move your edits, or pass
`--force` to replace the directory; the previous copy is kept under
`.plural/backups/`.

Revisions created in the web app, or pushed before Plural 0.15, store only the
compiled definition and have no package, so they cannot be pulled. Push them
again from their source directory. See [Migrate to 0.15](../migration/projects.md).

## Run pushed resources

```bash
plural run -b support-triage -a careful --hosted --follow
```

`--hosted` uses revisions that are already pushed and refuses to run when any
input differs from its pushed revision. Push first, then run. See
[Jobs](../running/jobs.md) for execution and the
[Python SDK](../sdk/evaluation.md) for programmatic use.
