"""What the Inspector's evidence tools read: one local Job's Trials.

Every number here is computed in code from the records the App host and the
Harness wrote, so the Inspector reasons about facts, not its own arithmetic.
Held-out Trials are left out entirely: diagnosis never looks at them.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterator, Mapping, Sequence
from functools import cached_property
from pathlib import Path
from typing import Any

from plural.agents import AgentBinding
from plural.apps.host import STATES_FILE, STEPS_FILE
from plural.execution.apps import environment_payload
from plural.harness.episode import EPISODE_FILE
from plural.jobs import BenchmarkJobSource, JobResult, JobSpec, TrialResult
from plural.project.layout import Project, ProjectError
from plural.project.resources import Workspace
from plural.project.runs import _load_local
from plural.tasks import TaskDefinition

TEXT_LIMIT = 1500
"""The longest text an evidence tool returns in one field; longer text is cut."""

CHARS_PER_TOKEN = 4
"""The divisor of an estimated token count, used only where no count was reported."""

EXPECTED_NOTE = "The Agent never saw this. It is the Task's answer key, for the Verifier."


def step_info(step: Mapping[str, Any]) -> dict[str, Any]:
    """A recorded step's ``info``, or an empty dict.

    Returns:
        The info.
    """
    info = step.get("info")
    return info if isinstance(info, dict) else {}


def estimate_tokens(text: str) -> int:
    """A rough token count for text no provider counted.

    Returns:
        The characters divided by :data:`CHARS_PER_TOKEN`, rounded up.

    Examples:
        >>> estimate_tokens("twelve chars")
        3
    """
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def clip(text: str, limit: int = TEXT_LIMIT) -> str:
    """Text cut to ``limit`` characters, saying how much was left out.

    Returns:
        The text, or its start and a note of the rest.

    Examples:
        >>> clip("abcdef", 3)
        'abc… (3 more characters)'
    """
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… ({len(text) - limit} more characters)"


def trial_passed(result: TrialResult) -> bool:
    """Whether a Trial passed: its gates, or with none, a score of 1.

    Returns:
        ``True`` when it passed.
    """
    if result.passed is not None:
        return bool(result.passed)
    return result.score is not None and result.score >= 1.0


class JobEvidence:
    """One local Job's dev Trials, as the evidence tools read them."""

    def __init__(self, project_root: Path, job_id: str) -> None:
        """Open a local Job.

        Raises:
            ProjectError: When the folder holds no such Job, or it hasn't finished.
        """
        self.root = project_root.resolve()
        self.workspace = Workspace(Project.at(self.root))
        self.job_id = job_id
        self.directory = self.workspace.project.jobs_dir / job_id
        self.spec: JobSpec
        self.spec, _record = _load_local(self.workspace, job_id)
        result_path = self.directory / "result.json"
        if not result_path.is_file():
            raise ProjectError(f"Job {job_id} hasn't finished, so it has no evidence yet.")
        self.result = JobResult.model_validate_json(result_path.read_text("utf-8"))
        source = self.spec.source
        self.benchmark = source.benchmark if isinstance(source, BenchmarkJobSource) else None
        self.heldout_tasks = set(self.benchmark.heldout) if self.benchmark is not None else set()
        self.categories = {
            task: category.id
            for category in (self.benchmark.categories if self.benchmark is not None else ())
            for task in category.tasks
        }

    @cached_property
    def trials(self) -> dict[str, TrialEvidence]:
        """Every finished dev Trial, by id. Held-out Trials are never included."""
        tasks = {item.content_hash: item for item in self.spec.tasks}
        agents = {item.content_hash: item for item in self.spec.agents}
        by_agent = {item.agent.content_hash: item for item in self.spec.agents}
        found: dict[str, TrialEvidence] = {}
        for result in self.result.trials:
            task = tasks.get(result.receipt.task_digest)
            if task is None or task.task_id in self.heldout_tasks:
                continue
            agent = agents.get(result.receipt.agent_digest) or by_agent.get(
                result.receipt.agent_digest
            )
            if agent is None and len(self.spec.agents) == 1:
                agent = self.spec.agents[0]
            if agent is None:
                continue
            trial_id = result.receipt.trial_id
            found[trial_id] = TrialEvidence(
                job=self,
                trial_id=trial_id,
                result=result,
                task=task,
                agent=agent,
                directory=self.directory / "trials" / trial_id,
            )
        return found

    @property
    def heldout_count(self) -> int:
        """How many of the Job's Trials ran held-out Tasks, and so are left out."""
        tasks = {item.content_hash: item.task_id for item in self.spec.tasks}
        return sum(
            1
            for item in self.result.trials
            if tasks.get(item.receipt.task_digest) in self.heldout_tasks
        )

    def trial(self, trial_id: str) -> TrialEvidence:
        """One dev Trial.

        Returns:
            The Trial's evidence.

        Raises:
            ProjectError: When the Job has no such dev Trial.
        """
        found = self.trials.get(trial_id)
        if found is None:
            raise ProjectError(
                f"Job {self.job_id} has no dev Trial {trial_id}. Held-out Trials are never "
                "inspected."
            )
        return found

    def failed(self) -> list[TrialEvidence]:
        """The dev Trials that didn't pass, in the Job's order.

        Returns:
            The failed Trials.
        """
        return [item for item in self.trials.values() if not item.passed]

    def query(
        self,
        *,
        task: str | None = None,
        passed: bool | None = None,
        action: str | None = None,
        category: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Trials matching every filter given, with their outcome at a glance.

        Returns:
            ``matched``, the count, and ``trials``, at most ``limit`` of them.
        """
        rows = []
        for item in self.trials.values():
            if task is not None and item.task.task_id != task:
                continue
            if passed is not None and item.passed is not passed:
                continue
            if action is not None and action not in item.actions_used:
                continue
            if category is not None and item.category != category:
                continue
            rows.append(item.row())
        return {"matched": len(rows), "trials": rows[: max(1, limit)]}

    def compare(self, first: str, second: str) -> dict[str, Any]:
        """Two Trials' actions side by side, and the first step where they differ.

        Returns:
            Each Trial's outcome and actions, and ``first_difference``: the
            first step whose action or arguments differ, or ``None``.
        """
        a, b = self.trial(first), self.trial(second)
        left, right = a.action_list(), b.action_list()
        difference = None
        for index in range(max(len(left), len(right))):
            one = left[index] if index < len(left) else None
            two = right[index] if index < len(right) else None
            if one is None or two is None or _call(one) != _call(two):
                difference = index + 1
                break
        metrics = sorted(set(a.result.metrics) | set(b.result.metrics))
        return {
            "first": a.row(),
            "second": b.row(),
            "first_difference": difference,
            "metric_differences": {
                name: {"first": a.result.metrics.get(name), "second": b.result.metrics.get(name)}
                for name in metrics
                if a.result.metrics.get(name) != b.result.metrics.get(name)
            },
            "first_actions": left,
            "second_actions": right,
        }

    def correlate(self, feature: str) -> dict[str, Any]:
        """The pass rate of the dev Trials, grouped by one feature.

        ``feature`` is ``category``, ``model``, ``task``, ``context_tokens`` or
        ``steps`` (split at the median), or ``tool:NAME`` (used it or not).

        Returns:
            Each group's Trials, passes, and pass rate, with the Trial ids.

        Raises:
            ValueError: When the feature isn't one of those.
        """
        groups: dict[str, list[TrialEvidence]] = {}
        trials = list(self.trials.values())
        if feature in {"context_tokens", "steps"}:
            values = [item.features()[feature] for item in trials]
            median = statistics.median(values) if values else 0
            for item, value in zip(trials, values, strict=True):
                key = f"<= {median:g}" if value <= median else f"> {median:g}"
                groups.setdefault(key, []).append(item)
        elif feature.startswith("tool:"):
            name = feature.removeprefix("tool:")
            for item in trials:
                key = f"used {name}" if name in item.actions_used else f"never used {name}"
                groups.setdefault(key, []).append(item)
        elif feature in {"category", "model", "task"}:
            for item in trials:
                groups.setdefault(str(item.features()[feature]), []).append(item)
        else:
            raise ValueError(
                f"Unknown feature {feature!r}. Use category, model, task, context_tokens, "
                "steps, or tool:NAME."
            )
        return {
            "feature": feature,
            "groups": {
                key: {
                    "trials": len(members),
                    "passed": sum(1 for item in members if item.passed),
                    "pass_rate": sum(1 for item in members if item.passed) / len(members),
                    "trial_ids": [item.trial_id for item in members],
                }
                for key, members in sorted(groups.items())
            },
        }


class TrialEvidence:
    """One finished Trial's records, read on demand."""

    def __init__(
        self,
        *,
        job: JobEvidence,
        trial_id: str,
        result: TrialResult,
        task: TaskDefinition,
        agent: AgentBinding,
        directory: Path,
    ) -> None:
        """Wrap a Trial's result and the folder its executions were written to."""
        self.job = job
        self.trial_id = trial_id
        self.result = result
        self.task = task
        self.agent = agent
        self.directory = directory

    @property
    def passed(self) -> bool:
        """Whether the Trial passed."""
        return self.result.status == "succeeded" and trial_passed(self.result)

    @property
    def category(self) -> str | None:
        """The Benchmark category of the Trial's Task, if it has one."""
        return self.job.categories.get(self.task.task_id)

    @cached_property
    def artifacts(self) -> Path:
        """The artifacts of the execution the Trial's result came from."""
        selected = self.directory / "selected.json"
        executions = self.directory / "executions"
        if selected.is_file():
            chosen = json.loads(selected.read_text("utf-8")).get("execution_id")
            if chosen is not None and (executions / str(chosen)).is_dir():
                return executions / str(chosen) / "artifacts"
        numbered = sorted(
            (item for item in executions.glob("*") if item.name.isdigit()),
            key=lambda item: int(item.name),
        )
        return (numbered[-1] if numbered else executions / "0") / "artifacts"

    @cached_property
    def steps(self) -> list[dict[str, Any]]:
        """The App host's step records, in order."""
        return [
            item for item in _jsonl(self.artifacts / STEPS_FILE) if item.get("kind") == "action"
        ]

    @cached_property
    def calls(self) -> list[dict[str, Any]]:
        """The model calls the Harness recorded, in order."""
        return [
            item
            for item in _jsonl(self.artifacts / EPISODE_FILE)
            if item.get("kind") == "model.call"
        ]

    @cached_property
    def model_turns(self) -> dict[int, int]:
        """The model call that chose each of the Agent's steps, by its turn.

        A step record's own ``turn`` counts actions; the Harness's episode
        records the model turn of each action, in the same order.
        """
        events = [
            item
            for item in _jsonl(self.artifacts / EPISODE_FILE)
            if item.get("kind") == "environment.step"
        ]
        agent = [item for item in self.steps if item.get("source") == "agent"]
        return {
            int(step.get("step") or 0): int(event["turn"])
            for step, event in zip(agent, events, strict=False)
            if event.get("turn") is not None
        }

    @cached_property
    def states(self) -> list[dict[str, Any]]:
        """The App State after each step, as the App host recorded it."""
        return list(_jsonl(self.artifacts / STATES_FILE))

    @property
    def actions_used(self) -> set[str]:
        """The names of the actions the Agent took."""
        return {str(item.get("action")) for item in self.steps if item.get("source") == "agent"}

    def action_list(self) -> list[dict[str, Any]]:
        """The Agent's actions, in order: step, action, and arguments.

        Returns:
            One entry per step the Agent took.
        """
        return [
            {
                "step": item.get("step"),
                "action": item.get("action"),
                "arguments": item.get("arguments"),
            }
            for item in self.steps
            if item.get("source") == "agent"
        ]

    def features(self) -> dict[str, Any]:
        """What :meth:`JobEvidence.correlate` groups by.

        Returns:
            The Trial's category, model, Task, largest context, and step count.
        """
        return {
            "category": self.category or "none",
            "model": self.agent.model,
            "task": self.task.task_id,
            "context_tokens": max(
                (int(_usage(item).get("input_tokens") or 0) for item in self.calls), default=0
            ),
            "steps": len(self.steps),
        }

    def row(self) -> dict[str, Any]:
        """The Trial at a glance, for lists.

        Returns:
            Id, Task, category, outcome, failed gates, and step count.
        """
        return {
            "trial_id": self.trial_id,
            "task": self.task.task_id,
            "category": self.category,
            "attempt": self.result.receipt.attempt,
            "passed": self.passed,
            "score": self.result.score,
            "failed_gates": sorted(name for name, ok in self.result.gates.items() if ok is False),
            "steps": len(self.steps),
            "stop_reason": self.result.stop_reason,
        }

    def overview(self) -> dict[str, Any]:
        """The Trial's outcome, cost, and size.

        Returns:
            The outcome, metrics, gates, stop reason, step and model-call
            counts, tokens, cost, and the last action.
        """
        usage = [_usage(item) for item in self.calls]
        last = self.action_list()[-1] if self.steps else None
        return {
            **self.row(),
            "job_id": self.job.job_id,
            "agent": self.agent.name,
            "model": self.agent.model,
            "status": self.result.status,
            "error": self.result.error_message,
            "metrics": dict(self.result.metrics),
            "gates": dict(self.result.gates),
            "turns": self.result.turns,
            "model_calls": len(self.calls),
            "input_tokens": sum(int(item.get("input_tokens") or 0) for item in usage),
            "output_tokens": sum(int(item.get("output_tokens") or 0) for item in usage),
            "cost_usd": round(sum(float(item.get("cost_usd") or 0.0) for item in usage), 6),
            "last_action": last,
        }

    def step_view(self, start: int = 1, end: int | None = None) -> list[dict[str, Any]]:
        """Steps ``start`` to ``end``, inclusive, as the Agent and the host saw them.

        Returns:
            Each step's action, arguments, observation, error, and reward.
        """
        rows = []
        for item in self.steps:
            step = int(item.get("step") or 0)
            if step < start or (end is not None and step > end):
                continue
            info = step_info(item)
            rows.append(
                {
                    "step": step,
                    "turn": item.get("turn"),
                    "source": item.get("source"),
                    "app": item.get("app"),
                    "action": item.get("action"),
                    "arguments": item.get("arguments"),
                    "observation": clip(str(item.get("rendered") or "")),
                    "error": info.get("error"),
                    "unknown_action": bool(info.get("unknown_action")),
                    "reward": item.get("reward"),
                    "terminated": item.get("terminated"),
                }
            )
        return rows

    def search(self, text: str, limit: int = 20) -> list[dict[str, Any]]:
        """Where ``text`` appears: in steps, and in what the model wrote or read.

        Returns:
            Each match: where it is, and the text around it.
        """
        needle = text.lower()
        found: list[dict[str, Any]] = []

        def add(where: str, haystack: str, **at: Any) -> None:
            index = haystack.lower().find(needle)
            if index >= 0 and len(found) < limit:
                found.append(
                    {
                        "where": where,
                        **at,
                        "text": haystack[max(0, index - 120) : index + len(text) + 120],
                    }
                )

        for item in self.steps:
            add(
                "step",
                json.dumps(item.get("arguments"), sort_keys=True),
                step=item.get("step"),
                field="arguments",
            )
            add("step", str(item.get("rendered") or ""), step=item.get("step"), field="observation")
        for call in self.calls:
            add("model output", str(call.get("text") or ""), turn=call.get("turn"))
            for message in call.get("messages") or ():
                add(
                    f"model input ({message.get('role')})",
                    _content(message),
                    turn=call.get("turn"),
                )
        return found

    def model_calls(self) -> list[dict[str, Any]]:
        """Each model call: tokens, cost, and what it asked for.

        Returns:
            One entry per call, in order.
        """
        rows = []
        for call in self.calls:
            usage = _usage(call)
            rows.append(
                {
                    "turn": call.get("turn"),
                    "model": call.get("model"),
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "reasoning_tokens": usage.get("reasoning_tokens"),
                    "cost_usd": usage.get("cost_usd"),
                    "finish_reason": call.get("finish_reason"),
                    "tool_calls": [_tool_name(item) for item in call.get("tool_calls") or ()],
                    "text": clip(str(call.get("text") or ""), 600),
                    "error": call.get("error"),
                }
            )
        return rows

    def context_at(self, step: int) -> dict[str, Any]:
        """The context the model read when it chose step ``step``'s action.

        Returns:
            The turn, the provider's input token count for that call, and each
            message with its role, size, and an estimated token count.

        Raises:
            ValueError: When no model call chose that step.
        """
        turn = self.model_turns.get(step)
        if turn is None and step == 0 and self.calls:
            turn = self.calls[0].get("turn")
        calls = [item for item in self.calls if item.get("turn") is not None]
        chosen = next((item for item in calls if item.get("turn") == turn), None)
        if chosen is None:
            raise ValueError(f"No recorded model call chose step {step}.")
        messages: list[dict[str, Any]] = []
        for call in calls:
            offset = int(call.get("messages_offset") or 0)
            messages = messages[:offset] + list(call.get("messages") or ())
            if call is chosen:
                break
        rows = [
            {
                "index": index,
                "role": message.get("role"),
                "characters": len(_content(message)),
                "estimated_tokens": estimate_tokens(_content(message)),
                "content": clip(_content(message), 800),
                "tool_calls": [_tool_name(item) for item in message.get("tool_calls") or ()],
            }
            for index, message in enumerate(messages)
        ]
        return {
            "step": step,
            "turn": turn,
            "input_tokens": _usage(chosen).get("input_tokens"),
            "estimated_tokens": sum(item["estimated_tokens"] for item in rows),
            "messages": rows,
        }

    def state_at(self, step: int, app: str | None = None) -> dict[str, Any]:
        """Each App's State after ``step``, or before the first action at step 0.

        Returns:
            The State by App name, or one App's State.
        """
        current: dict[str, Any] = {}
        for item in self.states:
            if int(item.get("step") or 0) > step:
                break
            state = item.get("state")
            if isinstance(state, dict):
                current.update(state)
        if app is not None:
            return {app: current.get(app)}
        return current

    def state_diff(self, before: int, after: int) -> dict[str, Any]:
        """What changed in App State between two steps.

        Returns:
            Each changed value, by its dotted path, before and after.
        """
        one = _flatten(self.state_at(before))
        two = _flatten(self.state_at(after))
        return {
            "from_step": before,
            "to_step": after,
            "changed": {
                path: {"before": one.get(path), "after": two.get(path)}
                for path in sorted(set(one) | set(two))
                if one.get(path) != two.get(path)
                # An empty object that gained keys shows as its new keys, not as itself.
                and not (
                    one.get(path) in (None, _EMPTY_KEY) and two.get(path) in (None, _EMPTY_KEY)
                )
            },
        }

    def metric_series(self) -> dict[str, Any]:
        """The final metric values, and any running metric's value after each step.

        Returns:
            ``final`` and ``running``.
        """
        running: dict[str, list[dict[str, Any]]] = {}
        for item in _jsonl(self.artifacts / "metrics.jsonl"):
            for name, value in dict(item.get("values") or {}).items():
                running.setdefault(name, []).append({"step": item.get("step"), "value": value})
        return {"final": dict(self.result.metrics), "running": running}

    def rewards(self) -> dict[str, Any]:
        """The reward on each step, and the episode's total.

        Returns:
            ``steps`` with a reward, and ``total``.
        """
        rows = [
            {"step": item.get("step"), "reward": item.get("reward"), "by": item.get("rewards")}
            for item in self.steps
            if item.get("reward") or item.get("rewards")
        ]
        return {"steps": rows, "total": self.result.step_reward_total}

    def verifier_output(self) -> list[dict[str, Any]]:
        """What each Verifier decided, and why.

        Returns:
            Each Verifier's status, score, metrics, feedback, and evidence.
        """
        return [
            {
                "verifier": item.verifier_name,
                "status": item.status,
                "score": item.score,
                "metrics": dict(item.metrics),
                "feedback": item.feedback,
                "evidence": list(item.evidence),
            }
            for item in self.result.verifier_results
        ]

    def verifier_code(self, name: str) -> dict[str, Any]:
        """A Verifier's files in the project, and whether they are what the Trial ran.

        Returns:
            Each Python file's text, and ``same_as_trial``.

        Raises:
            ValueError: When the Trial's Task has no such Verifier.
        """
        ran = {item.verifier.name: item.verifier for item in self.task.verifiers}
        if name not in ran:
            raise ValueError(f"Task {self.task.task_id} has no Verifier {name!r}.")
        folder = self.job.root / "verifiers" / name
        files = {
            str(path.relative_to(folder)): clip(path.read_text("utf-8"), 6000)
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".yaml", ".yml"}
        }
        same = None
        try:
            same = self.job.workspace.get("verifier", name).content_hash == ran[name].content_hash
        except (ProjectError, AttributeError, ValueError):
            same = None
        return {"verifier": name, "files": files, "same_as_trial": same}

    def reference_check(self) -> dict[str, Any]:
        """Play the Task's reference solution through its Environment and Verifiers.

        The reference never sees the answer key and calls no model. A saved check
        of the Task's current version is reused; otherwise the reference runs now
        and its check is saved, as ``plural task validate`` would.

        Returns:
            Whether the reference passed, the gates it failed, and the Verifiers'
            feedback, or why there is no reference to play.
        """
        from plural.project.checks import load_check, plan_checks, run_checks

        name = self.task.task_id
        workspace = self.job.workspace
        check = load_check(workspace, name)
        probe = next((p for p in check.probes if p.probe == "reference"), None) if check else None
        if probe is None:
            plan = plan_checks(workspace, [name])
            if name not in plan.references:
                return {
                    "reference": None,
                    "note": "This Task has no reference solution. Decide grader or task from "
                    "the request, the answer key, and the Verifier's code.",
                }
            (check,) = run_checks(workspace, plan, probes=("reference",))
            probe = next(p for p in check.probes if p.probe == "reference")
        assert check is not None
        return {
            "reference": "passed" if probe.status == "passed" else "failed",
            "score": probe.score,
            "failed_gates": list(probe.failed_checks),
            "feedback": clip(probe.feedback, 2000),
            "detail": probe.detail,
            "task_changed_since_trial": check.content_hash != self.task.content_hash,
        }

    def integrity(self) -> dict[str, Any]:
        """The Trial's trust tier and any integrity findings.

        Returns:
            The trust tier, App isolation, and integrity checks.
        """
        return {
            "trust": self.result.trust.model_dump(mode="json") if self.result.trust else None,
            "app_isolation": self.result.app_isolation,
            "integrity": [item.model_dump(mode="json") for item in self.result.integrity],
        }

    def agent_config(self) -> dict[str, Any]:
        """The Agent as it ran: model, instructions, Harness, and tool descriptions.

        Returns:
            The Agent's settings that decide its behavior.
        """
        agent = self.agent.agent
        return {
            "name": agent.name,
            "revision": agent.revision,
            "model": agent.model,
            "instructions": agent.instructions,
            "harness": agent.harness.name if agent.harness else "native",
            "harness_config": dict(agent.harness_config),
            "tool_overrides": {
                name: item.model_dump(mode="json", exclude_defaults=True)
                for name, item in getattr(agent, "tool_overrides", {}).items()
            },
            "external": agent.external is not None,
        }

    def environment_actions(self) -> list[dict[str, Any]]:
        """The Environment's actions as it declares them.

        Returns:
            Each action's name, App, description, and parameters.
        """
        return [
            {
                "name": item.get("name"),
                "app": item.get("app"),
                "description": item.get("description"),
                "parameters": item.get("parameters"),
                "mutates_state": item.get("mutates_state"),
            }
            for item in environment_payload(self.task, hosted=True).get("actions") or ()
        ]

    def tools_seen(self) -> dict[str, Any]:
        """The tools as the model saw them: the actions, after the Agent's overrides.

        Returns:
            Each tool's name and description as told to the model, the tool
            names the first model call offered, and the ones the Agent called.
        """
        overrides = getattr(self.agent.agent, "tool_overrides", {})
        tools = []
        for item in self.environment_actions():
            override = overrides.get(str(item["name"]))
            if override is not None and override.hidden:
                continue
            description = (
                override.description
                if override is not None and override.description
                else item["description"]
            )
            tools.append({"name": item["name"], "description": description})
        offered = list(self.calls[0].get("tools") or ()) if self.calls else []
        return {
            "tools": tools,
            "offered_to_model": offered,
            "called": sorted(self.actions_used),
        }

    def task_view(self) -> dict[str, Any]:
        """The Task: what the Agent was asked, and the answer key it never saw.

        Returns:
            Instructions, initial State, info, files, and the answer key, labeled.
        """
        return {
            "task": self.task.task_id,
            "category": self.category,
            "instructions": self.task.instructions,
            "initial_state": self.task.state,
            "info": self.task.info,
            "files": [item.path for item in self.task.resources if getattr(item, "path", None)],
            "expected": {"note": EXPECTED_NOTE, "value": self.task.expected},
        }

    def task_file(self, path: str) -> str:
        """One of the Task's files.

        Returns:
            The file's text.

        Raises:
            ValueError: When the Task has no such file.
        """
        folder = (self.job.root / "tasks" / self.task.task_id).resolve()
        target = (folder / path).resolve()
        if not target.is_relative_to(folder) or not target.is_file():
            raise ValueError(f"Task {self.task.task_id} has no file {path!r}.")
        return clip(target.read_text("utf-8"), 6000)


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                yield value


