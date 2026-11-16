---
route: /docs/project/scorecards
title: Scorecards
order: 57
description: "A Scorecard writes down what good work means for one workflow: in words, as metrics with gates, objectives, and guardrails, and as the decisions and labels that check the graders."
audience: all
nav: true
nav_group: Build
outcome: You can draft a Scorecard, label Trials against it, check that its graders agree with your team, and rank a Benchmark by it.
---
# Scorecards

A **Scorecard** writes down what good work means for one workflow, such as answering
steel quote requests. It has four parts:

- **The definition**: what good looks like, in plain language, for the people who own
  the work. Plural keeps it in `GOOD.md`.
- **Metrics**: the [metrics your Verifiers declare](verifiers.md#declare-metrics), each
  with a **role**.
- **Decisions**: how you settled the cases your team disagreed on.
- **Labels**: your team's own judgments of real Trials, used to check that the graders
  agree with people.

A Scorecard never changes a score. It decides which Trials pass, what a Benchmark ranks
on, and whether you can trust the graders that produced the numbers.

## Give each metric a role

| Role | Meaning | Steel quoting example |
| --- | --- | --- |
| `gate` | Must pass. A Trial that fails any gate fails. | `price_correct`, `above_cost` |
| `objective` | Something to maximize or minimize. A Benchmark can rank on it. | `margin_usd` of at least 150 |
| `guardrail` | Reported, never ranked on. | `cost_usd` under $0.50 |

```yaml
name: steel-quoting
version: 1.0.0
workflow: Respond to inbound steel RFQs with an accurate, profitable quote.
owner: KB (sales lead)
good: |
  A good quote is correct on price, grade and delivery, never below cost,
  and goes out fast. When unsure, the agent asks or hands off rather than guessing.
metrics:
  - name: decision_correct
    role: gate
  - name: price_correct
    role: gate
  - name: margin_usd
    role: objective
    target: ">= 150"
  - name: cost_usd
    role: guardrail
    target: "<= 0.50"
primary: margin_usd
calibration:
  min_labels: 20
  min_agreement: 0.6
```

Save it as `scorecards/steel-quoting/scorecard.yaml`. Each metric is one a Verifier on
the Benchmark's Tasks declares, or a built-in such as `cost_usd`. Its kind, unit, and
direction come from there; the Scorecard adds the role.

A `target` is `>= N`, `<= N`, `== N`, or `between A B`. A binary gate with no target
passes at 1. `applies_to` limits a metric to some Tasks or Benchmark categories, when it
isn't produced on every Task. `weight` sets how much an objective counts in the report.

A gate whose value is `None` doesn't apply, so it doesn't fail the Trial: a correct
handoff has no price, and passes on its other gates. A Trial **passes** when every gate
that applies passes. A Job reports its **pass rate** next to its score.

## Attach a Scorecard to a Benchmark

Name it in the Benchmark's file:

```yaml
name: quoting
scorecard: steel-quoting
primary_metric: margin_usd
```

`primary_metric` can then name one of the Scorecard's objectives instead of `score`, and
the leaderboard ranks by it. Every Trial records which gates it passed. The Benchmark
refuses a Scorecard metric that no Verifier on its Tasks declares, so each metric has
a grader.

## Draft one from your documents

You don't have to start from a blank file. `plural scorecard draft` reads your process
documents and a sample of real conversations, finds what matters and where sources
disagree, and asks you five questions:

```bash
plural scorecard draft steel-quoting \
  --docs docs/ --traces conversations.jsonl --environment mill
```

It shows a cost estimate before calling a model, and accepts `--model` and
`--budget-usd`. It calls models through the gateway with a key minted for this draft
alone, revoked when it ends, never your own key. It writes:

- `scorecard.yaml` and `GOOD.md`;
- `questions.md`, the questions it asked and your answers;
- a Verifier for each kind of check the new metrics need: code checks marked
  `PLURAL-TODO` for you to finish, a model judge, or a person's review.

Read and edit everything it wrote. The draft is a starting point, not a verdict.

## Label Trials

Graders make mistakes. Before you trust a metric, compare its grader with what your
team says on the same Trials. Label Trials from a Job:

```bash
plural scorecard label steel-quoting --job JOB_ID --labeler kb
```

It picks Trials the graders passed and failed, one per Task first, and asks about each
binary and rating metric, then an overall verdict: good, bad, or unsure, with a reason.
Labels are saved in `.plural/labels/` in the project. A **Label** never changes a score;
it only checks the graders.

Two or more people should label the same Trials, so you can tell a bad grader from a
metric your team doesn't agree on. To bring in labels collected elsewhere, pass
`--import` a JSONL file with one line per label, keyed by Task and Agent:

```json
{"task": "quote-009", "agent": "quote-bot", "labeler": "kb", "values": {"price_correct": 1, "tone": 4}, "verdict": "good", "reason": "Right price, clear next step."}
```

On a hosted project, the Scorecard's **Label** tab gives you the same queue in the
browser.

## Check the graders

```bash
plural scorecard calibrate steel-quoting
```

`calibrate` compares, metric by metric, how much your labelers agree with each other
(Cohen's kappa for two labelers, Fleiss' for more, on binary and rating metrics;
Spearman's rho on numbers) and how much the grader agrees with their consensus. Each
metric gets a status:

| Status | Meaning | What to do |
| --- | --- | --- |
| Trusted | The grader agrees with the team at least `min_agreement` | Nothing |
| Needs work | The team agrees; the grader doesn't | Fix the Verifier |
| Define it better | The team disagrees with itself | Settle it with a decision, then label again |
| Not calibrated | Fewer than `min_labels` labels, or no grader values | Label more Trials |

The result is saved for that Scorecard version. The hosted **Agreement** tab runs the
same calibration on the hosted labels.

## Record decisions

When `calibrate` finds a metric your team disagrees on, settle it:

```bash
plural scorecard decide steel-quoting
```

It walks through the disagreements, records each ruling in `scorecard.yaml`, bumps the
patch version, and rewrites `GOOD.md`. To record one ruling without the queue:

```bash
plural scorecard decide steel-quoting --metric delivery_feasible \
  --question "Is a quote with the right price but an unmeetable date acceptable?" \
  --answer "No. Delivery feasibility is a gate." --by KB
```

## Rescore without rerunning

Changing a gate's target doesn't need a new run. `rescore` applies the Scorecard to a
Job's stored metrics:

```bash
plural scorecard rescore steel-quoting --job JOB_ID
plural scorecard rescore steel-quoting --job JOB_ID --target "margin_usd=>= 200"
```

With `--target`, it shows what a different target would do without saving it. If a
Verifier changed, the metrics themselves change: use
[`plural verifier apply`](verifiers.md#try-a-verifier-on-stored-trials) instead.

## See also

- [Verifiers](verifiers.md#declare-metrics): declare metrics and running metrics.
- [Benchmarks](benchmarks.md#hold-tasks-out): hold Tasks out to confirm a fix.
- The `quoting` example ships the `steel-quoting` Scorecard and 20 Trials' worth of
  synthetic labels from two labelers, in `labels/steel-quoting.jsonl`.
