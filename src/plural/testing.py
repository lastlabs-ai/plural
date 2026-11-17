"""Test helpers for Environment authors.

``assert_restorable`` checks the App restore contract that forks and
checkpoints rely on::

    from plural.testing import assert_restorable


    def test_shop_restores():
        assert_restorable(shop, task, [{"name": "set_price", "price": 4}, ...])
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

from plural.environments.env import Environment, normalize_initial_state


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _action(item: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(item, Mapping):
        payload = dict(item)
        name = payload.pop("name", None) or payload.pop("action", None)
        arguments = payload.pop("arguments", None)
        return str(name), dict(arguments) if isinstance(arguments, Mapping) else payload
    if isinstance(item, Sequence) and not isinstance(item, str) and len(item) == 2:
        return str(item[0]), dict(item[1] or {})
    return str(item), {}


def assert_restorable(
    environment: Environment,
    task: Any = None,
    actions: Sequence[Any] = (),
    *,
    seed: int | None = None,
) -> None:
    """Restore at every step and check that replaying gives the same episode.

    Runs ``actions`` once from a reset. Then, for each step *k*, starts a new
    App host from the State and random number generators recorded after step
    *k* (as a fork does, without a reset), replays the remaining actions, and
    checks that every observation and every App's final State are identical,
    byte for byte, to the original run's.

    Args:
        environment: The Environment under test.
        task: A :class:`~plural.Task`, or ``None`` for an empty initial state.
            Its seed is the one a Job's first attempt uses.
        actions: Each action as ``{"name": ..., **arguments}``, a
            ``(name, arguments)`` pair, or a bare name.
        seed: The episode seed, overriding the Task's.

    Raises:
        AssertionError: When an App can't be restored, or a replay differs.
    """
    from plural.apps.host import AppHost
    from plural.execution.apps import trial_seed
    from plural.verifiers import StepTask

    info = getattr(task, "info", None)
    raw_state = getattr(task, "initial_state", None) or {}
    if seed is None and task is not None and hasattr(task, "content_hash"):
        seed = trial_seed(task.content_hash, 1)
    initial_state = normalize_initial_state(environment.definition(), raw_state)
    steps = [_action(item) for item in actions]
    problem = environment.definition().fork_problem
    if problem:
        raise AssertionError(f"The Environment is not forkable: {problem}")

    scratch = tempfile.TemporaryDirectory(prefix="plural-restorable-")

    def fresh() -> AppHost:
        return AppHost(
            environment, workspace=scratch.name, task=StepTask(info=info), private_state=True
        )

    with scratch:
        _check(fresh, steps, initial_state=initial_state, info=info, seed=seed)


def _check(
    fresh: Any,
    steps: Sequence[tuple[str, dict[str, Any]]],
    *,
    initial_state: Mapping[str, Any],
    info: Any,
    seed: int | None,
) -> None:
    from plural.checkpoints import opening_of, world_at

    original = fresh()
    try:
        original.reset(initial_state=initial_state, info=info, seed=seed)
        observations: list[str] = []
        turns: list[int] = [0]
        for name, arguments in steps:
            observations.append(_canonical(original.agent_view(original.step(name, arguments))))
            turns.append(original.turns)
        final = _canonical({name: original._snapshot(app) for name, app in original.apps.items()})
        lines = json.loads(_canonical(original._states))
    finally:
        original.close()
    opening, rendered = opening_of(lines)
    for k in range(len(steps) + 1):
        states, generators, initial = world_at(lines, k)
        restored = fresh()
        try:
            restored.restore(
                states=states,
                rng=generators,
                initial=initial,
                step=k,
                turns=turns[k],
                observation=opening if k == 0 else None,
                rendered=rendered if k == 0 else "",
                info=info,
                seed=seed,
            )
            for index in range(k, len(steps)):
                name, arguments = steps[index]
                seen = _canonical(restored.agent_view(restored.step(name, arguments)))
                if seen != observations[index]:
                    raise AssertionError(
                        f"Restored at step {k}, step {index + 1} ({name}) observed "
                        f"{seen[:300]}, not {observations[index][:300]}."
                    )
            replayed = _canonical(
                {name: restored._snapshot(app) for name, app in restored.apps.items()}
            )
        finally:
            restored.close()
        if replayed != final:
            raise AssertionError(
                f"Restored at step {k}, the final State differs:\n"
                f"  original {final[:400]}\n  replayed {replayed[:400]}"
            )


__all__ = ["assert_restorable"]
