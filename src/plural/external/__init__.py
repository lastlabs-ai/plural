"""Run your own agent service against Plural Tasks.

A Job sends the service a signed request for each episode. The service
verifies it, works the Task through the episode's actions and files, reports
its trace, and finishes with an answer::

    from plural.external import Episode, verify_request

    message = verify_request(body, headers)  # raises SignatureError
    if message.type == "episode.start":
        episode = Episode(message)
        observation = episode.act("submit", quantity=42)
        episode.finish("42 doors")
"""

from plural.external.client import KEY_VARIABLE, Episode, EpisodeError, Ping, verify_request
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

__all__ = [
    "KEY_VARIABLE",
    "Episode",
    "EpisodeAction",
    "EpisodeError",
    "EpisodeStart",
    "EpisodeTask",
    "Ping",
    "SignatureError",
    "new_signing_key",
    "sign",
    "signing_key",
    "verify",
    "verify_request",
]
