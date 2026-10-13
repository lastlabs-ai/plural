---
route: /docs/operations/security
title: Security
order: 934
description: What Plural keeps private, where your keys live, what the AI never sees, and how to choose isolation and data access for your evaluations.
audience: all
nav: false
nav_group: Operations
---
# Security

Plural keeps your work private by default, keeps your keys out of your project, and
never shows the AI anything beyond the Task's instructions and what the Environment
lets it see. This page explains those guarantees in plain words first, then the
settings you choose for isolation and data access.

Plural checks the safety controls you ask for and keeps a record of what ran. You
still decide which code, model providers, and people you trust.

## The short version

- **Your work stays private.** Pushing to Plural saves a private copy inside your
  hosted project. Nothing becomes public unless you publish it yourself in the web
  app.
- **Your keys never live in your project.** `plural auth login` keeps your
  credential in your computer's keyring (the operating system's password store) or a
  private file in your user settings folder. A push refuses files that look like
  credentials, such as `.env` files and private keys.
- **The AI sees only what it is meant to see.** An Agent (the contestant: a model
  plus its instructions) sees the Task's instructions and the Environment's
  Observations, and nothing else. It never sees its score, its rewards, the hidden
  State of the world, or what the grader knows.
- **Other secrets arrive when a run starts.** An API key a tool needs is declared by
  name only, and its value is supplied when the run begins. Plural hides those exact
  values in the logs it captures.

The rest of this page is for when you are running code or data you need to protect.

## Choose the process boundary

A **Runtime** is where the world runs. Each option draws the safety line in a
different place:

- `local` runs the Environment, Harness, and Verifiers as a trusted subprocess
  on your machine, under your user account. It is not a sandbox; use it only for
  code you trust.
- Docker adds container controls but trusts the host and Docker daemon.
- Daytona delegates isolation to an external service and its SDK.
- A third-party `SandboxProvider` is trusted to report and enforce its
  capabilities truthfully.

Plural refuses to start a run when the selected provider cannot enforce a
declared control. It cannot detect every provider bug or malicious
implementation.

**Opening a project runs its code.** Treat a project folder like any repository
you clone. Commands that load an Environment, such as `plural env validate`,
`plural run --dry-run`, and `plural env push`, import its Python files, start its MCP
servers to list their tools, and fetch its OpenAPI documents, all on your machine
and before any Runtime is involved. Run `plural` only in projects whose code you
trust.

## Separate information

After each action the Agent sees only what the action returned. Scores, rewards,
termination flags, State, and Verifier data never enter the model's context.

That separation governs what Plural shows the model. A Runtime with Apps also
keeps the Harness, which is the code under test, away from the grading:

- **The App host runs as its own OS user.** On Docker and Daytona the process
  that runs the Apps, their `reward` functions, and their secrets runs as a
  separate user from the Harness. Its files live in a folder only that user can
  read, and once it starts Plural deletes them from the shared workspace: the
  Environment, the Task, each App's own files, and the Verifier code that
  rewards steps. Each Trial records this as `app_isolation`.
- **The host signs what it reports.** The Harness reaches the Apps only by
  calling actions. Starting the host, collecting its records, and ending it are
  signed with a key made for each Trial that the Harness never gets, so a
  process pretending to be the host is caught and the Trial fails.
- **The host's account is the one that counts.** Rewards, observations, and
  whether the episode ended come from the host's record of each step,
  `steps.jsonl`, not from what the Harness writes. A step the Harness reports
  that the host never ran earns nothing and is marked unverified. The Verifiers
  and the stored Trial never fall back to an `observation.json`, `state.json`,
  or `view.json` the Harness wrote, even when no action ran.
- **The episode ends when the Harness's run does.** Before Plural reads the
  Harness's files or the host's record, it kills every process the Harness's
  users still run, on Docker and Daytona, and the host then refuses any further
  action, so nothing the Harness started can act while the Verifiers run. A
  Harness that timed out after the host ran an action is not retried, so it
  cannot re-roll an episode that was going badly.
- **Declared files are read as regular files only.** A file the Harness
  declares is collected only when it is a regular file inside the Harness's
  folder, never a symlink or a path that leads to the host's folder.
- **Each App's process sees only its own values.** An MCP server or OpenAPI
  hook gets the credentials and secrets that App declares, not another App's.
  Remote MCP servers may not redirect, so a credential header never follows a
  redirect elsewhere.
- **Verifier code never reaches the Runtime for scoring.** `check` runs after
  the Harness has finished, outside the Runtime. Only `reward` functions run
  beside the Apps, inside the host's private folder.
