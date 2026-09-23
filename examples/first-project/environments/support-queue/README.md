# Support queue

## Overview

A customer support queue with one open ticket per Task. The Agent reads the ticket and
the policy that applies to it, assigns a category, drafts a reply, and resolves the
ticket. The episode ends when the ticket is resolved.

## Actions

| Action | Arguments | Effect |
| --- | --- | --- |
| `inspect_ticket` | none | Returns the ticket and its policy. |
| `categorize` | `category`: `billing`, `technical`, or `account` | Sets the category. |
| `draft_response` | `message`: text | Saves a customer-facing reply. Needs a category. |
| `resolve` | none | Resolves the ticket. Needs a category and a reply. |

## State

`ticket_id` is set by each Task's `initial_state`. `expected` holds the correct
category; it is private, so Agents never see it and the Verifier compares against it.
The rest mirrors the ticket's progress: `category`, `draft_reply`, `status`, `done`.

## Observations

`ticket_id`, `customer_tier`, `issue`, `policy`, `category`, `draft_reply`, `status`,
and `done`. The expected category is never observed.

## Rewards

0.25 for each step that advances the ticket (open, triaged, drafted, resolved). Rewards
are recorded for training only and never contribute to a score.

## Resources

`resources/policy.md`: the support policy, staged into the runtime.

## Runtime

`local`: a trusted subprocess on your machine. It is not a sandbox.

## Settings

Any harness may run here. Each Trial is limited to 6 turns and 120 seconds.
