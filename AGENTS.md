# Working in this repository

`README.md` covers what Plural is, and `CONTRIBUTING.md` covers setup, the checks CI runs,
and the definition of done for a public symbol. This file covers the conventions that are
easy to violate: what is generated, where the docs are published, and which words mean
what.

## Generated files: never edit these by hand

CI fails on drift in every one of these, so regenerate rather than patch.

| File | Command |
| --- | --- |
| `src/plural/schemas/trace.v3.json`, `schemas/trace.v3.json`, `docs/schemas/trace.v3.json` | `uv run python scripts/generate_trace_schema.py` |
| `src/plural/schemas/packages/**` | `uv run python scripts/generate_package_schemas.py` |
| The reference section of `docs/cli/evaluation.md` | `uv run python scripts/generate_cli_reference.py` |
| `docs/reference/fields.md`, `docs/assets/project-schemas.json` | `uv run python scripts/generate_docs_fields.py` |
| `docs/reference/api.md` | `uv run python scripts/generate_docs_api.py` |
| `docs/assets/first-project.zip` | `uv run python scripts/sync_docs_starter.py` |

Each takes `--check` to report drift without writing. CI also runs
`uv run mypy --strict src/plural tests/typing/consumer.py` and the test suite on every
supported Python, from 3.10 up, so code under `examples/` must run on 3.10 too.

## Docs and examples are published elsewhere

`docs/` is the canonical product documentation. pluralintel.com mirrors it, along with
the `first-project`, `quoting`, and `wordle` examples, so a page or example changed here
changes the website at the next sync. `scripts/check_docs.py` validates every page's
frontmatter, internal links and anchors, and the CLI commands in `bash` fences.

`tests/unit/test_documentation.py` validates and dry-runs each tutorial project, and
`tests/unit/test_quoting_example.py` runs the quoting example end to end against a
scripted model. Keep both passing when you change an example.

## Vocabulary

The core vocabulary (Task, Verifier, score, reward, App, Environment, Harness, Agent,
Benchmark, Job, Trial) is defined in `docs/reference/glossary.md`. Two distinctions are
load-bearing everywhere: a **score** is what a Verifier's `check` produces and the only
thing a Benchmark ranks on, and a **reward** is credit on one step of a trajectory,
recorded in the reward ledger, which reaches a score only through `check: total_reward`.
Nothing a Verifier computes, and no State or answer key, may reach the Agent or its
Harness.

### Evaluation vocabulary

These words belong to the evaluation foundation (`docs/specs/plural-spec.md` in
pluralintel), which is being built in milestones. Its rule: every feature is a field on
an existing primitive, a verb in that primitive's existing command group, or an agent
built on Plural. No new resource kinds and no new top-level command groups. Use these
words, and only these, for the things they name. Keep the glossary's "Evaluating and
improving an Agent" section in step.

- A **Metric** is a named measurement a Verifier declares. It has a **kind** (`binary`,
  `score`, `number`, `rating`, `running`), a **direction**, an optional **unit**, and
  optionally `gate: true` and a `target`. A Verifier's `check` produces metric values at
  the end of the episode, and its `measure` hook produces values for a **running
  metric** after each step. `None` means not applicable. Metrics are measurements, not
  credit: they never enter the reward ledger.
- A **gate** is a metric with `gate: true`. A Trial **passes** when every applicable
  gate passes; with none applicable it is **not judged** (`passed` is `None`).
- **Success rate** is the share of Trials whose score reached the success threshold.
  **Pass rate** is the share of judged Trials that passed every gate. Never use one
  word for the other.
- **Score** keeps its meaning: the weighted Verifier score on a Trial (`Trial.score`).
  `primary_metric` may name any declared metric instead of `score`.
- **Reward** keeps its meaning: credit for one action, in `rewards.jsonl`. A reward is
  never a metric, and a metric is never a reward.
- A Benchmark's **held-out** Tasks (`heldout:`) are kept back for confirmation.
  Diagnosis never looks at them, and their results stay hidden until revealed. Each run
  against them, and each reveal, is a **peek**, and is counted.
- A **trust tier** (`verified`, `standard`, `unverified`) is computed for every Trial
  from how it ran: isolation, network enforcement, a pinned image, provider conformance,
  and a signed host report.
- A **Checkpoint** is everything needed to restart a Trial exactly as it stood after
  step *k*: each App's State and RNG state, the workspace, the host counters, the
  Environment clock, and the Agent's context.
- A **Fork** is a Trial started from another Trial's Checkpoint, by another Agent or, as
  a **control**, by the original Agent.
- A **change** is one thing a Fork alters at the fork point other than the Agent (an
  observation, a message, the next action), registered with `@change("name")`. A Fork
  with a change is **diagnostic**: it explains a cause, and is never shipped.
- The **Inspector** is Plural's investigating agent, an Agent built on Plural with
  read-only evidence tools over a Job and Forks as experiments.
- A **Finding** is the Inspector's conclusion about one failed Trial: the critical step,
  a cause dimension (model, context, tools, instructions, Harness, environment, grader,
  task, integrity, or one a project adds), the cause, the evidence, the Forks that
  tested it, and a status (`confirmed`, `inferred`, `refuted`, `inconclusive`).

In code: `MetricSpec`, `Checkpoint`, `ForkSpec`, and `Finding`. A fix is a new Agent
revision, never a resource of its own.