- **Harness setup runs first.** A Harness's `setup` commands run as root, to
  install its tools, so they run before the App host starts and before any
  secret, seat token, or App file is in the Runtime. For the strongest
  boundary, bake those tools into the Runtime image and leave `setup` empty.
- **Seats in a party are kept apart.** Each seat's Harness runs as its own OS
  user, in a folder no other seat can open, and the Trial fails rather than
  play without that, unless the Environment's party chooses `shared` seats,
  which the Trial records as `seat_isolation: none`. See
  [What each seat sees](../project/multi-agent.md#what-each-seat-sees-and-what-it-cannot).

On the `local` Runtime the Harness and the Apps share your user account, so
there is no OS boundary and each Trial records `app_isolation: none`. Use Docker
or Daytona for scores you rely on. Daytona isolation needs `sudo` and `useradd`
in the image, and an Agent user that cannot use `sudo`; on an image without
them the Trial runs without the boundary and records `app_isolation: none`.

Verifiers (the graders) receive the full final Episode, including State. Isolate
untrusted Verifier code and avoid capturing secrets.

## Handle secrets

Credentials are never stored in a project. `plural auth login` keeps its
credential in your OS keyring or a private file in your user config directory,
and a push refuses files that look like credentials, such as `.env` files and
private keys.

Supply other secrets when the Job runs:

- **Credentials.** An App's credentials, such as a CRM token, belong to the
  person running the Agent. Each person saves their own with
  `plural credential set` or on their Profile; values are encrypted, and only
  that person's own sign-in can use them. A project API key, as in CI, cannot,
  so CI exports them instead. Like secrets, they reach only the App host.
- **App secrets.** Each App declares the names of the secrets it needs, such as
  the token for its MCP server; the declarations never hold values. At run time
  Plural reads the values from the Job's environment, or from the hosted
  project's secrets (`plural secret set`), and gives them only to the process that
  runs the Apps and to Verifier queries. They never reach the Agent or its
  Harness. A missing value stops the run before it starts, naming the App.
- **Runtime variables.** `RuntimeVariable` declarations on a Runtime carry
  settings into the Runtime. The Harness shares the Runtime and can read them,
  so keep credentials on Apps instead.
- **Harness secrets.** A custom Harness lists the names it reads in `secrets`,
  and an Agent grants a subset with `secret_names`. Granting a name the Harness
  did not declare fails before any value is forwarded.
- **Model keys.** A Job passes model credentials to the Harness and to Agent
  Verifiers itself; you do not list them in `secret_names`.

Never store values in YAML, Task info, State, action results, resources, logs, or
artifacts.

> **Good to know:** Plural replaces the exact values of injected secrets in the
> Harness and Verifier logs it captures, in the App host's step record, States,
> and snapshots it stores, and in a Trial's error message. It cannot catch an
> encoded or transformed secret, and it does not redact files the Harness writes
> or data your code sends elsewhere.

## Hosted access

- `plural auth scope` selects where hosted commands go. It never changes what
  your credential may do.
- A browser login stores a 30-day API key for the one account, personal or an
  organization, that was selected in the browser that approved it. It appears
  under Keys in that account, and `plural auth logout` deletes it. An API key
  limited to one project reaches only that project; use one for CI.
- Pushing saves a private revision in your project and never makes anything
  public. Listing a resource on the Hub and
  [publishing a Benchmark release](../architecture/benchmark-publications.md)
  are separate, explicit actions in the web app.
- Organization admins can restrict which models members may use. The service
  enforces that list for runs, reruns, and model calls through the gateway.

## Lock code and output

Plural fingerprints your code and results so you can tell if something changed.
Those fingerprints prove *what* ran, not *who* made it or whether it is safe.

Environment and Harness source digests detect changes. Remote archives and OCI
sources require digests. These are integrity checks, not signatures,
attestations, publisher identity, or malware scanning.

Artifact SHA-256 values and receipts detect edits after a run. Receipts are
unsigned; a local run reports `self_reported` trust, and imported runs report
`imported_unverified`.

## Minimize capability

Give each run only what it needs:

- Use a pinned image, modest compute and time limits, focused actions, and a
  read-only root where supported.
- Allow access to the model endpoint and other services the Task needs. For a fully
  offline workflow, block networking with a Runtime that supports it.
- Grant optional Harness capabilities only when the workflow requires them; see
  [Harness and Environment policy](../concepts/harness-policy.md).

A hosted project's policy is an additional ceiling. It cannot enforce a control
that the selected Runtime provider does not support.

Read [Runtime](../project/environments.md#runtime), [Artifacts and evidence](../running/artifacts.md),
and [Known limitations](../reference/limitations.md) before processing
sensitive data.