def _usage(call: Mapping[str, Any]) -> Mapping[str, Any]:
    usage = call.get("usage")
    return usage if isinstance(usage, dict) else {}


def _content(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    return "" if content is None else json.dumps(content)


def _tool_name(call: Any) -> str:
    if isinstance(call, dict):
        function = call.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return str(call.get("name") or "")
    return str(call)


def _call(item: Mapping[str, Any]) -> tuple[Any, str]:
    return item.get("action"), json.dumps(item.get("arguments"), sort_keys=True)


_EMPTY_KEY = "{}"


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if value == {}:
        return {prefix: _EMPTY_KEY}
    if isinstance(value, dict) and value:
        flat: dict[str, Any] = {}
        for key, item in value.items():
            flat.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return flat
    if isinstance(value, list) and value and isinstance(value[0], dict | list):
        flat = {}
        for index, item in enumerate(value):
            flat.update(_flatten(item, f"{prefix}.{index}"))
        return flat
    return {prefix: value}


def failed_trials(evidence: JobEvidence, trial_ids: Sequence[str] = ()) -> list[TrialEvidence]:
    """The failed dev Trials to inspect: all of them, or the ones named.

    Returns:
        The Trials.

    Raises:
        ProjectError: When a named Trial isn't a dev Trial of the Job.
    """
    if not trial_ids:
        return evidence.failed()
    return [evidence.trial(item) for item in trial_ids]


__all__ = [
    "CHARS_PER_TOKEN",
    "EXPECTED_NOTE",
    "TEXT_LIMIT",
    "JobEvidence",
    "TrialEvidence",
    "clip",
    "estimate_tokens",
    "failed_trials",
    "step_info",
    "trial_passed",
]
