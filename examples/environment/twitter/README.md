# Twitter environment

`TwitterEnv` is a deterministic in-memory account simulator with two tasks:

- `reply_to_mentions`: reply to every waiting mention.
- `get_n_likes`: publish a non-empty post, then call `wait_for_engagement` to
  receive likes from the account's three seeded followers.

## Run

From the repository root:

```bash
uv run python examples/environment/twitter/run.py
```

The offline example demonstrates the reply goal with a small policy that reads
mention IDs from the `view_notifications` result:

```python
rollout = env.run_episode(task, ReplyPolicy(), model="reply-policy")
```

`wait_for_engagement` advances the simulator once. Each follower deterministically
likes every non-empty post owned by the account and `new_likes` reports only
likes added by that call; empty posts never gain engagement.

## Tool-only environment

`TwitterEnv` defines tools and inherits the base `apply_action` dispatcher.
Framework-owned final `step()` records actions and results, advances the turn,
and terminates when the active goal reaches a score of `1`.

See the [benchmarking examples](../../benchmarking/README.md) to compare models
or arbitrary policy factories over environment tasks.

## Files

- [`env.py`](env.py): simulator, tools, tasks, and scoring
- [`run.py`](run.py): deterministic reply policy and episode trace
- [`walkthrough.ipynb`](walkthrough.ipynb): brief environment, trace, and benchmark tutorial
