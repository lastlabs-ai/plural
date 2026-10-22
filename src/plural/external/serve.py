"""Take Plural episodes in a few lines, with each one traced.

``endpoint`` verifies each signed request, answers pings, and runs your handler
for each episode in the background, inside that episode's traced run. Return
the answer, or call ``run.finish``::

    from plural.external import serve


    def work(episode, run):
        return my_agent.invoke(episode.task.instructions)


    app = serve.app(work)  # uvicorn service:app
    # or, in an existing FastAPI app:
    api.add_route("/plural", serve.endpoint(work), methods=["POST"])
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from plural.external.client import Episode, verify_request
from plural.external.protocol import SignatureError
from plural.external.tracing import Run, Tracer, tracer

try:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError('Serving episodes needs Starlette: pip install "plural[external]"') from exc

log = logging.getLogger("plural.external")

Handler = Callable[[Episode, Run], Any]
MAX_START_BYTES = 8 * 1024 * 1024


def endpoint(
    handler: Handler,
    *,
    tracer_: Tracer | None = None,
    key: str | None = None,
    verify: str | bool = True,
    max_episodes: int = 16,
) -> Callable[[Request], Awaitable[Response]]:
    """A Starlette endpoint that takes signed episode starts.

    Args:
        handler: Called as ``handler(episode, run)`` for each episode, in a
            thread of its own; it may be a coroutine function. What it returns
            is the answer, unless it finished the run itself.
        tracer_: The tracer; defaults to the process's
            (:func:`plural.external.tracer`).
        key: The signing key. Defaults to ``PLURAL_SIGNING_KEY``.
        verify: How the agent checks the Job's certificate: ``True``, a CA
            bundle path, or ``False`` for a self-signed test certificate.
        max_episodes: Episodes run at once; more are answered 429, and the
            Job fails that Trial rather than waiting.

    Returns:
        The endpoint.

    Raises:
        ConfigurationError: When no tracer is given and ``plural-agent.yaml``
            cannot be read.
    """
    slots = threading.BoundedSemaphore(max_episodes)
    traced = tracer_ or tracer()

    async def receive(request: Request) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_START_BYTES:
            return JSONResponse({"error": "request too large"}, status_code=413)
        body = await request.body()
        if len(body) > MAX_START_BYTES:
            return JSONResponse({"error": "request too large"}, status_code=413)
        try:
            message = verify_request(body, dict(request.headers), key=key)
        except SignatureError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        if message.type == "ping":
            return JSONResponse({"ok": True})
        if not slots.acquire(blocking=False):
            return JSONResponse({"error": "too many episodes at once"}, status_code=429)
        episode = Episode(message, verify=verify)
        threading.Thread(
            target=_work,
            args=(handler, episode, traced, slots),
            name=f"plural-episode-{message.episode_id}",
            daemon=True,
        ).start()
        return JSONResponse({"accepted": True}, status_code=202)

    return receive


def app(handler: Handler, *, path: str = "/plural", **options: Any) -> Starlette:
    """An ASGI app serving :func:`endpoint` at ``path``, for ``uvicorn``.

    Returns:
        The app.
    """
    return Starlette(routes=[Route(path, endpoint(handler, **options), methods=["POST"])])


def _work(handler: Handler, episode: Episode, tracer_: Tracer, slots: threading.Semaphore) -> None:
    try:
        with tracer_.episode(episode) as run:
            answer = handler(episode, run)
            if inspect.isawaitable(answer):
                answer = asyncio.run(_wait(answer))
            if not run.finished:
                run.finish(answer)
    except Exception:  # noqa: BLE001 - the run already failed the episode
        log.exception("Episode %s failed", episode.start.episode_id)
    finally:
        slots.release()


async def _wait(value: Awaitable[Any]) -> Any:
    return await value


__all__ = ["app", "endpoint"]
