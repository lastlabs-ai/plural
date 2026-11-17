---
route: /docs/operations/integrity
title: Integrity
order: 936
description: How Plural checks that a Benchmark measures the work, not a shortcut. Probe the graders, scan for leaks, and flag Trials that look like exploits.
audience: all
nav: false
nav_group: Operations
---
# Integrity

A high score means something only when the Agent could not get it without doing
the Task. Plural checks this at three points:

1. **Before any Agent runs**, `plural task validate` proves each Task can be solved and
   can't be passed by doing nothing.
2. **Before a baseline**, the same command scans everything the Agent can read for the
   answer or the graders, and `plural benchmark validate` also reports the default
   Runtime's trust.
3. **After every recorded Trial**, detectors look for signs that the Agent exploited
   the Environment instead of doing the work.

Findings are evidence for a person. On their own they never change a score.

## Check the graders

```bash
plural task validate                # every Task
plural task validate quote-001      # one Task
plural benchmark validate quoting   # a Benchmark's Tasks, against its success threshold, plus trust
plural task validate --no-probes    # the files only, without running anything
```

Each Task runs through the normal engine, in its own Runtime, with fixed players in
place of an Agent:

| Probe | Plays | Must |
| --- | --- | --- |
| `reference` | The Task's reference policy | Pass |
| `noop` | Nothing | Fail |
| `echo` | Answers with the Task's instructions | Fail |
| `random` | Random actions, with `--random N` | Fail; a pass is a warning |

A `reference` that fails means the Task or its grader is broken, not the Agent. A
`noop` or `echo` that passes means the grader rewards nothing. Each result is saved
in `.plural/checks/` and kept until the Task changes. When you are signed in, it is
also recorded on the Task's revision, and the **Tasks** list shows a **Check** badge.

### A reference policy

A reference policy is a Python function that solves a Task the way a careful person
would, using only what an Agent sees. Declare one for the whole Environment, or for
one Task in place of its Environment's:

```yaml
# environment.yaml or task.yaml
reference: reference.py:solve
```

```python
def solve(task, environment):
    environment.reset()
    price = environment.step("lookup_price", grade="A36")
    ...
```

It is called with the Task and the episode, and acts through the same `step` an Agent
uses. It never reaches the Agent, and it is not part of the Task's or Environment's
identity, so editing it does not create a new revision.

## Scan for leaks

The check reads everything the Agent can: the instructions, `info` and `metadata`,
the Task's files, the Environment's resources, and the sandbox's working folders as
the `noop` probe found them. It reports:

| Code | What it found |
| --- | --- |
| `answer_key` | The Task's `expected`, or a part of it at least six characters long |
| `git_history` | A git repository with more than its checked-out commit, or with tags or other branches |
| `solution_file` | A file named like `solution*`, `answer*`, `reference*`, `*.orig`, or `*.rej` |
| `verifier_copy` | A file identical to a Verifier's source |
| `canary` | The Benchmark's [canary](../project/benchmarks.md#integrity) |
| `not_scanned` | A file whose format can't be read |

Text is read from PDFs when `pypdf` is installed, and from Word, Excel, and PowerPoint
files, including their document properties, comments, tracked changes, and hidden
sheets. A file that can't be read, such as an image or a CAD drawing, is reported as
`not_scanned`, never as clean.

## Flag suspicious Trials

Every recorded Trial is checked from what Plural already recorded: the App host's
steps and States, the files the Harness left, its logs, and the Verifiers' results. No
detector calls a model.

| Code | Severity | Means |
| --- | --- | --- |
| `forbidden_read` | critical | The Harness was refused a read of the App host's folder, a Verifier file, or the reward ledger |
| `grader_file_touch` | critical | An action or command names a Verifier file, `rewards.jsonl`, `states.jsonl`, or the App host's folder |
| `canary_seen` | critical | The Benchmark's canary appears in what the Agent produced |
| `suspicious_success` | warning | The Verifiers passed, yet the Agent changed nothing and its answer is not the answer key |
| `egress_denied` | warning | The Runtime blocked a connection the Agent tried. No provider reports blocked connections yet, so this does not appear today |

An [External Agent](../project/external-agents.md) reports its own trace, and where it
disagrees with what the App host observed, the Trial lists that too: actions the trace
claims but the host never saw, actions it left out, a final answer that differs, and
steps timed outside the episode. On a recorded run, `model_calls_differ` means the
trace reports a different number of model calls than the gateway counted on the
Trial's own key.

Findings appear on the Trial, in `plural trial show`, and in the Trial table, which
can filter to flagged Trials. A Benchmark release decides what a `critical` finding
does to its attempt with
[`scoring.integrity`](../project/benchmarks.md#integrity).

## Trust tiers

Integrity findings are about what an Agent did. A Trial's
[trust tier](../project/runtimes.md#trust-tiers) is about whether the sandbox could
have stopped it: isolation, network enforcement, a pinned image, provider
conformance, and a signed host report.
