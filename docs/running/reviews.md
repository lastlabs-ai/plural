---
route: /docs/running/reviews
title: "Reviews"
order: 100
description: When a person needs to grade the work, the Trial waits for them. Submit a human score and see how it combines with the automatic ones.
audience: all
nav: true
nav_group: Run
outcome: You know when a Trial waits for a person and what that person is allowed to see.
---
# Reviews

Some work can only be judged by a person. Was the reply to the customer polite?
Does the plan follow company policy? For those, you add a **Human Verifier**: a
rubric that a person fills in after the attempt.

After the Agent and any automatic Verifiers finish, the Trial waits at
`awaiting_review` until the required review is submitted. Its final score is ready
only once the person has graded it. In the web app, reviews live under Reviews.

## Submit a review

Read the Trial's evidence and the Verifier's rubric before choosing a score. List
the local Trials waiting for review, open one, then submit a score for it:

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
the Trial has more than one. `--feedback` is optional notes for the record.

## How the score is applied

Your score joins the automatic ones to make the Trial's final score.

Each criterion score must fall within its `min_score` and `max_score`. Plural
normalizes each criterion's range to 0 to 1, applies criterion weights, then
combines the Human Verifier's score with the other Verifiers' scores by their
`weight` to produce the Trial's score.

## Evidence and access

`plural review list` reports the pending Trial, Job, and Verifier identifiers; it
does not expose the full contracted evidence view. Open the evidence with
`plural trial show TRIAL_ID` and the artifacts directory it prints.

> **Good to know:** Whoever can read that directory can read all of the Trial's
> evidence, including the hidden State. Control reviewer access to the artifacts
> separately.

A local submission is immutable, and only one submission is accepted for a
given Trial and Human Verifier. Receipts, logs, manifests, artifact bytes, and
the submission itself never change. Plural updates the Trial and Job
`result.json` summaries to include the review and the new score.

## Hosted reviews

Reviews for Jobs in your hosted project come as review assignments. Use the same
commands with `--hosted`:

```bash
plural review list --hosted
plural review submit ASSIGNMENT_ID --hosted --score quality=2
```

A hosted submission names each criterion with `criterion=value`. Hosted reviews
need `plural auth login` and a selected project.
