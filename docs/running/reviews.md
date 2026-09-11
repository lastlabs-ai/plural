---
route: /docs/running/reviews
title: "Reviews"
order: 100
description: "A human Verifier pauses the Trial at awaiting_review. The reviewer sees the same evidence view the contract asked for, then the Trial unblocks."
audience: all
nav: true
nav_group: Running
outcome: You know when a Trial waits for a person and what that person is allowed to see.
---
# Reviews

A human Verifier does not run a command. It parks the Trial.

```bash
plural verifier init review.yaml --name legal-play --kind human
```

When that Verifier is pinned on a Task, the Job still runs the Agent and any deterministic Verifiers. Then the Trial status becomes `awaiting_review`. Plural Intel lists it under Reviews.

```mermaid
flowchart LR
  job[Job]
  trial[Trial]
  pause[awaiting_review]
  human[Reviewer]
  done[scored]
  job --> trial
  trial --> pause
  pause --> human
  human --> done
```

The reviewer sees the same `environment_view` the evidence contract asked for: selected artifacts, observation paths, and hidden state only if the contract said so. They do not get a raw dump of the Environment. They score the rubric. The Trial unblocks with that score rolled into the reward.

What this unlocks: you can keep a deterministic solver in the loop and still require a person for the cases a script cannot judge. The [Wordle tutorial](../tutorials/wordle.md) stays automatic; add a human Verifier when you want this pause.
