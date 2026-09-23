---
route: /docs/running/reviews
title: "Reviews"
order: 100
description: Review completed agent work, submit a human score, and understand how it affects the result.
audience: all
nav: true
nav_group: Run
outcome: You know when a Trial waits for a person and what that person is allowed to see.
---
# Reviews

Use a Human Verifier when a person needs to judge the result. After the agent and automatic Verifiers finish, the Trial waits at `awaiting_review` until the required review is submitted.

## Submit a review

Read the Trial evidence and the Verifier rubric before choosing a score. List
the local Trials waiting for review, then submit a score for one of them:

```bash
plural review list
plural trial show TRIAL_ID
plural review submit TRIAL_ID \
  --verifier policy-review \
  --score 2 \
  --feedback "Compliant and actionable."
```

A bare `--score` value works when the Human Verifier's rubric has one criterion.
For a rubric with several criteria, repeat `--score criterion=value` once for
each criterion. `--verifier` names the Human Verifier and is required only when
the Trial has more than one.

## How the score is applied

Each criterion score must fall within its `min_score` and `max_score`. Plural
normalizes each criterion's range to 0 to 1, applies criterion weights, then
combines the Human Verifier's score with the other Verifiers' scores by their
`weight` to produce the Trial's score.

## Evidence and access

`plural review list` reports the pending Trial, Job, and Verifier identifiers; it
does not expose the full contracted evidence view. Open the evidence with
`plural trial show TRIAL_ID` and the artifacts directory it prints. Whoever can
read that directory can read all of the Trial's evidence, including internal
State, so control reviewer access to the artifacts separately.

A local submission is immutable, and only one submission is accepted for a
given Trial and Human Verifier. Receipts, logs, manifests, artifact bytes, and
the submission itself never change. Plural updates the Trial and Job
`result.json` summaries to include the review and the new score.

## Hosted reviews

Hosted review assignments use the same commands with `--hosted`:

```bash
plural review list --hosted
plural review submit ASSIGNMENT_ID --hosted --score quality=2
```

A hosted submission names each criterion with `criterion=value`. Hosted reviews
need `plural auth login` and a selected project.
