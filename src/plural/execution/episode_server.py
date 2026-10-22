"""The HTTPS server a Job runs for External Agents.

Each episode gets its own routes under ``/episodes/{id}`` and its own bearer
token. The agent acts, reads the Task's files, reports its trace, and
finishes there; it reaches nothing else. The server keeps only each token's
SHA-256, and a token stops working when its episode finishes, is revoked, or
passes its deadline.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator

from plural.atif import validate_atif
from plural.blobs import content_type_for
from plural.common import FrozenModel
from plural.external.protocol import EpisodeAction, EpisodeURLs, is_loopback

MAX_ACTION_BYTES = 1024 * 1024
MAX_FINISH_BYTES = 4 * 1024 * 1024
MAX_TRACE_BYTES = 32 * 1024 * 1024
TOKEN_GRACE_SECONDS = 30.0
"""How long after its deadline a token still works, for a finish already on its way."""

ActionCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class EpisodeServerOptions(FrozenModel):
    """Where the Job listens for External Agents, and how they reach it.

    ``listen`` is ``HOST:PORT``; port 0 picks a free one. Any address but
    loopback needs ``tls_cert`` and ``tls_key``. ``public_url`` is the base
    URL agents use when it differs from the listening address, such as behind
    a load balancer or a tunnel.
    """

    listen: str = "127.0.0.1:0"
    public_url: str | None = None
    tls_cert: Path | None = None
    tls_key: Path | None = None

    @field_validator("listen")
    @classmethod
    def _address(cls, value: str) -> str:
        host, separator, port = value.rpartition(":")
        if not separator or not host or not port.isdigit() or int(port) > 65535:
            raise ValueError(f"--listen takes HOST:PORT, such as 127.0.0.1:8765, not {value!r}")
        return value

    @field_validator("public_url")
    @classmethod
    def _public(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError(f"--public-url must be an https URL, not {value!r}")
        if parts.scheme == "http" and not is_loopback(parts.hostname):
            raise ValueError("--public-url must use https unless it is a loopback address")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("--public-url may not carry credentials, a query, or a fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _tls(self) -> EpisodeServerOptions:
        if (self.tls_cert is None) != (self.tls_key is None):
            raise ValueError("--tls-cert and --tls-key go together")
        if not is_loopback(self.host) and self.tls_cert is None:
            raise ValueError(
                f"Listening on {self.host} would expose episodes beyond this machine without "
                "TLS. Pass --tls-cert and --tls-key, or listen on 127.0.0.1 behind a proxy "
                "that serves https."
            )
        return self

    @property
    def host(self) -> str:
        """The address to bind."""
        return self.listen.rpartition(":")[0].strip("[]")

    @property
    def port(self) -> int:
        """The port to bind; 0 for any free one."""
        return int(self.listen.rpartition(":")[2])


@dataclass(eq=False)
class EpisodeSession:
    """One episode's routes, as the server holds them."""

    episode_id: str
    token_digest: bytes
    expires_at: float
    actions: dict[str, EpisodeAction]
    files: dict[str, bytes]
    max_turns: int
    act: ActionCall
    turns: int = 0
    done: bool = False
    trace: bytes | None = None
    revoked: bool = False
    finished: asyncio.Future[Any] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    mcp: Any = None

    def finish(self, response: Any) -> bool:
        """End the episode with ``response``, once.

        Returns:
            Whether this call ended it.
        """
        if self.finished.done():
            return False
        self.finished.set_result(response)
        self.revoked = True
        return True

    def accepts(self, token: str) -> bool:
        """Whether ``token`` may use this episode now."""
        if self.revoked or time.time() > self.expires_at:
            return False
        return hmac.compare_digest(hashlib.sha256(token.encode()).digest(), self.token_digest)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Take one action through the App host, at most ``max_turns`` in all.

        Raises:
            EpisodeRefused: When the episode is over, the action is unknown, or
                the agent has used its turns.
        """
        if name not in self.actions:
            raise EpisodeRefused(404, f"There is no action {name!r}.")
        async with self.lock:
            if self.done or self.finished.done():
                raise EpisodeRefused(409, "The episode is over.")
            if self.turns >= self.max_turns:
                raise EpisodeRefused(409, f"The episode allows {self.max_turns} actions.")
            self.turns += 1
            reply = await self.act(name, arguments)
            self.done = bool(reply.get("done"))
            return reply


class EpisodeRefused(Exception):
    """A request the episode refuses, with the status to answer it with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _require_server_packages() -> None:
    try:
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "An external Agent needs the Job to serve its episodes. Install it with "
            "`pip install 'plural[mcp]'`."
        ) from None


