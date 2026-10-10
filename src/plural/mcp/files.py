"""A ready-made MCP server over a Trial's files: ``server: plural.mcp.files:server``.

It gives the Agent the Environment's and the Task's resources, read-only::

    environment-resources/   every Task's files, from environment.yaml
    task-resources/          this Task's own files, when it has any

Tools:

- ``list_files(path, recursive)`` and ``read_file(path, offset, limit)``,
- ``search_files(pattern, path, glob)``, a regular expression over text files,
- ``list_tables()`` and ``query(sql)``, read-only SQL over every CSV, JSON, JSONL,
  and SQLite file in both folders. A CSV, JSON, or JSONL file is a table named
  after the file; a SQLite file's tables are named ``<file>.<table>``.

``plural.mcp.files:writable`` also offers ``write_file(path, content)`` into a
third folder, ``scratch/``, which belongs to the Trial and is deleted when it
ends; its snapshot is every file written there, for Rewarders. The resource
folders are never changed.

To change what it offers, copy it into your Environment with
``plural mcp eject files ENVIRONMENT`` and edit it like any FastMCP server.
"""

from __future__ import annotations

import csv
import fnmatch
import io
import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

import plural.mcp

MAX_READ_BYTES = 5 * 1024 * 1024
MAX_TABLE_BYTES = 16 * 1024 * 1024
MAX_LISTED = 500
MAX_MATCHES = 100
MAX_ROWS = 200
SCRATCH = "scratch"
_TABLE_SUFFIXES = {".csv", ".json", ".jsonl"}
_DATABASE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]+")
_READ_ONLY_SQL = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}


def _folders(writable: bool) -> dict[str, Path]:
    folders = {plural.mcp.ENVIRONMENT_RESOURCES: plural.mcp.environment_resources()}
    task = plural.mcp.task_resources()
    if task is not None:
        folders[plural.mcp.TASK_RESOURCES] = task
    if writable:
        folders[SCRATCH] = plural.mcp.scratch()
    return folders


