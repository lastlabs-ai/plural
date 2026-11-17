"""Checkpoints: everything needed to continue a Trial from after step *k*.

A checkpoint is rebuilt on demand from a finished Trial's artifacts, never
written by the Harness:

- the **world**: each App's State and random number generator from
  ``states.jsonl``, the host's counters, the observation at *k*, and the
  workspace snapshot *k* from ``workspace.bundle``;
- the **Agent context**: the messages the Agent had seen through observation
  *k*, in a neutral OpenAI-style form, with the names of the tools it used.
  It comes from the model calls a native loop or custom Harness recorded, and
  otherwise from the step timeline; an External Agent's is marked
  ``reported``.

``plural trial checkpoint`` saves one under a name, in the Trial's
``checkpoints/`` folder, so a fork or a Task's ``from_checkpoint`` can reuse
it. A checkpoint holds App State, so it stays with the Job's records; only the
Agent context and observation *k* ever reach a Harness.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from plural.apps.workspace import BUNDLE_FILE, commit_for

CHECKPOINTS_FOLDER = "checkpoints"
"""The folder in a Trial's directory that holds its named checkpoints."""

ContextSource = Literal["recorded", "steps", "reported"]
"""Where an Agent context came from: model calls the Harness recorded, the step
timeline alone, or an External Agent's self-reported trace."""

History = Literal["native", "transcript", "none"]
"""How a fork handed the history to its Agent (§4.2's rule)."""

_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_BACKGROUND = re.compile(
    r"(?:^|[\s;(])(?:nohup|setsid|disown|daemonize)\b"
    # A lone `&`, not `&&`, `>&` or `&>`, also closing a quoted `sh -c '...'` as CLI
    # Harnesses run commands. An `&` in quoted text warns too: better than missing one.
    r"|(?<![&>|])&(?![&>\d])(?=\s|$|[;)'\"])"
    r"|\b(?:tmux\s+new(?:-session)?|screen)\b[^\n]*\s-d"
    r"|\bdocker\s+(?:run|compose\s+up)\b[^\n]*\s(?:-d|--detach)\b"
)


class CheckpointWorkspace(BaseModel):
    """The workspace snapshot a checkpoint restores."""

    model_config = ConfigDict(extra="forbid")

    available: bool = False
    commit: str | None = None
    skipped: list[str] = Field(default_factory=list)
    """Files over the snapshot cap; a fork does not get them back."""
    problem: str | None = None


class AgentContext(BaseModel):
    """What one Agent had seen through observation *k*, in a Harness-neutral form."""

    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]] = Field(default_factory=list)
    """OpenAI-style chat messages, tool calls included."""
    turn: int = 0
    tools_used: list[str] = Field(default_factory=list)
    """Every tool the history called: Environment actions and Harness tools."""
    source: ContextSource = "steps"
    summary: str | None = None
    memory: Any = None
    compaction: list[Any] | None = None


