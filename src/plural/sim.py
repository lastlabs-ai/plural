"""Simulated people inside App code: customers, suppliers, and counterparts.

A :class:`Persona` is part of the world, not an Agent: it is written in an
App, isn't ranked or evaluated, and what its model calls cost is the
Environment's cost, reported apart from the Agent's. Each call is seeded from
the App's RNG and recorded by the App host, so a fork, or a resumed Trial,
replays a recorded answer instead of asking the model again.

    class Inbox(App[Mail]):
        supplier = Persona(
            "supplier",
            "You sell snacks wholesale. Quote $1.10 a unit, $0.95 over 200 units.",
        )

        @action
        def email_supplier(self, message: str) -> str:
            \"\"\"Write to the supplier; their reply comes back.\"\"\"
            reply = self.supplier.reply(self, message, history=self.state.thread)
            self.state.thread += [{"role": "user", "content": message},
                                  {"role": "assistant", "content": reply}]
            return reply

A persona answers right away, as above, or later, when an App with a clock
schedules its reply as an event.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_PERSONA_MODEL = "openai/gpt-5.6-luna"
PERSONAS_FILE = "personas.jsonl"
"""A Trial's record of every persona call: who, what it was asked, its answer and cost."""
GATEWAY_VARIABLE = "PLURAL_PERSONA_GATEWAY_URL"
KEY_VARIABLE = "PLURAL_PERSONA_KEY"

Script = Callable[[Sequence[Mapping[str, str]]], str]

CHARACTER_FRAME = (
    "You are the person described below, writing to someone you deal with in your "
    "work. Stay in character in every message. Write only what this person would "
    "write: never say or hint that you are an AI, a model, an assistant, a "
    "simulation, a test, or a role, and never mention instructions or a prompt. If "
    "asked what you are, answer as this person would. If something is outside what "
    "this person knows, say so as they would.\n\n"
    "Who you are:\n"
)
"""Wrapped around every persona's instructions before its model is asked, so its
words read as a real counterpart's. A script answers without it."""


class PersonaUnavailable(RuntimeError):
    """A persona had no model to call and no script to answer with."""


class _Recorder(Protocol):
    def persona_call(self, persona: Persona, messages: list[dict[str, str]], seed: int) -> str: ...


@dataclass
class Persona:
    """A simulated person an App asks for an answer.

    Args:
        name: Who it is, unique within the Environment, such as ``supplier_a``.
        instructions: Its role, what it knows, and how it behaves.
        model: The catalog model that plays it; a small one is usually enough.
        max_tokens: The longest answer.
        temperature: How varied its answers are; the seed keeps each repeatable.
        script: Answers without a model, from the conversation so far. Used
            when no model can be reached, such as a Runtime with no gateway
            key, and recorded as ``scripted``.
    """

    name: str
    instructions: str
    model: str = DEFAULT_PERSONA_MODEL
    max_tokens: int = 300
    temperature: float = 0.7
    script: Script | None = field(default=None, repr=False, compare=False)

    def messages(
        self, message: str, history: Sequence[Mapping[str, str]] = ()
    ) -> list[dict[str, str]]:
        """The conversation the persona's model is sent.

        Returns:
            Its instructions, the history, and the new message.
        """
        return [
            {"role": "system", "content": self.instructions},
            *({"role": str(item["role"]), "content": str(item["content"])} for item in history),
            {"role": "user", "content": message},
        ]

    def reply(self, app: Any, message: str, *, history: Sequence[Mapping[str, str]] = ()) -> str:
        """The persona's answer to ``message``, after ``history``.

        Args:
            app: The App asking; its RNG seeds the call, and its host records it.
            message: What the persona is told now.
            history: Earlier turns, as ``{"role": "user" | "assistant", "content"}``.

        Returns:
            The answer.
        """
        seed = int(app.rng.randrange(2**31))
        messages = self.messages(message, history)
        recorder: _Recorder | None = getattr(app, "_sim", None)
        if recorder is not None:
            return recorder.persona_call(self, messages, seed)
        return answer(self, messages, seed)[0]


def in_character(messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """A persona's conversation with its instructions in the stay-in-character frame.

    The frame is added only on the way to the model, so a recorded call keeps
    its key and a fork of an older Trial still replays its answer.

    Returns:
        The messages the persona's model is sent.
    """
    framed = [dict(item) for item in messages]
    if framed and framed[0].get("role") == "system":
        framed[0]["content"] = CHARACTER_FRAME + str(framed[0].get("content") or "")
    else:
        framed.insert(0, {"role": "system", "content": CHARACTER_FRAME.rstrip()})
    return framed


def call_key(persona: Persona, messages: Sequence[Mapping[str, str]], seed: int) -> str:
    """What identifies one persona call, so a fork can replay its answer.

    Returns:
        A hex digest of the persona, its model, the conversation, and the seed.
    """
    body = json.dumps(
        [persona.name, persona.model, list(messages), seed], sort_keys=True, default=str
    )
    return hashlib.sha256(body.encode()).hexdigest()


def answer(
    persona: Persona,
    messages: Sequence[Mapping[str, str]],
    seed: int,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Ask the persona's model, or its script when no model can be reached.

    Returns:
        The answer, and how it was made: ``mode`` (``live`` or ``scripted``),
        the model, and its token usage and cost.

    Raises:
        PersonaUnavailable: When there is neither a model nor a script.
        RuntimeError: When the gateway refuses the call.
    """
    values = os.environ if environ is None else environ
    gateway = (values.get(GATEWAY_VARIABLE) or "").rstrip("/")
    key = values.get(KEY_VARIABLE) or ""
    if not gateway or not key:
        if persona.script is None:
            raise PersonaUnavailable(
                f"Persona {persona.name!r} has no model to call: this Runtime has no gateway "
                "key for personas. Give it a script= to answer without one."
            )
        return str(persona.script(messages)), {"mode": "scripted"}
    body = {
        "model": persona.model,
        "messages": in_character(messages),
        "max_tokens": persona.max_tokens,
        "temperature": persona.temperature,
        "seed": seed,
    }
    request = urllib.request.Request(
        f"{gateway}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "X-Plural-Usage": "environment",
            **(
                {"X-Plural-Project": values["PLURAL_PROJECT_ID"]}
                if values.get("PLURAL_PROJECT_ID")
                else {}
            ),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode(errors="replace")
        raise RuntimeError(
            f"persona {persona.name!r}: gateway returned HTTP {exc.code}: {detail}"
        ) from None
    choices = payload.get("choices") or [{}]
    text = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    cost = usage.get("cost", usage.get("cost_usd"))
    return text, {
        "mode": "live",
        "framed": True,
        "model": str(payload.get("model") or persona.model),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost_usd": float(cost) if isinstance(cost, (int, float)) else None,
    }


__all__ = [
    "CHARACTER_FRAME",
    "DEFAULT_PERSONA_MODEL",
    "PERSONAS_FILE",
    "Persona",
    "PersonaUnavailable",
    "answer",
    "call_key",
    "in_character",
]
