---
route: /docs/project/environment-components
title: Environment components
order: 37
description: Define actions, State, Observation, Rewarders, resources, lifecycle setup, rendering, limits, and information boundaries.
audience: all
nav: true
nav_group: Build
---
# Environment components

Use this page after [Environments](environments.md). These components belong to
one Environment version and therefore contribute to its content hash.

## Actions

An `@action` is a world operation available to the Agent:

```python
from plural import action

@action
def assign(self, team: str) -> dict[str, str]:
    """Assign the ticket to a support team."""
    self.state.team = team
    return {"team": team}
```

Typed parameters become JSON Schema. Keep actions narrow, validate inputs, and
return useful error information. Avoid a generic shell action unless arbitrary
code execution is the task and the Runtime is designed for it.

`reset()` and `step()` are lifecycle methods, not actions. The Job resets an
episode, the Harness asks the model for a move, and `step()` applies it.

## State and Observation

State is durable internal truth. Observation is the Agent-visible projection:

```python
from plural import Observation, State

class TicketView(Observation):
    issue: str = ""
    status: str = "open"

class TicketState(State):
    expected_team: str = ""
    issue: str = ""
    status: str = "open"
```

State is never sent to the Agent. Observation is the only visible surface.
Never put credentials in State.

Override `Observation.render()` to produce policy-facing text. Override
`Environment.view()` to produce a JSON operator display. Persisted
`observation.json`, `state.json`, and `view.json` are run artifacts.

## Reset and setup

`reset(seed=..., options=...)` returns `(observation, info)`. A Task can supply
`initial_state` and `reset_options`; initial State is schema-checked while
reset behavior remains Environment code. Plural serializes and hashes
`reset_options`, but the package command adapter does not yet forward them to
`reset`; use Task info or initial State in that path.

Make reset deterministic for a given Task and seed when practical. Recreate
ephemeral data, close stale handles, and avoid carrying state between Trials
unless the Runtime explicitly supports and the experiment intentionally uses
persistence.

## Rewarders

A Rewarder is a training signal, not a final evaluator:

```python
from plural import rewarder

@rewarder(weight=0.25)
def progress(previous_state, current_state, action, result) -> float:
    return float(current_state["status"] != previous_state["status"])
```

Rewarders conceptually describe state-transition credit and run only in train
mode. Package Jobs can execute command Rewarders during final
scoring; decorated Python Rewarders are recorded by implementation digest but
are not executable from a package Job. A compatible in-process integration
must invoke transition Rewarders itself. Do not present this declaration as a
training algorithm.

Use Verifiers for held-out success, Rewarders for learning signals, and keep
their metrics separate.

## Resources

`Resource` describes data, an application, or a file:

```python
from plural import Resource

policy = Resource(
    kind="data",
    name="support-policy",
    path="policy.md",
    content_type="text/markdown",
)
```

Fields are `kind`, `name`, optional `path`, `uri`, `digest`, `content_type`, and
`config`. Environment resources are shared by its Tasks; Task resources are
case-specific. A descriptor does not automatically mount a host path, fetch a
URI, or grant Agent access. Package needed files in the Environment or Harness
source and expose only the intended content through actions.

This authored `Resource` is different from an output artifact. An artifact is
a file captured after an execution and addressed by its digest.

## Limits and guardrails

`ExecutionLimits` defaults to `max_turns=8` and `max_seconds=120`; cost is
unlimited unless `max_cost_usd` is set. Guardrails are plain-language rules.
Neither substitutes for Runtime enforcement.

Keep limits low enough to catch loops, then raise them from observed evidence.
Use Runtime network, compute, filesystem, and process controls for security.