class Checkpoint(BaseModel):
    """Everything needed to continue a Trial from after step ``step``.

    ``apps`` and ``rng`` are private to the Job: they restore the App host and
    never reach a Harness. ``contexts`` is keyed by seat, with ``""`` for a
    Trial one Agent works alone.
    """

    model_config = ConfigDict(extra="forbid")

    trial_id: str
    job_id: str = ""
    step: int = Field(ge=0)
    name: str | None = None
    task_digest: str = ""
    agent_digest: str = ""
    apps: dict[str, Any] = Field(default_factory=dict)
    rng: dict[str, Any] = Field(default_factory=dict)
    initial: dict[str, Any] = Field(default_factory=dict)
    turns: int = 0
    elapsed: float = 0.0
    observation: Any = None
    rendered: str = ""
    workspace: CheckpointWorkspace = Field(default_factory=CheckpointWorkspace)
    contexts: dict[str, AgentContext] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    heldout: bool = False
    prefix_steps: list[dict[str, Any]] = Field(default_factory=list)
    """The original's steps 1 to ``step``, as its host recorded them, with rewards."""
    prefix_states: list[dict[str, Any]] = Field(default_factory=list)
    prefix_metrics: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def digest(self) -> str:
        """A stable digest of what the checkpoint restores; its name is not part of it.

        Returns:
            ``sha256:`` and the hex digest.
        """
        payload = self.model_dump(mode="json", exclude={"name", "warnings", "heldout"})
        payload["workspace"] = {"commit": self.workspace.commit}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()

    @property
    def tools_used(self) -> list[str]:
        """Every tool any seat's history called, sorted."""
        return sorted({name for context in self.contexts.values() for name in context.tools_used})

    def context(self, seat: str | None = None) -> AgentContext:
        """One seat's context, or the only Agent's.

        Returns:
            The context; empty when the seat has none.
        """
        return self.contexts.get(seat or "", AgentContext())

    def restore_inputs(self) -> dict[str, Any]:
        """The App host's ``restore`` inputs, sent in its bootstrap.

        Returns:
            States, generators, counters, and observation *k*.
        """
        return {
            "states": self.apps,
            "rng": self.rng,
            "initial": self.initial,
            "step": self.step,
            "turns": self.turns,
            "elapsed": self.elapsed,
            "observation": self.observation,
            "rendered": self.rendered,
        }


# The world at step k.


def world_at(
    states: Iterable[Mapping[str, Any]], step: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Fold ``states.jsonl`` up to ``step``: each App's State and generator then.

    Each line holds only the Apps whose State, or generator, changed.

    Returns:
        ``(states, generators, initial)``: the State and generator of each App
        after step ``step``, and every App's State after the reset.
    """
    current: dict[str, Any] = {}
    generators: dict[str, Any] = {}
    initial: dict[str, Any] = {}
    for line in states:
        number = line.get("step")
        if not isinstance(number, int) or number > step:
            continue
        changed = line.get("state")
        if isinstance(changed, Mapping):
            current.update(changed)
            if number == 0:
                initial.update(changed)
        rng = line.get("rng")
        if isinstance(rng, Mapping):
            generators.update(rng)
    return current, generators, initial


def opening_of(states: Iterable[Mapping[str, Any]]) -> tuple[Any, str]:
    """The observation the Agent saw on reset, as the host recorded it at step 0.

    Returns:
        ``(observation, rendered)``.
    """
    for line in states:
        if line.get("step") == 0 and isinstance(line.get("opening"), Mapping):
            opening = line["opening"]
            return opening.get("observation"), str(opening.get("rendered") or "")
    return None, ""


def steps_through(
    steps: Iterable[Mapping[str, Any]], step: int, seat: str | None = None
) -> list[dict[str, Any]]:
    """The timeline's steps numbered up to ``step``, optionally one seat's.

    Returns:
        The steps, in order.
    """
    kept = []
    for item in steps:
        number = item.get("step")
        if not isinstance(number, int) or number > step or number < 1:
            continue
        if seat is not None and item.get("seat") not in {seat, None}:
            continue
        kept.append(dict(item))
    return sorted(kept, key=lambda item: int(item["step"]))


# The Agent's context at step k.


def tool_names(steps: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every tool the steps called, once each, sorted.

    Returns:
        Environment action and Harness tool names.
    """
    return sorted({str(item["action"]) for item in steps if item.get("action")})


def _content(step: Mapping[str, Any]) -> str:
    rendered = step.get("rendered")
    if isinstance(rendered, str) and rendered:
        return rendered
    info = step.get("info")
    if isinstance(info, Mapping) and info.get("error"):
        return f"Error: {info['error']}"
    observation = step.get("observation")
    if observation is None:
        return ""
    return observation if isinstance(observation, str) else json.dumps(observation, default=str)


def messages_from_steps(
    instructions: str, steps: Sequence[Mapping[str, Any]], opening: str = ""
) -> list[dict[str, Any]]:
    """A chat history rebuilt from the step timeline alone, one tool call per step.

    Returns:
        OpenAI-style messages.
    """
    first = instructions if not opening else f"{instructions}\n\n{opening}"
    messages: list[dict[str, Any]] = [{"role": "user", "content": first}]
    for item in steps:
        call_id = f"call_{item.get('step')}"
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": str(item.get("action") or "tool"),
                            "arguments": json.dumps(item.get("arguments") or {}, default=str),
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": str(item.get("action") or "tool"),
                "content": _content(item),
            }
        )
    return messages