def _resolve(path: str, folders: dict[str, Path]) -> tuple[str, Path] | None:
    """Map a path the Agent gives to a real one, refusing anything outside the folders.

    Returns:
        The folder name and the real path, or ``None`` for the root.

    Raises:
        ValueError: For a path outside every folder.
    """
    parts = [part for part in path.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts:
        return None
    folder = folders.get(parts[0])
    if folder is None:
        raise ValueError(f"No folder {parts[0]!r}. Start with one of: {', '.join(folders)}")
    target = (folder / Path(*parts[1:])).resolve() if parts[1:] else folder.resolve()
    if not target.is_relative_to(folder.resolve()):
        raise ValueError(f"{path} is outside {parts[0]}")
    return parts[0], target


def _display(name: str, folder: Path, target: Path) -> str:
    relative = target.relative_to(folder.resolve()).as_posix()
    return name if relative == "." else f"{name}/{relative}"


def _walk(folder: Path) -> Iterator[Path]:
    for path in sorted(folder.rglob("*")):
        if any(part.startswith(".") for part in path.relative_to(folder).parts):
            continue
        yield path


def _infer(values: Iterable[Any]) -> str:
    kind = "INTEGER"
    for value in values:
        if value is None or value == "" or isinstance(value, bool):
            continue
        if isinstance(value, (dict, list)):
            return "TEXT"
        if isinstance(value, int):
            continue
        if isinstance(value, float):
            kind = "REAL"
            continue
        try:
            int(str(value))
            continue
        except ValueError:
            pass
        try:
            float(str(value))
            kind = "REAL"
        except ValueError:
            return "TEXT"
    return kind


def _rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    loaded = json.loads(text)
    if isinstance(loaded, list) and all(isinstance(item, dict) for item in loaded):
        return loaded
    raise ValueError("not a JSON list of objects")


def _read_only(action: int, first: str | None, *_: Any) -> int:
    if action in _READ_ONLY_SQL or (action == sqlite3.SQLITE_PRAGMA and first == "table_info"):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _identifier(name: str) -> str:
    cleaned = _IDENTIFIER.sub("_", name).strip("_") or "table"
    return f"t_{cleaned}" if cleaned[0].isdigit() else cleaned


class _Tables:
    """Every table file in the resource folders, loaded once into read-only SQLite."""

    def __init__(self, folders: dict[str, Path]) -> None:
        self.connection = sqlite3.connect("file::memory:", uri=True, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.sources: dict[str, str] = {}
        self.skipped: list[str] = []
        candidates: list[tuple[str, Path, Path]] = [
            (name, folder, path)
            for name, folder in folders.items()
            if name != SCRATCH and folder.is_dir()
            for path in _walk(folder)
            if path.is_file()
            and path.suffix.lower() in _TABLE_SUFFIXES | _DATABASE_SUFFIXES
            and path.stat().st_size <= MAX_TABLE_BYTES
        ]
        stems = [_identifier(path.stem) for _, _, path in candidates]
        for (name, folder, path), stem in zip(candidates, stems, strict=True):
            table = stem if stems.count(stem) == 1 else _identifier(f"{name}_{stem}")
            shown = _display(name, folder, path.resolve())
            try:
                if path.suffix.lower() in _DATABASE_SUFFIXES:
                    self.connection.execute(
                        "ATTACH DATABASE ? AS " + f'"{table}"', (f"file:{path}?mode=ro",)
                    )
                    for row in self.connection.execute(
                        f"SELECT name FROM \"{table}\".sqlite_master WHERE type = 'table'"
                    ):
                        self.sources[f"{table}.{row[0]}"] = shown
                else:
                    self._load(table, _rows(path))
                    self.sources[table] = shown
            except (ValueError, sqlite3.Error, UnicodeDecodeError) as exc:
                self.skipped.append(f"{shown}: {exc}")
        self.connection.set_authorizer(_read_only)

    def _load(self, table: str, rows: list[dict[str, Any]]) -> None:
        columns: list[str] = []
        for row in rows:
            columns.extend(key for key in row if key not in columns)
        if not columns:
            raise ValueError("no columns")
        kinds = {column: _infer(row.get(column) for row in rows) for column in columns}
        definitions = ", ".join(f'"{_identifier(column)}" {kinds[column]}' for column in columns)
        self.connection.execute(f'CREATE TABLE "{table}" ({definitions})')
        placeholders = ", ".join("?" for _ in columns)
        self.connection.executemany(
            f'INSERT INTO "{table}" VALUES ({placeholders})',
            [
                [
                    json.dumps(value) if isinstance(value, (dict, list)) else value
                    for value in (row.get(column) for column in columns)
                ]
                for row in rows
            ],
        )

    def describe(self) -> dict[str, Any]:
        tables = []
        for table, source in sorted(self.sources.items()):
            schema, _, name = table.rpartition(".")
            pragma = f'"{schema}".table_info("{name}")' if schema else f'table_info("{table}")'
            columns = [
                {"name": row[1], "type": row[2] or "TEXT"}
                for row in self.connection.execute(f"PRAGMA {pragma}")
            ]
            tables.append({"table": table, "file": source, "columns": columns})
        return {"tables": tables, "skipped": self.skipped}

    def query(self, sql: str) -> dict[str, Any]:
        try:
            cursor = self.connection.execute(sql)
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"query failed: {exc}. Only SELECT statements are allowed.") from exc
        columns = [item[0] for item in cursor.description or ()]
        rows = [dict(row) for row in cursor.fetchmany(MAX_ROWS + 1)]
        return {
            "columns": columns,
            "rows": rows[:MAX_ROWS],
            "truncated": len(rows) > MAX_ROWS,
        }


def build(*, writable: bool = False, name: str = "files") -> FastMCP:
    """The files server.

    Returns:
        A FastMCP server; with ``writable``, it also offers ``write_file`` into ``scratch/``.
    """
    mcp = FastMCP(name)
    tables: list[_Tables] = []

    def loaded() -> _Tables:
        if not tables:
            tables.append(_Tables(_folders(writable)))
        return tables[0]

    @mcp.tool(annotations={"readOnlyHint": True})
    def list_files(path: str = "", recursive: bool = False) -> str:
        """List files and folders. Start with no path to see the top-level folders.

        environment-resources/ holds files every task shares, task-resources/ this
        task's own files.
        """
        folders = _folders(writable)
        resolved = _resolve(path, folders)
        if resolved is None:
            return "\n".join(f"{item}/" for item in folders)
        name, target = resolved
        if target.is_file():
            return f"{path} ({target.stat().st_size} bytes)"
        if not target.is_dir():
            raise ValueError(f"No folder {path}")
        entries = _walk(target) if recursive else sorted(target.iterdir())
        lines = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            shown = _display(name, folders[name], entry.resolve())
            lines.append(
                f"{shown}/" if entry.is_dir() else f"{shown} ({entry.stat().st_size} bytes)"
            )
            if len(lines) >= MAX_LISTED:
                lines.append(f"… more than {MAX_LISTED} entries; list a subfolder")
                break
        return "\n".join(lines) or f"{path} is empty"

    @mcp.tool(annotations={"readOnlyHint": True})
    def read_file(path: str, offset: int = 1, limit: int = 400) -> str:
        """Read a text file, from line `offset` (1 is the first), at most `limit` lines."""
        resolved = _resolve(path, _folders(writable))
        if resolved is None or not resolved[1].is_file():
            raise ValueError(f"No file {path}. Use list_files to see what exists.")
        target = resolved[1]
        if target.stat().st_size > MAX_READ_BYTES:
            raise ValueError(f"{path} is too large to read; search it with search_files")
        data = target.read_bytes()
        if b"\0" in data[:8192]:
            raise ValueError(f"{path} is not a text file")
        lines = data.decode("utf-8", errors="replace").splitlines()
        start = max(offset, 1) - 1
        chosen = lines[start : start + max(limit, 1)]
        footer = (
            f"\n… lines {start + 1}-{start + len(chosen)} of {len(lines)}; "
            f"read on with offset={start + len(chosen) + 1}"
            if start + len(chosen) < len(lines)
            else ""
        )
        return "\n".join(chosen) + footer

    @mcp.tool(annotations={"readOnlyHint": True})
    def search_files(pattern: str, path: str = "", glob: str | None = None) -> str:
        """Find lines matching a regular expression in text files.

        `glob`, such as *.md, limits which files are searched.
        """
        try:
            expression = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid pattern: {exc}") from exc
        folders = _folders(writable)
        resolved = _resolve(path, folders)
        roots = (
            [(name, folder.resolve()) for name, folder in folders.items()]
            if resolved is None
            else [resolved]
        )
        matches: list[str] = []
        for name, root in roots:
            files = [root] if root.is_file() else [item for item in _walk(root) if item.is_file()]
            for file in files:
                if glob and not fnmatch.fnmatch(file.name, glob):
                    continue
                if file.stat().st_size > MAX_READ_BYTES:
                    continue
                data = file.read_bytes()
                if b"\0" in data[:8192]:
                    continue
                shown = _display(name, folders[name], file.resolve())
                for number, line in enumerate(
                    data.decode("utf-8", errors="replace").splitlines(), 1
                ):
                    if expression.search(line):
                        matches.append(f"{shown}:{number}: {line[:300]}")
                        if len(matches) >= MAX_MATCHES:
                            return "\n".join([*matches, f"… stopped at {MAX_MATCHES} matches"])
        return "\n".join(matches) or "No matches."

    @mcp.tool(annotations={"readOnlyHint": True})
    def list_tables() -> dict[str, Any]:
        """List the tables query can read: every CSV, JSON, JSONL, and SQLite file, with columns."""
        return loaded().describe()

    @mcp.tool(annotations={"readOnlyHint": True})
    def query(sql: str) -> dict[str, Any]:
        """Run one read-only SQL SELECT over the tables list_tables shows."""
        if not sql.strip():
            raise ValueError("query needs sql")
        return loaded().query(sql)

    if writable:

        @mcp.tool
        def write_file(path: str, content: str) -> str:
            """Write a text file under scratch/, replacing it if it exists."""
            folders = _folders(writable)
            resolved = _resolve(path, folders)
            if resolved is None or resolved[0] != SCRATCH:
                raise ValueError(
                    "Only scratch/ can be written; the resource folders are read-only."
                )
            target = resolved[1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Wrote {path} ({len(content.encode())} bytes)."

        @plural.mcp.snapshot(mcp)
        def written() -> dict[str, Any]:
            folder = plural.mcp.scratch()
            return {
                "scratch": {
                    item.relative_to(folder).as_posix(): item.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    for item in _walk(folder)
                    if item.is_file()
                }
            }

    return mcp


def server() -> FastMCP:
    """The read-only files server.

    Returns:
        The server.
    """
    return build()


def writable() -> FastMCP:
    """The files server that can also write to ``scratch/``.

    Returns:
        The server.
    """
    return build(writable=True)


__all__ = ["build", "server", "writable"]
