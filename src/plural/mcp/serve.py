"""Start an App's FastMCP server over stdio: ``python -m plural.mcp.serve server.py:mcp``.

The reference is ``file.py:name`` for a file in the Environment folder, or
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


def main(argv: list[str] | None = None) -> None:
    """Run the named server on stdin and stdout."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m plural.mcp.serve file.py:name")
    try:
        server = load_server(args[0])
    except ModuleNotFoundError as exc:
        if exc.name == "fastmcp":
            raise SystemExit(
                "This App's server uses FastMCP. Install it with: pip install 'plural[mcp]'"
            ) from None
        raise
    server.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
