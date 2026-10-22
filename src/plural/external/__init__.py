"""Run your own agent service against Plural Tasks, and trace it to Plural.

A Job sends the service a signed request for each episode. The service
verifies it, works the Task through the episode's actions and files, reports
its trace, and finishes with an answer::

    from plural.external import Episode, verify_request

    message = verify_request(body, headers)  # raises SignatureError
    if message.type == "episode.start":
        episode = Episode(message)
        observation = episode.act("submit", quantity=42)
        episode.finish("42 doors")

A :class:`Tracer` traces the agent's runs from any framework: into the Job
during an episode, and as production traces of the Agent otherwise. See
:mod:`plural.external.tracing`, the adapters in :mod:`plural.external.otel`,
:mod:`plural.external.langchain`, and :mod:`plural.external.openai_agents`, and
:mod:`plural.external.serve` for an endpoint that does all of this.
"""

from plural.external.client import KEY_VARIABLE, Episode, EpisodeError, Ping, ping, verify_request
from plural.external.config import AgentConfig, Capture, FlushPolicy
from plural.external.protocol import (
    EpisodeAction,
    EpisodeStart,
    EpisodeTask,
    SignatureError,
    new_signing_key,
    sign,
    signing_key,
    verify,
)
from plural.external.tracing import Run, ToolCall, Tracer, current_run, set_tracer, tracer

__all__ = [
    "KEY_VARIABLE",
    "AgentConfig",
    "Capture",
    "Episode",
    "EpisodeAction",
    "EpisodeError",
    "EpisodeStart",
    "EpisodeTask",
    "FlushPolicy",
    "Ping",
    "Run",
    "SignatureError",
    "ToolCall",
    "Tracer",
    "current_run",
    "new_signing_key",
    "ping",
    "set_tracer",
    "sign",
    "signing_key",
    "tracer",
    "verify",
    "verify_request",
]