class EpisodeServer:
    """Serves every External Agent episode of one Job."""

    def __init__(self, options: EpisodeServerOptions | None = None) -> None:
        self.options = options or EpisodeServerOptions()
        self._sessions: dict[str, EpisodeSession] = {}
        self._server: Any = None
        self._task: asyncio.Task[Any] | None = None
        self.base_url = ""

    async def __aenter__(self) -> EpisodeServer:
        _require_server_packages()
        import uvicorn

        config = uvicorn.Config(
            self._app(),
            host=self.options.host,
            port=self.options.port,
            ssl_certfile=str(self.options.tls_cert) if self.options.tls_cert else None,
            ssl_keyfile=str(self.options.tls_key) if self.options.tls_key else None,
            log_level="warning",
            access_log=False,
            lifespan="off",
            server_header=False,
            h11_max_incomplete_event_size=64 * 1024,
        )
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._task.done():
                self._task.result()
                raise RuntimeError("The episode server stopped as it started")
            await asyncio.sleep(0.01)
        port = self._server.servers[0].sockets[0].getsockname()[1]
        scheme = "https" if self.options.tls_cert else "http"
        host = self.options.host
        shown = f"[{host}]" if ":" in host else host
        self.base_url = self.options.public_url or f"{scheme}://{shown}:{port}"
        return self

    async def __aexit__(self, *_exc: object) -> None:
        for session in tuple(self._sessions.values()):
            await self.revoke(session.episode_id)
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def register(
        self,
        *,
        actions: tuple[EpisodeAction, ...],
        files: Mapping[str, bytes],
        max_turns: int,
        deadline: float,
        act: ActionCall,
    ) -> tuple[EpisodeSession, str, EpisodeURLs]:
        """Open one episode's routes.

        Returns:
            The episode, its bearer token, which only the agent is sent, and its URLs.
        """
        token = secrets.token_urlsafe(32)
        episode_id = "eps_" + secrets.token_hex(16)
        session = EpisodeSession(
            episode_id=episode_id,
            token_digest=hashlib.sha256(token.encode()).digest(),
            expires_at=deadline + TOKEN_GRACE_SECONDS,
            actions={item.name: item for item in actions},
            files=dict(files),
            max_turns=max_turns,
            act=act,
        )
        session.mcp = await self._mcp_app(session)
        self._sessions[episode_id] = session
        base = f"{self.base_url}/episodes/{episode_id}"
        urls = EpisodeURLs(
            mcp=f"{base}/mcp/",
            actions=f"{base}/actions",
            files=f"{base}/files",
            trace=f"{base}/trace",
            finish=f"{base}/finish",
        )
        return session, token, urls

    async def revoke(self, episode_id: str) -> None:
        """Close one episode's routes for good."""
        session = self._sessions.pop(episode_id, None)
        if session is None:
            return
        session.revoked = True
        if session.mcp is not None:
            _, stop, running = session.mcp
            stop.set()
            await asyncio.gather(running, return_exceptions=True)

    async def _mcp_app(
        self, session: EpisodeSession
    ) -> tuple[Any, asyncio.Event, asyncio.Task[None]]:
        from fastmcp import FastMCP
        from fastmcp.tools import Tool
        from fastmcp.tools.base import ToolResult
        from mcp.types import TextContent

        class _Action(Tool):
            async def run(self, arguments: dict[str, Any]) -> ToolResult:
                try:
                    reply = await session.call(self.name, dict(arguments))
                except EpisodeRefused as exc:
                    return ToolResult(
                        content=[TextContent(type="text", text=str(exc))], is_error=True
                    )
                return ToolResult(
                    content=[TextContent(type="text", text=_text(reply.get("observation")))],
                    structured_content={"done": bool(reply.get("done"))},
                )

        tools = [
            _Action(
                name=item.name,
                description=item.description or item.name,
                parameters=item.parameters or {"type": "object", "properties": {}},
            )
            for item in session.actions.values()
        ]
        server = FastMCP(name="plural-episode", tools=tools)
        app = server.http_app(
            path="/",
            stateless_http=True,
            json_response=True,
            host_origin_protection=False,
        )
        ready, stop = asyncio.Event(), asyncio.Event()

        async def lifespan() -> None:
            # The MCP app's task group must start and stop in one task.
            async with app.router.lifespan_context(app):
                ready.set()
                await stop.wait()

        running = asyncio.create_task(lifespan())
        waiting = asyncio.create_task(ready.wait())
        await asyncio.wait({running, waiting}, return_when=asyncio.FIRST_COMPLETED)
        waiting.cancel()
        if running.done():
            running.result()
        return app, stop, running

    def _session(self, episode_id: str, authorization: str | None) -> EpisodeSession:
        scheme, _, token = (authorization or "").partition(" ")
        session = self._sessions.get(episode_id)
        if scheme.lower() != "bearer" or session is None or not session.accepts(token.strip()):
            raise EpisodeRefused(401, "This episode's token is missing, wrong, or no longer valid.")
        return session

    def _app(self) -> Any:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response
        from starlette.routing import Mount, Route

        def refused(exc: EpisodeRefused) -> Response:
            headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
            return JSONResponse({"error": str(exc)}, status_code=exc.status, headers=headers)

        def guarded(
            handler: Callable[[Request, EpisodeSession], Awaitable[Response]],
        ) -> Callable[[Request], Awaitable[Response]]:
            async def endpoint(request: Request) -> Response:
                try:
                    session = self._session(
                        request.path_params["episode_id"], request.headers.get("authorization")
                    )
                    return await handler(request, session)
                except EpisodeRefused as exc:
                    return refused(exc)

            return endpoint

        async def actions(_request: Request, session: EpisodeSession) -> Response:
            return JSONResponse(
                {"actions": [item.model_dump(mode="json") for item in session.actions.values()]}
            )

        async def act(request: Request, session: EpisodeSession) -> Response:
            arguments = await _json_body(request, MAX_ACTION_BYTES)
            if not isinstance(arguments, dict):
                raise EpisodeRefused(422, "An action takes a JSON object of its arguments.")
            reply = await session.call(request.path_params["name"], arguments)
            return JSONResponse(
                {"observation": reply.get("observation"), "done": bool(reply.get("done"))}
            )

        async def files(_request: Request, session: EpisodeSession) -> Response:
            return JSONResponse(
                {
                    "files": [
                        {"path": path, "size": len(data), "content_type": content_type_for(path)}
                        for path, data in sorted(session.files.items())
                    ]
                }
            )

        async def file(request: Request, session: EpisodeSession) -> Response:
            path = request.path_params["path"]
            data = session.files.get(path)
            if data is None:
                raise EpisodeRefused(404, f"There is no file {path!r}.")
            return Response(
                data,
                media_type=content_type_for(path),
                headers={
                    "Content-Disposition": "attachment",
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "no-store",
                },
            )

        async def trace(request: Request, session: EpisodeSession) -> Response:
            if session.finished.done():
                raise EpisodeRefused(409, "Report the trace before finishing the episode.")
            body = await _read(request, MAX_TRACE_BYTES)
            try:
                document = json.loads(body)
            except ValueError:
                raise EpisodeRefused(422, "The trace must be an ATIF JSON document.") from None
            problems = validate_atif(document)
            if problems:
                raise EpisodeRefused(422, "The trace is not valid ATIF: " + "; ".join(problems[:5]))
            session.trace = body
            return JSONResponse({"stored": True})

        async def finish(request: Request, session: EpisodeSession) -> Response:
            payload = await _json_body(request, MAX_FINISH_BYTES)
            if not isinstance(payload, dict) or "response" not in payload:
                raise EpisodeRefused(422, 'Finish with {"response": ...}.')
            if not session.finish(payload["response"]):
                raise EpisodeRefused(409, "The episode is already finished.")
            return JSONResponse({"finished": True})

        async def mcp(scope: Any, receive: Any, send: Any) -> None:
            request = Request(scope, receive)
            try:
                session = self._session(
                    scope["path_params"]["episode_id"], request.headers.get("authorization")
                )
            except EpisodeRefused as exc:
                await refused(exc)(scope, receive, send)
                return
            await session.mcp[0](scope, receive, send)

        prefix = "/episodes/{episode_id}"
        return Starlette(
            routes=[
                Route(f"{prefix}/actions", guarded(actions), methods=["GET"]),
                Route(f"{prefix}/actions/{{name}}", guarded(act), methods=["POST"]),
                Route(f"{prefix}/files", guarded(files), methods=["GET"]),
                Route(f"{prefix}/files/{{path:path}}", guarded(file), methods=["GET"]),
                Route(f"{prefix}/trace", guarded(trace), methods=["POST"]),
                Route(f"{prefix}/finish", guarded(finish), methods=["POST"]),
                Mount(f"{prefix}/mcp", app=mcp),
            ]
        )


async def _read(request: Any, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise EpisodeRefused(413, f"The request may be at most {limit // (1024 * 1024)} MiB.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise EpisodeRefused(413, f"The request may be at most {limit // (1024 * 1024)} MiB.")
    return bytes(body)


async def _json_body(request: Any, limit: int) -> Any:
    body = await _read(request, limit)
    try:
        return json.loads(body) if body else {}
    except ValueError:
        raise EpisodeRefused(422, "The request body must be JSON.") from None


def _text(observation: Any) -> str:
    return observation if isinstance(observation, str) else json.dumps(observation, default=str)


__all__ = [
    "EpisodeRefused",
    "EpisodeServer",
    "EpisodeServerOptions",
    "EpisodeSession",
]
