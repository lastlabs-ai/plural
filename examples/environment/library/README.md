# Library environment

`LibraryEnv` is a small closed-corpus research task. A policy can `search`,
`read`, or use the nested `research` tool before submitting `answer`.

## Run

From the repository root:

```bash
uv run python examples/environment/library/run.py
```

The offline script compares a researcher with an immediate wrong guess, prints
their returns, adds late credit, and saves a Trace Dataset under
`.plural/examples`.

## Tool-only environment

`LibraryEnv` defines tools but does not override `apply_action`. It inherits the
base dispatcher, while the framework-owned final `step()` records decisions,
advances turns, and checks termination.

```python
from plural import ScriptedPolicy
from plural.tracing import ParsedAction

rollout = env.run_episode(
    task,
    ScriptedPolicy(
        [
            ParsedAction(name="search", arguments={"query": "voting"}),
            ParsedAction(name="read", arguments={"doc_id": "d1"}),
            ParsedAction(name="answer", arguments={"text": "the river path"}),
        ]
    ),
)
```

Use `rollout.trace.returns(gamma=0.9)` to assign the final answer reward back to
research actions, then save traces as training data. To compare policies across
both default tasks, run the [benchmarking examples](../../benchmarking/README.md).

## Files

- [`env.py`](env.py): environment, corpus, tools, and scoring
- [`run.py`](run.py): offline `run_episode` and training handoff
- [`walkthrough.ipynb`](walkthrough.ipynb): brief environment, trace, and benchmark tutorial
