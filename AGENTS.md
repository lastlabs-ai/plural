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

These words belong to the evaluation foundation, which is being built in milestones.
Most of them name things that don't exist in code yet; use them, and only them, for
those things when they arrive. Keep the glossary's "Evaluating and improving an Agent"
section in step.

- A **Metric** is a named, declared measurement of an episode. It has a **kind**
  (`binary`, `score`, `number`, `rating`, `running`), a **direction**, an optional
  **unit**, and a **role**: a **gate** must pass; an **objective** is something to
  maximize or minimize; a **guardrail** is reported but never ranked on. A Verifier's
  `check` produces metric values at the end of the episode, and its `measure` hook
  produces values for a **running metric** after each step. Metrics are measurements,
  not credit: they never enter the reward ledger.
- **Score** keeps its meaning: the weighted Verifier score on a Trial (`Trial.score`).
  When a Benchmark has a Scorecard, `primary_metric` may name one of the Scorecard's
  objectives instead of `score`.
- **Reward** keeps its meaning: credit for one action, in `rewards.jsonl`. A reward is
  never a metric, and a metric is never a reward.
- A **Scorecard** is a versioned project resource that records what "good" means for one
  workflow: its plain-language definition, its Metrics, the **decisions** that settled
  disagreements, and the **labels** used to check the graders.
- A **Label** is a person's judgment of one Trial against a Scorecard's Metrics, with a
  reason. Labels check graders. They never change a score.
- A Benchmark's **held-out** Tasks are kept back for confirmation. Diagnosis and fixing
  never look at them. Each run against them is a **peek**, and is counted.
- A **Checkpoint** is everything needed to restart a Trial exactly as it stood after
  step *k*: each App's State and RNG state, the host counters, and the Agent's context.
- A **Fork** is a Trial started from another Trial's Checkpoint, with an
  **Intervention** (a change) or with none (a **control**).
- An **Intervention** is a typed change applied at the fork point. A **deployable** one
  changes the Agent (model, instructions, Harness config, the whole Agent). A
  **diagnostic** one changes one moment of the episode (an observation, the next action,
  an injected hint) and is used only to find causes.
- The **Inspector** is Plural's investigating agent. It explains why an Agent fails,
  using read-only evidence tools and experiments (forks). One run of it over a Job is an
  **Investigation**.
- A **Finding** is the Inspector's conclusion about one failed Trial: the critical step,
  a **cause kind** (a dimension of the **cause lens**: model, context, tools,
  instructions, Harness, environment, grader, task, integrity, or one a project adds), a
  free-text cause, the evidence, the experiments, a status (`confirmed`, `inferred`,
  `refuted`, `inconclusive`), and suggested fixes.
- A **failure pattern** is a reusable, named kind of failure, with a signature, a way to
  confirm it, and fixes with measured effects. Patterns live in a **library** at project,
  organization, and Plural scope. A **failure mode** is a group of Findings in one Job
  that share a pattern or cause.
- A **Fix** is a deployable change under test, with a lifecycle: proposed, tested,
  applied, confirmed (or rejected).
- A **trust tier** (`verified`, `standard`, `unverified`) is computed for every Trial
  from how it ran: isolation, network enforcement, a pinned image, provider conformance,
  and a signed host report.
- An **Eval Report** is an immutable document generated from pinned inputs (Scorecard
  version, Jobs, Investigation, Fixes) that answers three questions: how well the Agent
  works, where and why it fails, and which change makes it better and how sure we are.

In the UI and docs, say "Eval Report", "Scorecard", "Finding", "Fix", and "Fork". In
code: `EvalReport`, `Scorecard`, `Finding`, `Fix`, `ForkSpec`, `Checkpoint`, `Metric`,
and `Label`.
