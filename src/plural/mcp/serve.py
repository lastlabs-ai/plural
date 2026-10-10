"""Start an App's FastMCP server: ``python -m plural.mcp.serve server.py:mcp``.

A Trial talks to the server over stdin and stdout, so it opens no port and
concurrent Trials never collide. ``--http`` serves it over Streamable HTTP
instead, at ``http://127.0.0.1:3825/mcp`` unless ``--port`` says otherwise, to
try it in any MCP client. The reference is ``file.py:name`` for a file in the Environment folder, or
``package.module:name`` for an installed server such as
``plural.mcp.files:server``. ``name`` is a FastMCP server, or a function
that returns one.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from plural.mcp import PORT


def load_server(reference: str, root: Path | None = None) -> Any:
    """Import the server a reference names.

    Returns:
        The FastMCP server.

    Raises:
        ValueError: When the reference is malformed or names nothing.
    """
    location, separator, attribute = reference.partition(":")
    if not separator or not location or not attribute:
        raise ValueError(
            f"server {reference!r} must be file.py:name or package.module:name, "
            "such as server.py:mcp"
        )
    if location.endswith(".py"):
        path = ((root or Path.cwd()) / location).resolve()
        if not path.is_file():
            raise ValueError(f"server file {location} does not exist in {root or Path.cwd()}")
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot import {location}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(location)
    server = getattr(module, attribute, None)
    if server is None:
        raise ValueError(f"{location} has no {attribute}")
    if callable(server) and not hasattr(server, "run"):
        server = server()
    if not hasattr(server, "run"):
        raise ValueError(f"{reference} is not a FastMCP server")
    return server


def serve_http(server: Any, port: int = PORT) -> None:
    """Serve a FastMCP server over Streamable HTTP on this machine only."""
    server.run(transport="http", host="127.0.0.1", port=port, path="/mcp", show_banner=False)


def _load(reference: str, root: Path | None = None) -> Any:
    try:
        return load_server(reference, root)
    except ModuleNotFoundError as exc:
        if exc.name == "fastmcp":
            raise SystemExit(
                "This App's server uses FastMCP. Install it with: pip install 'plural[mcp]'"
            ) from None
        raise


def main(argv: list[str] | None = None) -> None:
    """Run the named server on stdin and stdout, or over HTTP with ``--http``."""
    args = list(sys.argv[1:] if argv is None else argv)
    http = "--http" in args
    if http:
        args.remove("--http")
    port = PORT
    if "--port" in args:
        at = args.index("--port")
        try:
            port = int(args[at + 1])
        except (IndexError, ValueError):
            raise SystemExit("--port needs a number, such as --port 3825") from None
        del args[at : at + 2]
    if len(args) != 1:
        raise SystemExit("usage: python -m plural.mcp.serve file.py:name [--http [--port N]]")
    server = _load(args[0])
    if http:
        serve_http(server, port)
    else:
        server.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
