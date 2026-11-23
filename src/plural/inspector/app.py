"""The Inspector's App: one Job's evidence as read-only tools, forks, and record_finding.

The Inspector's Environment (``plural/inspector/project``) subclasses
:class:`InspectorApp`. Each Task sets the App's State to the Job and the failed
Trial to look at, so the same App serves ``plural job inspect``, ``plural
trial ask``, and inspector-bench. Every tool reads files the Job wrote, and
every number in its answers is computed here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from pydantic import Field, ValidationError

from plural.agents.models import ContextPolicy
from plural.agents.tool_overrides import ToolOverride
from plural.apps.base import App
from plural.apps.definition import SecretReference
from plural.environments.action_registry import action
from plural.environments.types import State, initial
from plural.inspector.causes import load_causes
from plural.inspector.evidence import JobEvidence, TrialEvidence
from plural.inspector.findings import ForkTest, Remedy, finding_status, stronger_model_won
from plural.inspector.signals import load_project_signals, run_signals

PATTERNS_FILE = "patterns.yaml"
"""In a project's ``inspector`` folder: known failure patterns, written by people."""

CREDENTIAL = "INSPECTOR_FORK_KEY"
"""The key forks call models with, minted for one inspection of one Job.

It calls the gateway and nothing else, is revoked when the inspection ends, and
reaches only the App host: never the Inspector's model, and never the user's own key.
"""

ATTEMPTS = {"quick": 0, "standard": 4, "deep": 6}
"""Forks per side for each depth. A quick inspection runs no forks."""

_F = TypeVar("_F", bound=Callable[..., Any])


def _tool(*, read_only: bool = True, timeout_seconds: float = 30) -> Callable[[_F], _F]:
    return cast("Callable[[_F], _F]", action(read_only=read_only, timeout_seconds=timeout_seconds))


def _context_config(value: dict[str, Any] | None) -> dict[str, Any]:
    """The ``harness_config`` of a context policy the Inspector proposed.

    Raises:
        ValueError: Saying what is wrong with the policy.
    """
    if value is None:
        return {}
    try:
        policy = ContextPolicy.model_validate(value)
    except ValidationError as exc:
        raise ValueError(f"context isn't a context policy: {exc}") from exc
    return {"context": policy.model_dump(mode="json")}


class InspectorState(State):
    """What the Inspector is looking at, and what it has found so far."""

    mode: Literal["inspect", "ask"] = initial("inspect", description="Find a cause, or answer.")
    project: str = initial("", description="The inspected project's folder.")
    job_id: str = initial("", description="The inspected Job.")
    trial_id: str = initial("", description="The failed Trial to explain.")
    question: str = initial("", description="For ask: the question.")
    depth: Literal["quick", "standard", "deep"] = initial("standard")
    budget_usd: float = initial(1.0, minimum=0, description="What forks may spend, in USD.")
    gateway_url: str = initial("", description="Where forks call models.")
    api_url: str = initial("", description="The Plural API forks report to.")
    fork_models: list[str] = initial(
        default_factory=list, description="The models a fork may switch to; empty allows any."
    )
    spent_usd: float = 0.0
    tests: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    done: bool = False
    answer: str | None = None


