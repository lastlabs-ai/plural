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

Read the Trial evidence and the Verifier rubric before choosing a score. Replace the identifiers below with the pending Job, Trial, and Verifier IDs.

List pending local reviews:

```bash
plural review list JOB_ID
plural review submit JOB_ID TRIAL_ID \
  --verifier policy-review \
  --score 2 \
  --feedback "Compliant and actionable."
```

The local CLI `--score` form supports a Human Verifier with one criterion.
Plural does not expose a supported public package API for submitting
multiple local criterion scores.

## How the score is applied

Each criterion score must fall within its `min_score` and `max_score`. Plural
normalizes the criterion ranges, applies criterion weights, then includes the
Human Verifier score in the Task's Verifier-weighted final score.

## Evidence and access

`plural review list` reports pending identifiers and criterion metadata; it
does not expose the full contracted evidence view. A reviewer workflow must
load and authorize evidence separately. The evidence contract describes
selected Environment fields, but artifact storage and reviewer UI access are
separate security concerns.

A local submission is immutable and only one submission is accepted for a
given Trial and Human Verifier. Receipts, logs, manifests, artifact bytes, and
the submission remain immutable. The selected execution, Trial, and Job result
projections are rewritten to include the completed review and updated
aggregates; this does not mutate the captured execution evidence.

## Hosted reviews

Hosted assignments use `plural review hosted-list` and
`plural review hosted-submit`. Hosted review availability depends on the
configured Plural Intel service.