def _record_step(record: Mapping[str, Any]) -> int | None:
    info = record.get("info")
    number = info.get("step") if isinstance(info, Mapping) else None
    return number if isinstance(number, int) and not isinstance(number, bool) else None


def _answered(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop tool calls the history never got a result for, so any model accepts it.

    Returns:
        The messages, with unanswered calls removed.
    """
    answered = {str(item.get("tool_call_id")) for item in messages if item.get("role") == "tool"}
    cleaned = []
    for message in messages:
        calls = message.get("tool_calls")
        if message.get("role") == "assistant" and isinstance(calls, list):
            kept = [call for call in calls if str(call.get("id")) in answered]
            message = (
                {**message, "tool_calls": kept}
                if kept
                else {key: value for key, value in message.items() if key != "tool_calls"}
            )
            if not kept and not message.get("content"):
                continue
        cleaned.append(message)
    return cleaned


def context_at(
    step: int,
    *,
    steps: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]] = (),
    instructions: str = "",
    opening: str = "",
    seat: str | None = None,
    reported: bool = False,
) -> AgentContext:
    """The Agent's context through observation ``step``.

    From the model calls the Harness recorded when there are any, since they
    hold the model's own words; otherwise from the timeline.

    Returns:
        The context.
    """
    from plural.transcript import episode_to_messages

    prefix = steps_through(steps, step, seat)
    tools = tool_names(prefix)
    if step > 0 and seat is None and any(item.get("kind") == "model.call" for item in records):
        ordered = sorted(records, key=lambda item: int(item.get("sequence") or 0))
        cut = 0
        for index, record in enumerate(ordered):
            number = _record_step(record) if record.get("kind") == "environment.step" else None
            if number is not None and number <= step:
                cut = index + 1
        kept = ordered[:cut]
        if any(item.get("kind") == "model.call" for item in kept):
            messages = _answered(episode_to_messages(kept)["messages"])
            turn = sum(1 for item in kept if item.get("kind") == "model.call")
            return AgentContext(messages=messages, turn=turn, tools_used=tools, source="recorded")
    turns = {item.get("turn") for item in prefix if isinstance(item.get("turn"), int)}
    return AgentContext(
        messages=messages_from_steps(instructions, prefix, opening),
        turn=max((int(value) for value in turns if value is not None), default=len(prefix)),
        tools_used=tools,
        source="reported" if reported else "steps",
    )


def transcript_text(context: AgentContext, *, limit: int = 4_000) -> str:
    """The history as a readable transcript, for an Agent that lacks its tools.

    Returns:
        Plain text: "Earlier you ran `ls` and saw ...", one paragraph per call.
    """
    results = {
        str(item.get("tool_call_id")): str(item.get("content") or "")
        for item in context.messages
        if item.get("role") == "tool"
    }
    lines = ["Earlier in this episode:"]
    for message in context.messages:
        if message.get("role") != "assistant":
            continue
        text = message.get("content")
        if isinstance(text, str) and text.strip():
            lines.append(f"You said: {text.strip()[:limit]}")
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name") or "a tool"
            arguments = str(function.get("arguments") or "")
            seen = results.get(str(call.get("id")), "")
            shown = arguments if len(arguments) <= 400 else arguments[:400] + "..."
            output = seen if len(seen) <= limit else seen[:limit] + "..."
            lines.append(f"You ran `{name}` with {shown} and saw:\n{output}")
    return "\n\n".join(lines)


# Warnings.


def _command_text(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    if not isinstance(arguments, Mapping):
        return ""
    for key in ("command", "cmd", "script", "input"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
    return ""


def background_warnings(steps: Iterable[Mapping[str, Any]]) -> list[str]:
    """A warning for each step that started a process the checkpoint can't bring back.

    Workspace snapshots hold files, not running processes, so a server the
    Agent started is gone after a restore.

    Returns:
        The warnings.
    """
    warnings = []
    for item in steps:
        info = item.get("info")
        flagged = isinstance(info, Mapping) and bool(info.get("background"))
        command = _command_text(item.get("arguments"))
        if flagged or (command and _BACKGROUND.search(command)):
            shown = command.strip().splitlines()[0][:120] if command else str(item.get("action"))
            warnings.append(
                f"Step {item.get('step')} started a background process (`{shown}`). "
                "Checkpoints restore files, not running processes, so it isn't running "
                "after the restore."
            )
    return warnings


# Building and saving.


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    return rows


def build_checkpoint(
    artifacts: Path,
    step: int,
    *,
    trial_id: str,
    job_id: str = "",
    instructions: str = "",
    seats: Sequence[str] = (),
    task_digest: str = "",
    agent_digest: str = "",
    heldout: bool = False,
) -> Checkpoint:
    """Rebuild the checkpoint after ``step`` from a finished Trial's artifacts.

    Returns:
        The checkpoint.

    Raises:
        ValueError: When the Trial has no such step.
    """
    from plural.apps.host import STATES_FILE, STEPS_FILE
    from plural.harness.episode import EPISODE_FILE

    states = _read_jsonl(artifacts / STATES_FILE)
    steps = _read_jsonl(artifacts / STEPS_FILE)
    numbers = [int(item["step"]) for item in steps if isinstance(item.get("step"), int)]
    last = max(numbers, default=0)
    if step < 0 or step > last:
        raise ValueError(f"Trial {trial_id} has steps 0 to {last}; there is no step {step}.")
    apps, rng, initial = world_at(states, step)
    opening, opening_text = opening_of(states)
    prefix = steps_through(steps, step)
    if step == 0:
        observation, rendered = opening, opening_text
    else:
        at = prefix[-1]
        observation, rendered = at.get("observation"), str(at.get("rendered") or "")
    records = _read_jsonl(artifacts / EPISODE_FILE)
    reported = (artifacts / "agent-trace.json").is_file()
    contexts: dict[str, AgentContext] = {}
    if seats:
        for seat in seats:
            contexts[seat] = context_at(
                step, steps=steps, instructions=instructions, opening=opening_text, seat=seat
            )
    else:
        contexts[""] = context_at(
            step,
            steps=steps,
            records=records,
            instructions=instructions,
            opening=opening_text,
            reported=reported,
        )
    workspace = _workspace(artifacts, step)
    warnings = background_warnings(prefix)
    if workspace.skipped:
        warnings.append(
            f"{len(workspace.skipped)} workspace file(s) were over the snapshot cap and are not "
            f"restored: {', '.join(workspace.skipped[:5])}."
        )
    if not workspace.available:
        warnings.append(f"The workspace is not restored: {workspace.problem or 'no snapshot'}.")
    turns = max((int(item.get("turn") or 0) for item in prefix), default=0)
    elapsed = max((float(item.get("t") or 0.0) for item in prefix), default=0.0)
    metrics = [
        item
        for item in _read_jsonl(artifacts / "metrics.jsonl")
        if isinstance(item.get("step"), int) and int(item["step"]) <= step
    ]
    return Checkpoint(
        trial_id=trial_id,
        job_id=job_id,
        step=step,
        task_digest=task_digest,
        agent_digest=agent_digest,
        apps=apps,
        rng=rng,
        initial=initial,
        turns=turns,
        elapsed=elapsed,
        observation=observation,
        rendered=rendered,
        workspace=workspace,
        contexts=contexts,
        warnings=warnings,
        heldout=heldout,
        prefix_steps=prefix,
        prefix_states=[
            line for line in states if isinstance(line.get("step"), int) and line["step"] <= step
        ],
        prefix_metrics=metrics,
    )


def _workspace(artifacts: Path, step: int) -> CheckpointWorkspace:
    report_path = artifacts / "workspace.json"
    report = json.loads(report_path.read_text("utf-8")) if report_path.is_file() else None
    if not isinstance(report, Mapping):
        return CheckpointWorkspace(problem="the Trial recorded no workspace snapshots")
    if not (artifacts / BUNDLE_FILE).is_file():
        return CheckpointWorkspace(problem=str(report.get("problem") or "no workspace.bundle"))
    commit = commit_for(report, step)
    skipped = sorted(
        {
            str(item.get("path"))
            for item in report.get("skipped") or []
            if isinstance(item, Mapping) and int(item.get("step") or 0) <= step
        }
    )
    return CheckpointWorkspace(
        available=commit is not None,
        commit=commit,
        skipped=skipped,
        problem=None if commit is not None else f"no snapshot for step {step}",
    )


def checkpoint_path(trial_dir: Path, name: str) -> Path:
    """Where a named checkpoint lives in a Trial's directory.

    Returns:
        The file path.

    Raises:
        ValueError: When the name is not a lowercase slug.
    """
    if not _NAME.match(name):
        raise ValueError(
            f"Checkpoint name {name!r} must be lowercase letters, digits, '.', '_' or '-'."
        )
    return trial_dir / CHECKPOINTS_FOLDER / f"{name}.json"


def save_checkpoint(trial_dir: Path, checkpoint: Checkpoint) -> Path:
    """Store a named checkpoint with its Trial.

    Returns:
        The file written.

    Raises:
        ValueError: When the checkpoint has no name, or the name is taken.
    """
    if not checkpoint.name:
        raise ValueError("A saved checkpoint needs a name.")
    path = checkpoint_path(trial_dir, checkpoint.name)
    if path.exists():
        existing = load_checkpoint(path)
        if existing.digest != checkpoint.digest:
            raise ValueError(
                f"Trial {checkpoint.trial_id} already has a checkpoint named "
                f"{checkpoint.name!r} at step {existing.step}."
            )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(checkpoint.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def load_checkpoint(path: Path) -> Checkpoint:
    """Read a saved checkpoint.

    Returns:
        The checkpoint.
    """
    return Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))


def history_rule(
    context: AgentContext,
    tools_offered: Iterable[str],
    *,
    supports_resume: bool,
    external: bool = False,
    agent_name: str = "The Agent",
    step: int = 0,
) -> tuple[History, list[str]]:
    """How a fork hands the history to a new Agent: one rule, no options (§4.2).

    - An External Agent without resume support gets the restored world and the
      Task only (``none``); with it, always a transcript, since its tools are
      its own.
    - An Agent that lacks a tool the history used gets a readable transcript.
    - An Agent whose Harness can't take a history as its own conversation gets
      a transcript too.
    - Otherwise the history is its own conversation (``native``).

    Returns:
        The history kind and the warnings to print and record.
    """
    if step == 0:
        return "native", []
    if external:
        if not supports_resume:
            return "none", [
                f"{agent_name} is an External Agent without resume support, so it got the "
                f"restored world and the Task only, not the history before step {step}."
            ]
        return "transcript", []
    missing = sorted(set(context.tools_used) - set(tools_offered))
    if missing:
        shown = ", ".join(missing[:8]) + (", ..." if len(missing) > 8 else "")
        noun = "tool" if len(missing) == 1 else "tools"
        return "transcript", [
            f"{agent_name} lacks {len(missing)} {noun} used before step {step} ({shown}). "
            "It got the history as a transcript, not as its own tool calls."
        ]
    if not supports_resume:
        return "transcript", [
            f"{agent_name}'s Harness can't continue a history as its own conversation. "
            "It got the history as a transcript."
        ]
    return "native", []


__all__ = [
    "CHECKPOINTS_FOLDER",
    "AgentContext",
    "Checkpoint",
    "CheckpointWorkspace",
    "ContextSource",
    "History",
    "background_warnings",
    "build_checkpoint",
    "checkpoint_path",
    "context_at",
    "history_rule",
    "load_checkpoint",
    "messages_from_steps",
    "opening_of",
    "save_checkpoint",
    "steps_through",
    "tool_names",
    "transcript_text",
    "world_at",
]
