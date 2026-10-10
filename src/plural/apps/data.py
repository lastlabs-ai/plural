"""Give the Agent data that has no API, through generated actions.

A data App loads tables from a SQLite database or from CSV, JSON, or JSONL
files into a private working copy at the start of each episode, so the
source files never change. For each table ``t`` it offers:

- ``list_t(where, limit, offset)`` and ``get_t(<key>)``, which are read-only,
- ``create_t``, ``update_t``, and ``delete_t``, unless the table is read-only,
- and, with ``sql=True``, one read-only ``query(sql)`` action.

A Task seeds it through ``initial_state``, mapping a table name to the rows it
should start with. Its snapshot is every table's rows, so a Verifier can check
exactly what changed.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from plural.apps.base import App
from plural.apps.definition import AppAction, SecretReference
from plural.environments.types import State

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JSON_TYPES = {"INTEGER": "integer", "REAL": "number", "TEXT": "string", "BLOB": "string"}


def _quote(name: str) -> str:
    if _IDENTIFIER.fullmatch(name) is None:
        raise ValueError(f"{name!r} is not a usable table or column name")
    return f'"{name}"'


def _infer(values: Iterable[Any]) -> str:
    kind = "INTEGER"
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            continue
        if isinstance(value, float):
            kind = "REAL"
            continue
        if isinstance(value, (dict, list)):
            return "TEXT"
        text = str(value)
        try:
            int(text)
            continue
        except ValueError:
            pass
        try:
            float(text)
            kind = "REAL"
        except ValueError:
            return "TEXT"
    return kind


def _read_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".csv":
        return [dict(row) for row in csv.DictReader(text.splitlines())]
    if suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if suffix == ".json":
        loaded = json.loads(text)
        if isinstance(loaded, list) and all(isinstance(item, dict) for item in loaded):
            return loaded
        raise ValueError(f"{path} must hold a JSON list of objects")
    raise ValueError(f"{path}: use a .csv, .json, or .jsonl file for a data App table")


def _coerce(value: Any, kind: str) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if kind == "INTEGER":
        return int(value) if not isinstance(value, bool) else int(value)
    if kind == "REAL":
        return float(value)
    return str(value)


class DataApp(App[State]):
    """An App over tables of data, with generated query and change actions.

    Settings:
        database: A SQLite file in the Environment folder.
        tables: Table name to a ``.csv``, ``.json``, or ``.jsonl`` file in the
            Environment folder. Use this or ``database``, or both.
        keys: Table name to its key column. Default: ``id`` when the table has
            one, else the row number.
        read_only: Tables the Agent may read but not change, or ``True`` for all.
        sql: Also offer a read-only ``query(sql)`` action.
        page_size: The most rows one ``list`` action returns.
    """

    kind = "data"
    snapshot_on_step = False

    def __init__(
        self,
        *,
        name: str | None = None,
        database: str | None = None,
        tables: Mapping[str, str] | None = None,
        keys: Mapping[str, str] | None = None,
        read_only: bool | Sequence[str] = (),
        sql: bool = False,
        page_size: int = 50,
        secrets: Iterable[str | SecretReference] | None = None,
        credentials: Iterable[str | SecretReference] | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(
            name=name or type(self).name or None,
            description=description,
            secrets=secrets,
            credentials=credentials,
        )
        if database is None and not tables:
            raise ValueError(f"Data App {self.name!r} needs database or tables")
        self.database = database
        self.table_files = dict(tables or {})
        for table in self.table_files:
            _quote(table)
        self.keys = dict(keys or {})
        self.read_only = read_only
        self.sql = sql
        self.page_size = page_size
        self._folder: Path | None = None
        self._connection: sqlite3.Connection | None = None
        self._columns: dict[str, dict[str, str]] | None = None

    # Loading.

    def _path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.workspace / path

    def _build(self, target: Path) -> sqlite3.Connection:
        if self.database:
            source = self._path(self.database)
            if not source.is_file():
                raise ValueError(f"Data App {self.name!r}: {source} does not exist")
            shutil.copyfile(source, target)
        connection = sqlite3.connect(target, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        for table, file in self.table_files.items():
            rows = _read_rows(self._path(file))
            columns: list[str] = []
            for row in rows:
                columns.extend(key for key in row if key not in columns)
            if not columns:
                raise ValueError(f"Data App {self.name!r}: {file} has no columns")
            kinds = {column: _infer(row.get(column) for row in rows) for column in columns}
            key = self.keys.get(table) or ("id" if "id" in columns else None)
            definitions = ", ".join(
                f"{_quote(column)} {kinds[column]}" + (" PRIMARY KEY" if column == key else "")
                for column in columns
            )
            connection.execute(f"DROP TABLE IF EXISTS {_quote(table)}")
            connection.execute(f"CREATE TABLE {_quote(table)} ({definitions})")
            self._insert(connection, table, rows, kinds)
        connection.commit()
        return connection

    def _insert(
        self,
        connection: sqlite3.Connection,
        table: str,
        rows: Sequence[Mapping[str, Any]],
        kinds: Mapping[str, str],
    ) -> None:
        for row in rows:
            unknown = [column for column in row if column not in kinds]
            if unknown:
                raise ValueError(f"{table} has no column {', '.join(unknown)}")
            columns = list(row)
            if not columns:
                connection.execute(f"INSERT INTO {_quote(table)} DEFAULT VALUES")
                continue
            connection.execute(
                f"INSERT INTO {_quote(table)} ({', '.join(_quote(c) for c in columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [_coerce(row[column], kinds[column]) for column in columns],
            )

    def _schema(self) -> dict[str, dict[str, str]]:
        """Each table's columns and their SQLite types, read from the source.

        Returns:
            Table name to column name to type.
        """
        if self._columns is None:
            with tempfile.TemporaryDirectory(prefix="plural-data-") as folder:
                connection = self._build(Path(folder) / "schema.sqlite")
                try:
                    self._columns = self._read_schema(connection)
                finally:
                    connection.close()
        return self._columns

    @staticmethod
    def _read_schema(connection: sqlite3.Connection) -> dict[str, dict[str, str]]:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        schema: dict[str, dict[str, str]] = {}
        for table in tables:
            if _IDENTIFIER.fullmatch(table) is None:
                continue
            columns = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
            schema[table] = {
                str(column[1]): (str(column[2]).upper() or "TEXT")
                for column in columns
                if _IDENTIFIER.fullmatch(str(column[1]))
            }
        return schema

    def _key(self, table: str) -> str:
        columns = self._schema()[table]
        return self.keys.get(table) or ("id" if "id" in columns else "rowid")

    def _key_sql(self, table: str) -> str:
        key = self._key(table)
        # A quoted name that matches no column is a string literal in SQLite.
        return key if key == "rowid" else _quote(key)

    def _writable(self, table: str) -> bool:
        if self.read_only is True:
            return False
        if self.read_only is False:
            return True
        return table not in set(self.read_only)

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            self.reset({})
        assert self._connection is not None
        return self._connection

    # Actions.

    def actions(self) -> tuple[AppAction, ...]:
        """Generated actions for every table.

        Returns:
            List, get, and, for writable tables, create, update, and delete.
        """
        actions: list[AppAction] = []
        for table, columns in self._schema().items():
            key = self._key(table)
            column_schema = {
                column: {"type": [_JSON_TYPES.get(kind, "string"), "null"]}
                for column, kind in columns.items()
            }
            key_schema = {"type": _JSON_TYPES.get(columns.get(key, "INTEGER"), "integer")}
            listed = ", ".join(columns)
            actions.append(
                AppAction(
                    name=f"list_{table}"[:64],
                    description=f"List rows of {table} ({listed}). "
                    "where filters on exact column values.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "where": {
                                "type": "object",
                                "properties": column_schema,
                                "additionalProperties": False,
                            },
                            "limit": {"type": "integer", "minimum": 1},
                            "offset": {"type": "integer", "minimum": 0},
                        },
                    },
                    mutates_state=False,
                    binding={"table": table, "operation": "list"},
                )
            )
            actions.append(
                AppAction(
                    name=f"get_{table}"[:64],
                    description=f"Get one row of {table} by {key}.",
                    parameters={
                        "type": "object",
                        "properties": {key: key_schema},
                        "required": [key],
                    },
                    mutates_state=False,
                    binding={"table": table, "operation": "get"},
                )
            )
            if not self._writable(table):
                continue
            editable = {name: value for name, value in column_schema.items() if name != "rowid"}
            actions.extend(
                (
                    AppAction(
                        name=f"create_{table}"[:64],
                        description=f"Add a row to {table}.",
                        parameters={
                            "type": "object",
                            "properties": editable,
                            "additionalProperties": False,
                        },
                        binding={"table": table, "operation": "create"},
                    ),
                    AppAction(
                        name=f"update_{table}"[:64],
                        description=f"Change columns of one row of {table}, found by {key}.",
                        parameters={
                            "type": "object",
                            "properties": {
                                key: key_schema,
                                "values": {
                                    "type": "object",
                                    "properties": editable,
                                    "additionalProperties": False,
                                },
                            },
                            "required": [key, "values"],
                        },
                        binding={"table": table, "operation": "update"},
                    ),
                    AppAction(
                        name=f"delete_{table}"[:64],
                        description=f"Delete one row of {table}, found by {key}.",
                        parameters={
                            "type": "object",
                            "properties": {key: key_schema},
                            "required": [key],
                        },
                        binding={"table": table, "operation": "delete"},
                    ),
                )
            )
        if self.sql:
            actions.append(
                AppAction(
                    name="query",
                    description="Run one read-only SQLite SELECT statement. Tables: "
                    + ", ".join(self._schema()),
                    parameters={
                        "type": "object",
                        "properties": {"sql": {"type": "string"}},
                        "required": ["sql"],
                    },
                    mutates_state=False,
                    binding={"operation": "query"},
                )
            )
        return tuple(actions)

    def call(self, action: str, arguments: Mapping[str, Any]) -> Any:
        """Run one generated action.

        Returns:
            The rows read, or the row changed.

        Raises:
            ValueError: For bad arguments or a missing row; the Agent sees it.
        """
        declared = {item.name: item for item in self.actions()}
        spec = declared.get(action)
        if spec is None:
            raise ValueError(
                f"unknown action {action!r}; available actions: {', '.join(sorted(declared))}"
            )
        operation = spec.binding["operation"]
        values = dict(arguments)
        if operation == "query":
            return self._query(str(values.get("sql") or ""))
        table = str(spec.binding["table"])
        columns = self._schema()[table]
        key = self._key(table)
        connection = self._db()
        try:
            if operation == "list":
                return self._list(table, columns, values)
            if operation == "create":
                return self._create(table, values)
            if key not in values:
                raise ValueError(f"{action} needs {key}")
            identifier = values.pop(key)
            if operation == "get":
                return self._row(table, key, identifier)
            if operation == "delete":
                row = self._row(table, key, identifier)
                connection.execute(
                    f"DELETE FROM {_quote(table)} WHERE {self._key_sql(table)} = ?", [identifier]
                )
                connection.commit()
                return {"deleted": row}
            if operation == "update":
                changes = values.get("values")
                if not isinstance(changes, Mapping) or not changes:
                    raise ValueError(f"{action} needs values: the columns to change")
                self._row(table, key, identifier)
                unknown = [column for column in changes if column not in columns]
                if unknown:
                    raise ValueError(f"{table} has no column {', '.join(unknown)}")
                connection.execute(
                    f"UPDATE {_quote(table)} SET "
                    + ", ".join(f"{_quote(column)} = ?" for column in changes)
                    + f" WHERE {self._key_sql(table)} = ?",
                    [*(_coerce(changes[c], columns[c]) for c in changes), identifier],
                )
                connection.commit()
                return self._row(table, key, changes.get(key, identifier))
        except sqlite3.Error as exc:
            raise ValueError(f"{action} failed: {exc}") from exc
        raise ValueError(f"unknown data operation {operation!r}")

    def _create(self, table: str, values: Mapping[str, Any]) -> Any:
        columns = self._schema()[table]
        connection = self._db()
        self._insert(connection, table, [values], columns)
        connection.commit()
        identifier = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = connection.execute(
            f"SELECT * FROM {_quote(table)} WHERE rowid = ?", [identifier]
        ).fetchone()
        return dict(row) if row is not None else {}

    def _list(
        self, table: str, columns: Mapping[str, str], values: Mapping[str, Any]
    ) -> dict[str, Any]:
        where = values.get("where") or {}
        if not isinstance(where, Mapping):
            raise ValueError("where must be an object of column values")
        unknown = [column for column in where if column not in columns]
        if unknown:
            raise ValueError(f"{table} has no column {', '.join(unknown)}")
        limit = min(int(values.get("limit") or self.page_size), self.page_size)
        offset = int(values.get("offset") or 0)
        clause = " AND ".join(f"{_quote(column)} IS ?" for column in where)
        rows = self._db().execute(
            f"SELECT * FROM {_quote(table)}"
            + (f" WHERE {clause}" if clause else "")
            + f" ORDER BY {self._key_sql(table)} LIMIT ? OFFSET ?",
            [*(_coerce(where[c], columns[c]) for c in where), limit, offset],
        )
        found = [dict(row) for row in rows]
        return {"rows": found, "count": len(found), "offset": offset}

    def _row(self, table: str, key: str, identifier: Any) -> dict[str, Any]:
        row = (
            self._db()
            .execute(
                f"SELECT * FROM {_quote(table)} WHERE {self._key_sql(table)} = ?", [identifier]
            )
            .fetchone()
        )
        if row is None:
            raise ValueError(f"{table} has no row with {key} = {identifier!r}")
        return dict(row)

    def _query(self, statement: str) -> dict[str, Any]:
        if not statement.strip():
            raise ValueError("query needs sql")
        connection = self._db()
        connection.execute("PRAGMA query_only = ON")
        try:
            cursor = connection.execute(statement)
            rows = [dict(row) for row in cursor.fetchmany(self.page_size)]
        except sqlite3.Error as exc:
            raise ValueError(f"query failed: {exc}") from exc
        finally:
            connection.execute("PRAGMA query_only = OFF")
        return {"rows": rows, "count": len(rows)}

    # Lifecycle.

    def reset(self, initial_state: Mapping[str, Any]) -> Any:
        """Load a fresh working copy, then replace any tables the Task seeds.

        Returns:
            ``None``; the Agent starts from the Task's instructions.

        Raises:
            ValueError: When the initial state names an unknown table or column.
        """
        self.close()
        self._folder = Path(tempfile.mkdtemp(prefix="plural-data-"))
        self._connection = self._build(self._folder / "data.sqlite")
        schema = self._read_schema(self._connection)
        self._columns = schema
        for table, rows in dict(initial_state).items():
            if table not in schema:
                raise ValueError(f"Data App {self.name!r} has no table {table!r}")
            if not isinstance(rows, list):
                raise ValueError(f"initial state for {table!r} must be a list of rows")
            self._connection.execute(f"DELETE FROM {_quote(table)}")
            self._insert(self._connection, table, rows, schema[table])
        self._connection.commit()
        return None

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Every table's rows, in key order.

        Returns:
            Table name to rows.
        """
        connection = self._db()
        return {
            table: [
                dict(row)
                for row in connection.execute(
                    f"SELECT * FROM {_quote(table)} ORDER BY {self._key_sql(table)}"
                )
            ]
            for table in self._schema()
        }

    def close(self) -> None:
        """Close and delete the working copy."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._folder is not None:
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = None

    def _state_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                table: {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": f"Rows {table} starts with, replacing the source rows.",
                    "x-plural-initial": True,
                }
                for table in self._schema()
            },
            "additionalProperties": False,
        }


__all__ = ["DataApp"]
