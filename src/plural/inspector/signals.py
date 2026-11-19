"""Evidence signals: plugins that point the Inspector at what looks wrong in a Trial.

A signal is a function registered with :func:`signal`. It reads one Trial's
evidence and returns what it noticed, each with the step it is about. The
Inspector reads every registered signal's output before it investigates:

.. code-block:: python

    from plural.inspector.signals import Signal, signal


    @signal("late_quote")
    def late_quote(trial):
        if len(trial.steps) > 8:
            yield Signal("late_quote", None, f"took {len(trial.steps)} steps")

A project adds its own in ``inspector/signals.py``, which the Inspector loads.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plural.inspector.causes import INSPECTOR_DIR
from plural.inspector.evidence import step_info

if TYPE_CHECKING:
    from plural.inspector.evidence import TrialEvidence

SIGNALS_FILE = "signals.py"
"""The file, in a project's ``inspector`` folder, that registers its own signals."""

LARGE_CONTEXT_TOKENS = 16_000
"""A model call reading more input tokens than this raises ``large_context``."""

FINISHED = frozenset({"environment_terminated", "finished", "agent_finished"})


@dataclass(frozen=True)
class Signal:
    """One thing a signal noticed.

    Attributes:
        name: The signal's name.
        step: The step it is about, or ``None`` for the whole Trial.
        detail: What it noticed, in a sentence.
    """

    name: str
    step: int | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        """The signal as JSON.

        Returns:
            Its fields.
        """
        return asdict(self)


SignalFunction = Callable[["TrialEvidence"], Iterable[Signal]]

_SIGNALS: dict[str, SignalFunction] = {}


def signal(name: str) -> Callable[[SignalFunction], SignalFunction]:
    """Register a signal under ``name``.

    Returns:
        A decorator that registers the function and returns it unchanged.

    Raises:
        ValueError: When another signal already has the name.
    """

    def register(function: SignalFunction) -> SignalFunction:
        if name in _SIGNALS and _SIGNALS[name] is not function:
            raise ValueError(f"a signal named {name!r} is already registered")
        _SIGNALS[name] = function
        return function

    return register


def registered() -> tuple[str, ...]:
    """Every signal's name, sorted.

    Returns:
        The names.
    """
    return tuple(sorted(_SIGNALS))


def run_signals(trial: TrialEvidence) -> list[Signal]:
    """Every registered signal's output for one Trial.

    A signal that raises is reported as a ``signal_failed`` signal, so one
    broken plugin never hides the others.

    Returns:
        The signals, by signal name, then step.
    """
    found: list[Signal] = []
    for name in registered():
        try:
            found.extend(_SIGNALS[name](trial))
        except Exception as exc:  # noqa: BLE001 - a plugin's failure is reported, not raised
            found.append(Signal("signal_failed", None, f"signal {name!r} failed: {exc}"))
    return found


def load_project_signals(project_root: Path) -> list[str]:
    """Import a project's ``inspector/signals.py``, which registers its signals.

    Returns:
        The names of the signals it added.
    """
    path = project_root / INSPECTOR_DIR / SIGNALS_FILE
    if not path.is_file():
        return []
    before = set(_SIGNALS)
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
    module_name = f"plural_project_signals_{digest}"
    if module_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return []
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return sorted(set(_SIGNALS) - before)


@signal("unknown_action")
def _unknown_action(trial: TrialEvidence) -> Iterable[Signal]:
    for item in trial.steps:
        info = step_info(item)
        if info.get("unknown_action"):
            yield Signal(
                "unknown_action",
                item.get("step"),
                f"called {item.get('action')!r}, which the Environment doesn't have",
            )


@signal("action_error")
def _action_error(trial: TrialEvidence) -> Iterable[Signal]:
    for item in trial.steps:
        info = step_info(item)
        if info.get("error") and not info.get("unknown_action"):
            yield Signal(
                "action_error", item.get("step"), f"{item.get('action')} failed: {info['error']}"
            )


@signal("repeated_action")
def _repeated_action(trial: TrialEvidence) -> Iterable[Signal]:
    previous: tuple[Any, str] | None = None
    for item in trial.steps:
        call = (item.get("action"), json.dumps(item.get("arguments"), sort_keys=True))
        if call == previous:
            yield Signal(
                "repeated_action",
                item.get("step"),
                f"repeated {item.get('action')} with the same arguments",
            )
        previous = call


@signal("unused_tool")
def _unused_tool(trial: TrialEvidence) -> Iterable[Signal]:
    seen = trial.tools_seen()
    used = set(seen["called"])
    for item in seen["tools"]:
        if item["name"] not in used:
            yield Signal(
                "unused_tool",
                None,
                f"never called {item['name']} ({item['description'] or 'no description'})",
            )


@signal("failed_gate")
def _failed_gate(trial: TrialEvidence) -> Iterable[Signal]:
    feedback = "; ".join(
        str(item.feedback) for item in trial.result.verifier_results if item.feedback
    )
    for name, passed in sorted(trial.result.gates.items()):
        if passed is False:
            yield Signal("failed_gate", None, f"gate {name} failed. Verifier said: {feedback}")


@signal("stop_reason")
def _stop_reason(trial: TrialEvidence) -> Iterable[Signal]:
    reason = trial.result.stop_reason
    if reason and reason not in FINISHED:
        yield Signal("stop_reason", None, f"the episode ended by {reason}, not by finishing")
    if trial.result.status != "succeeded":
        yield Signal(
            "stop_reason",
            None,
            f"the Trial {trial.result.status}: {trial.result.error_message or 'no message'}",
        )


@signal("large_context")
def _large_context(trial: TrialEvidence) -> Iterable[Signal]:
    for call in trial.model_calls():
        tokens = int(call["input_tokens"] or 0)
        if tokens > LARGE_CONTEXT_TOKENS:
            yield Signal("large_context", None, f"turn {call['turn']} read {tokens} input tokens")


__all__ = [
    "LARGE_CONTEXT_TOKENS",
    "SIGNALS_FILE",
    "Signal",
    "SignalFunction",
    "load_project_signals",
    "registered",
    "run_signals",
    "signal",
]
