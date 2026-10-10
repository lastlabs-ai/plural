"""A tiny MCP server for tests: an in-memory record store.

Run it over stdio (the default) or Streamable HTTP with ``--http PORT``. With
``--require-token NAME`` the HTTP server demands ``Authorization: Bearer
$NAME``. ``RECORDS_SEED`` (JSON list) preloads records. ``RECORDS_FILE`` makes
the store persist to that file, as many real servers do.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

RECORDS: dict[str, dict[str, Any]] = {}
for _item in json.loads(os.environ.get("RECORDS_SEED") or "[]"):
    RECORDS[str(_item["id"])] = _item
STORE = os.environ.get("RECORDS_FILE")
if STORE and os.path.exists(STORE):
    with open(STORE, encoding="utf-8") as _file:
        RECORDS.update(json.load(_file))

TOOLS = [
    {
        "name": "create_record",
        "description": "Create a record with a name.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "get_record",
        "description": "Read one record by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_records",
        "description": "List every record.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
        "outputSchema": {"type": "object"},
    },
]


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "create_record":
        ident = str(len(RECORDS) + 1)
        RECORDS[ident] = {"id": ident, "name": arguments["name"]}
        if STORE:
            with open(STORE, "w", encoding="utf-8") as file:
                json.dump(RECORDS, file)
        return {"content": [{"type": "text", "text": f"created record {ident}"}]}
    if name == "get_record":
        record = RECORDS.get(str(arguments.get("id")))
        if record is None:
            return {"content": [{"type": "text", "text": "no such record"}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(record)}]}
    if name == "list_records":
        records = list(RECORDS.values())
        return {
            "content": [{"type": "text", "text": json.dumps(records)}],
            "structuredContent": {"records": records},
        }
    raise KeyError(name)


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    ident = message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": message["params"]["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "records", "version": "1"},
        }
    elif method == "tools/list":
        cursor = (message.get("params") or {}).get("cursor")
        result = {"tools": TOOLS[2:]} if cursor else {"tools": TOOLS[:2], "nextCursor": "page2"}
    elif method == "tools/call":
        params = message["params"]
        try:
            result = call(params["name"], params.get("arguments") or {})
        except KeyError:
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "no tool"}}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "unknown"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def stdio() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        reply = handle(json.loads(line))
        if reply is not None:
            # A log notification first, which the client must skip.
            sys.stdout.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}})
                + "\n"
            )
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


def http(port: int, token_variable: str | None) -> None:
    session = uuid.uuid4().hex

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            return

        def do_DELETE(self) -> None:  # noqa: N802
            self.send_response(204)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if token_variable and self.headers.get("Authorization") != (
                f"Bearer {os.environ[token_variable]}"
            ):
                self.send_response(401)
                self.end_headers()
                return
            reply = handle(body)
            if reply is None:
                self.send_response(202)
                self.end_headers()
                return
            if body.get("method") != "initialize" and self.headers.get("Mcp-Session-Id") != session:
                self.send_response(400)
                self.end_headers()
                return
            payload = f"event: message\ndata: {json.dumps(reply)}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Mcp-Session-Id", session)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(sys.argv[sys.argv.index("--http") + 1])
        token = (
            sys.argv[sys.argv.index("--require-token") + 1]
            if "--require-token" in sys.argv
            else None
        )
        http(port, token)
    else:
        stdio()