class InspectorApp(App[InspectorState]):
    """A Job's evidence, read-only, plus forks within a budget and record_finding."""

    credentials = (
        SecretReference(
            name=CREDENTIAL,
            required=False,
            scopes=("gateway",),
            description="This inspection's own key, for forks. Without it, forks are off.",
        ),
    )
    restorable = False

    def reset(self, initial_state: Any) -> str:
        """Open the Job, and say what to explain.

        Returns:
            The opening observation.
        """
        super().reset(initial_state)
        self._evidence: JobEvidence | None = None
        load_project_signals(self._root)
        if self.state.mode == "ask":
            return f"Answer this about Trial {self.state.trial_id}: {self.state.question}"
        return f"Trial {self.state.trial_id} of Job {self.state.job_id} failed. Find out why."

    @property
    def _root(self) -> Path:
        return Path(self.state.project)

    @property
    def _job(self) -> JobEvidence:
        if getattr(self, "_evidence", None) is None:
            self._evidence = JobEvidence(self._root, self.state.job_id)
        assert self._evidence is not None
        return self._evidence

    def _trial(self, trial_id: str | None = None) -> TrialEvidence:
        return self._job.trial(trial_id or self.state.trial_id)

    def terminated(self) -> bool:
        """The episode ends with the last Finding recorded, or the question answered.

        Returns:
            Whether it is over.
        """
        return self.state.done or self.state.answer is not None

    # One Trial.

    @_tool()
    def overview(self) -> dict[str, Any]:
        """Start here: the failed Trial's outcome, metrics, gates, cost, and the signals
        that point at what looks wrong, with any known failure patterns of this project.
        """
        trial = self._trial()
        return {
            **trial.overview(),
            "signals": [item.as_dict() for item in run_signals(trial)],
            "context_compactions": trial.compactions,
            "known_patterns": _patterns(self._root),
            "fork_budget_usd": round(self.state.budget_usd - self.state.spent_usd, 4),
            "forks_allowed": ATTEMPTS[self.state.depth] > 0 and bool(os.environ.get(CREDENTIAL)),
            "fork_models": list(self.state.fork_models) or "any",
        }

    @_tool()
    def steps(self, start: int = 1, end: int | None = None) -> list[dict[str, Any]]:
        """Steps start to end (inclusive): each action, its arguments, what the Agent saw
        back, any error, and the reward.
        """
        return self._trial().step_view(start, end)

    @_tool()
    def search(self, text: str) -> list[dict[str, Any]]:
        """Find text in the Trial's steps and in what the model read and wrote."""
        return self._trial().search(text)

    @_tool()
    def context_at(self, step: int) -> dict[str, Any]:
        """The model's context when it chose step's action: each message, its size, and
        the provider's input token count for that call.
        """
        return self._trial().context_at(step)

    @_tool()
    def model_calls(self) -> list[dict[str, Any]]:
        """Each model call: tokens, cost, finish reason, and the tools it called."""
        return self._trial().model_calls()

    @_tool()
    def state_at(self, step: int, app: str | None = None) -> dict[str, Any]:
        """The Apps' State after a step (0 is before the first action). The Agent never
        saw State; it shows what was true in the world.
        """
        return self._trial().state_at(step, app)

    @_tool()
    def state_diff(self, from_step: int, to_step: int) -> dict[str, Any]:
        """What changed in the Apps' State between two steps."""
        return self._trial().state_diff(from_step, to_step)

    @_tool()
    def metrics(self) -> dict[str, Any]:
        """The Trial's final metric values, and running metrics after each step."""
        return self._trial().metric_series()

    @_tool()
    def rewards(self) -> dict[str, Any]:
        """The reward on each step, and the total."""
        return self._trial().rewards()

    @_tool()
    def verifier_output(self) -> list[dict[str, Any]]:
        """Each Verifier's decision: score, metrics, feedback, and evidence."""
        return self._trial().verifier_output()

    @_tool()
    def verifier_code(self, name: str) -> dict[str, Any]:
        """A Verifier's code in the project, and whether it is the code the Trial ran."""
        return self._trial().verifier_code(name)

    @_tool(timeout_seconds=600)
    def reference_check(self) -> dict[str, Any]:
        """Play the Task's reference solution, which never sees the answer key, through the
        same Environment and Verifiers, with no model. If it passes, the grading works and
        the cause is the Agent's. If it fails too, the cause is grader or task: compare the
        request with the answer key to tell which.
        """
        return self._trial().reference_check()

    @_tool()
    def integrity(self) -> dict[str, Any]:
        """The Trial's trust tier and integrity checks."""
        return self._trial().integrity()

    # The system under test.

    @_tool()
    def agent_config(self) -> dict[str, Any]:
        """The Agent as it ran: model, instructions, Harness, and tool overrides."""
        return self._trial().agent_config()

    @_tool()
    def tools_seen(self) -> dict[str, Any]:
        """The tools as the model saw them, after the Agent's overrides, and which it used."""
        return self._trial().tools_seen()

    @_tool()
    def environment_actions(self) -> list[dict[str, Any]]:
        """The Environment's actions as it declares them."""
        return self._trial().environment_actions()

    @_tool()
    def task(self) -> dict[str, Any]:
        """The Task: its instructions, initial State, files, and its answer key (expected),
        which the Agent never saw.
        """
        return self._trial().task_view()

    @_tool()
    def task_file(self, path: str) -> str:
        """One of the Task's files."""
        return self._trial().task_file(path)

    # Across Trials.

    @_tool()
    def query_trials(
        self,
        task: str | None = None,
        passed: bool | None = None,
        action: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """The Job's other dev Trials matching every filter given: Task, outcome, an action
        they took, or Benchmark category.
        """
        return self._job.query(task=task, passed=passed, action=action, category=category)

    @_tool()
    def compare_trials(self, first: str, second: str) -> dict[str, Any]:
        """Two Trials' actions side by side, and the first step where they differ."""
        return self._job.compare(first, second)

    @_tool()
    def correlate(self, feature: str) -> dict[str, Any]:
        """The Job's pass rate grouped by a feature: category, model, task,
        context_tokens, steps, or tool:NAME.
        """
        return self._job.correlate(feature)

    @_tool()
    def causes(self) -> list[dict[str, Any]]:
        """The cause dimensions a Finding may name. agent: true means a change to the
        Agent can fix it, so a fork can confirm it.
        """
        return [item.model_dump(mode="json") for item in load_causes(self._root)]

    # Experiments.

    @_tool(read_only=False, timeout_seconds=1800)
    def fork(
        self,
        step: int,
        instructions: str | None = None,
        tool_descriptions: dict[str, str] | None = None,
        hide_tools: list[str] | None = None,
        model: str | None = None,
        context: dict[str, Any] | None = None,
        change: str | None = None,
        payload: dict[str, Any] | None = None,
        gates: list[str] | None = None,
    ) -> dict[str, Any]:
        """Test a cause: continue the failed Trial after step with the Agent changed, beside
        controls that rerun it unchanged. Change the Agent with instructions (its whole new
        text), tool_descriptions (tool name to new description), hide_tools, model, or
        context (its whole new context policy: strategy, max_tokens, keep_last_turns,
        summary_instructions); or change what it sees with a diagnostic change and
        payload. Step 0 starts over.
        gates names the failed gates this cause explains: each side is judged on those
        alone, so a fix for one of two failures shows its effect. Returns how often each
        side passed and the verdict. Costs money.
        """
        attempts = ATTEMPTS[self.state.depth]
        if attempts == 0:
            raise ValueError("A quick inspection runs no forks. Record what you inferred.")
        if not os.environ.get(CREDENTIAL):
            raise ValueError(
                "Forks are off for this inspection: it has no key of its own to run them "
                "with. Record what you inferred."
            )
        remedy = Remedy(
            instructions=instructions,
            tool_overrides={
                **{
                    name: ToolOverride(description=text)
                    for name, text in (tool_descriptions or {}).items()
                },
                **{name: ToolOverride(hidden=True) for name in hide_tools or ()},
            },
            model=model,
            harness_config=_context_config(context),
        )
        if remedy.empty and change is None:
            raise ValueError("Change the Agent or name a diagnostic change to test.")
        self._general(remedy)
        if model is not None and self.state.fork_models and model not in self.state.fork_models:
            raise ValueError(
                f"Forks may run {', '.join(self.state.fork_models)}, not {model}. Pick one of "
                "those."
            )
        trial = self._trial()
        failed = set(trial.row()["failed_gates"])
        unknown = sorted(set(gates or ()) - failed)
        if unknown:
            raise ValueError(
                f"{', '.join(unknown)} didn't fail. The failed gates: {sorted(failed) or 'none'}."
            )
        estimate = 2 * attempts * float(trial.overview()["cost_usd"] or 0.0)
        left = self.state.budget_usd - self.state.spent_usd
        if estimate > left:
            raise ValueError(
                f"This fork would cost about ${estimate:.4f}, and ${left:.4f} of the budget "
                "is left. Record what you have."
            )
        from plural.inspector.experiments import run_fork

        test = run_fork(
            self._root,
            trial_id=self.state.trial_id,
            step=step,
            remedy=None if remedy.empty else remedy,
            change=change,
            payload=payload,
            attempts=attempts,
            test_id=f"X{len(self.state.tests) + 1}",
            environ=_fork_environ(self.state.gateway_url, self.state.api_url),
            gates=sorted(set(gates or ())),
        )
        self.state.tests.append(test.model_dump(mode="json"))
        self.state.spent_usd += test.cost_usd
        candidates = test.outcomes.get("candidate", {})
        newly = sorted(
            name
            for name in candidates
            if name != "passed" and name not in failed | set(gates or ())
        )
        return {
            **test.model_dump(mode="json", exclude={"remedy", "payload"}),
            "beat_controls": test.beat_controls,
            "newly_failed": {name: candidates[name] for name in newly},
            "next": (
                f"The candidates failed {', '.join(newly)}, which the original Trial didn't. "
                "Find out why before recording: the change may need refining, or the answer "
                "key may be wrong."
                if newly
                else ""
            ),
            "fork_budget_left_usd": round(self.state.budget_usd - self.state.spent_usd, 4),
        }

    # Output.

    @_tool(read_only=False)
    def record_finding(
        self,
        cause: str,
        summary: str,
        evidence: list[str],
        critical_step: int | None = None,
        tests: list[str] | None = None,
        instructions: str | None = None,
        tool_descriptions: dict[str, str] | None = None,
        model: str | None = None,
        context: dict[str, Any] | None = None,
        note: str = "",
        gates: list[str] | None = None,
        more: bool = False,
    ) -> str:
        """Record one cause of the failure. cause is one dimension from causes(); gates
        lists the failed gates (from overview) this cause explains; summary says the
        cause in a sentence or two; evidence lists what shows it, each naming its step or
        record; critical_step is where it went wrong (None when the Agent's work was right
        and the grading was wrong); tests names the forks (X1, ...) that tested it. For a
        cause the Agent can fix, give the remedy you would ship: instructions,
        tool_descriptions, model, or context, and a note. A remedy ships to every Task, so
        one that names this Task's own accounts, customers, or items is refused: describe
        the kind of thing instead. A model Finding is refused unless tests
        names a fork that changed only the model and beat its controls. Set more to true
        when another cause
        explains other failed gates and you will record it next; otherwise this ends the
        episode, and every failed gate must be explained by then.
        """
        if self.state.mode != "inspect":
            raise ValueError("This is a question; answer it with answer().")
        causes = {item.name: item for item in load_causes(self._root)}
        if cause not in causes:
            raise ValueError(f"cause must be one of {', '.join(sorted(causes))}.")
        if any(item["cause"] == cause for item in self.state.findings):
            raise ValueError(f"A {cause} Finding is already recorded for this Trial.")
        if not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
            raise ValueError("Give at least one piece of evidence.")
        known = {item["test_id"]: item for item in self.state.tests}
        missing = sorted(set(tests or ()) - set(known))
        if missing:
            raise ValueError(f"No fork {', '.join(missing)} was run. Ran: {sorted(known)}.")
        forks = [ForkTest.model_validate(known[name]) for name in tests or ()]
        failed = set(self._trial().row()["failed_gates"]) | self._revealed()
        unknown = sorted(set(gates or ()) - failed)
        if unknown:
            raise ValueError(
                f"{', '.join(unknown)} didn't fail. The failed gates: {sorted(failed) or 'none'}."
            )
        explained = {gate for item in self.state.findings for gate in item["gates"]}
        left = sorted(failed - explained - set(gates or ()))
        if left and not more:
            raise ValueError(
                f"No Finding explains {', '.join(left)} yet. Add it to gates if this cause "
                "explains it, or set more to true and record its own cause next. A gate a "
                "fork's candidates failed after the fix worked counts: something else stops "
                "this Trial from passing."
            )
        if cause == "model" and not any(
            stronger_model_won(item, self._trial().agent.model, gates or ()) for item in forks
        ):
            raise ValueError(
                "A model Finding needs a fork in which a stronger model beat the controls: "
                "fork with model set to another model and nothing else changed, on the gates "
                "this cause explains, and list it in tests. Without one, the cause isn't "
                "shown to be the model: keep looking at the instructions, tools, and context."
            )
        remedy = Remedy(
            instructions=instructions,
            tool_overrides={
                name: ToolOverride(description=text)
                for name, text in (tool_descriptions or {}).items()
            },
            model=model,
            harness_config=_context_config(context),
            note=note,
        )
        self._general(remedy)
        trial = self._trial()
        status = finding_status(forks, agent_cause=causes[cause].agent, gates=gates or ())
        self.state.findings.append(
            {
                "trial_id": trial.trial_id,
                "task": trial.task.task_id,
                "agent": trial.agent.name,
                "critical_step": critical_step,
                "cause": cause,
                "gates": sorted(set(gates or ())),
                "summary": summary.strip(),
                "evidence": [item.strip() for item in evidence],
                "forks": [item.model_dump(mode="json") for item in forks],
                "status": status,
                "remedy": None
                if remedy.empty and not remedy.note
                else remedy.model_dump(mode="json"),
            }
        )
        self.state.done = not more
        return f"Recorded: {cause}, {status}." + (" Record the next cause." if more else "")

    def _general(self, remedy: Remedy) -> None:
        """Refuse a remedy that names one Task's own accounts, customers, or items.

        A remedy changes the Agent for every Task, so naming what only this Task holds
        would fit the fix to this Trial rather than to the Agent's work.
        """
        trial = self._trial()
        named = remedy.names(self._job.task_entities(trial))
        if named:
            raise ValueError(
                f"The remedy names {', '.join(repr(item) for item in named[:5])}, which "
                f"belong{'s' if len(named) == 1 else ''} to Task {trial.task.task_id} alone. "
                "A remedy changes the Agent for every Task, so describe the kind of thing "
                "(a customer, a supplier, an item) and how to recognize it, never one Task's "
                "own."
            )

    def _revealed(self) -> set[str]:
        """Gates that forks which beat their controls failed, beyond the ones they fixed."""
        gates: set[str] = set()
        for item in self.state.tests:
            test = ForkTest.model_validate(item)
            if test.beat_controls:
                fixed = set(test.gates)
                gates |= {
                    name
                    for name in test.outcomes.get("candidate", {})
                    if name != "passed" and name not in fixed
                }
        return gates

    @_tool(read_only=False)
    def answer(self, text: str) -> str:
        """Answer the question, which ends the episode. Name the steps and records your
        answer rests on.
        """
        if self.state.mode != "ask":
            raise ValueError("This inspection records a Finding with record_finding().")
        if not text.strip():
            raise ValueError("The answer is empty.")
        self.state.answer = text.strip()
        return "Answered."


def _patterns(root: Path) -> list[dict[str, Any]]:
    import yaml

    path = root / "inspector" / PATTERNS_FILE
    if not path.is_file():
        return []
    payload = yaml.safe_load(path.read_text("utf-8")) or []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _fork_environ(gateway_url: str, api_url: str) -> dict[str, str]:
    """What a fork Job's process needs: the credential this App was given, and where to call.

    Returns:
        The environment.
    """
    environ = {
        name: value
        for name in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
        if (value := os.environ.get(name)) is not None
    }
    if os.environ.get(CREDENTIAL):
        environ["PLURAL_API_KEY"] = os.environ[CREDENTIAL]
    if gateway_url:
        environ["PLURAL_GATEWAY_URL"] = gateway_url
    if api_url:
        environ["PLURAL_API_URL"] = api_url
    return environ


def render(value: Any) -> str:
    """An evidence tool's answer as the model reads it.

    Returns:
        Compact JSON.
    """
    return json.dumps(value, sort_keys=True, default=str)


__all__ = ["ATTEMPTS", "PATTERNS_FILE", "InspectorApp", "InspectorState", "render"]
