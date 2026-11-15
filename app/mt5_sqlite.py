import os
import re
import sqlite3
import json

from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent

DB_PATH = Path(
    os.getenv(
        "MT5_SQLITE_DB",
        str(PROJECT_DIR / "data" / "mt5_market.sqlite3"),
    )
)

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")

SUPPORTED_TYPES = {
    "TEXT",
    "INTEGER",
    "REAL",
    "NUMERIC",
    "BLOB",
}


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")

    return conn

def _ensure_operation_table(conn):

    conn.execute("""
        CREATE TABLE IF NOT EXISTS mt5_operation_results (
            execution_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

def _record_operation(conn, execution_id, command, response):
    _ensure_operation_table(conn)

    result_json = json.dumps(
        response,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    created_at = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO mt5_operation_results (
            execution_id,
            command,
            result_json,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            execution_id,
            command,
            result_json,
            created_at,
        ),
    )
    
def _validate_identifier(value):
    if not isinstance(value, str):
        raise ValueError("Identifier must be a string.")

    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid identifier: {value}")

    return value


def _get_table_columns(conn, table):
    table = _validate_identifier(table)

    rows = conn.execute(
        f"PRAGMA table_info('{table}')"
    ).fetchall()

    if not rows:
        raise ValueError(f"Table does not exist: {table}")

    return {
        row["name"]: row
        for row in rows
    }


def _make(payload, conn=None):
    table = _validate_identifier(payload.get("table"))

    columns = payload.get("columns")

    if not isinstance(columns, list) or not columns:
        raise ValueError(
            "MAKE requires a non-empty columns array."
        )

    definitions = [
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT'
    ]

    column_names = set()

    for column in columns:
        if not isinstance(column, dict):
            raise ValueError("Each column must be an object.")

        name = _validate_identifier(column.get("name"))

        if name.lower() == "id":
            raise ValueError("The id column is managed automatically.")

        if name in column_names:
            raise ValueError(f"Duplicate column: {name}")

        column_names.add(name)

        column_type = str(column.get("type", "")).upper()

        if column_type not in SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported SQLite type: {column_type}"
            )

        definition = f'"{name}" {column_type}'

        if column.get("not_null", False):
            definition += " NOT NULL"

        definitions.append(definition)

    unique_groups = payload.get("unique", [])

    if not isinstance(unique_groups, list):
        raise ValueError("unique must be an array.")

    for group in unique_groups:
        if not isinstance(group, list) or not group:
            raise ValueError("Each unique group must be a non-empty array.")

        validated = []

        for name in group:
            name = _validate_identifier(name)

            if name not in column_names:
                raise ValueError(
                    f"Unknown column in unique constraint: {name}"
                )

            validated.append(f'"{name}"')

        definitions.append(
            "UNIQUE (" + ", ".join(validated) + ")"
        )

    sql = (
        f'CREATE TABLE "{table}" ('
        + ", ".join(definitions)
        + ")"
    )

    if conn is None:
        with _connect() as conn:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            conn.execute(sql)
    else:
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(sql)

    return {
        "table": table,
        "columns": ["id"] + list(column_names),
        "recreated": True,
    }



def _insert(payload, conn=None):
    table = _validate_identifier(payload.get("table"))
    values = payload.get("values")

    if not isinstance(values, dict) or not values:
        raise ValueError(
            "INSR requires a non-empty values object."
        )

    def _run(connection):
        columns = _get_table_columns(connection, table)

        for name in values:
            _validate_identifier(name)

            if name not in columns:
                raise ValueError(
                    f"Unknown column '{name}' in table '{table}'."
                )

        if "id" in values:
            raise ValueError("The id column cannot be inserted manually.")

        names = list(values.keys())

        quoted_names = ", ".join(
            f'"{name}"' for name in names
        )

        placeholders = ", ".join(
            "?" for _ in names
        )

        sql = (
            f'INSERT INTO "{table}" ({quoted_names}) '
            f"VALUES ({placeholders})"
        )

        cursor = connection.execute(
            sql,
            [values[name] for name in names],
        )

        return cursor.lastrowid

    if conn is None:
        with _connect() as connection:
            inserted_id = _run(connection)
    else:
        inserted_id = _run(conn)

    return {
        "table": table,
        "inserted_id": inserted_id,
    }



def _select_all(payload, conn=None):
    table = _validate_identifier(payload.get("table"))

    limit = payload.get("limit", 100)

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer.")

    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000.")

    def _run(connection):
        _get_table_columns(connection, table)

        rows = connection.execute(
            f'SELECT * FROM "{table}" ORDER BY "id" ASC LIMIT ?',
            (limit,),
        ).fetchall()

        return {
            "table": table,
            "count": len(rows),
            "records": [dict(row) for row in rows],
        }

    if conn is None:
        with _connect() as connection:
            return _run(connection)

    return _run(conn)



def _list_tables(conn=None):

    def _run(connection):
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        return {
            "tables": [row["name"] for row in rows],
            "count": len(rows),
        }

    if conn is None:
        with _connect() as connection:
            return _run(connection)

    return _run(conn)



def execute_command(payload, execution_id=None):
    if not isinstance(payload, dict):
        return {
            "success": False,
            "error": "Request body must be a JSON object.",
        }

    command = str(payload.get("command", "")).upper()

    handlers = {
        "MAKE": _make,
        "INSR": _insert,
        "SELA": _select_all,
        "LIST-TABL": lambda _, conn=None: _list_tables(conn=conn),
    }

    handler = handlers.get(command)

    if handler is None:
        return {
            "success": False,
            "command": command,
            "error": f"Unsupported command: {command}",
        }

    if execution_id is None:
        try:
            result = handler(payload)

            return {
                "success": True,
                "command": command,
                "result": result,
            }

        except (ValueError, sqlite3.Error) as exc:
            return {
                "success": False,
                "command": command,
                "error": str(exc),
            }

    if not isinstance(execution_id, str) or not execution_id.strip():
        return {
            "success": False,
            "command": command,
            "error": "execution_id must be a non-empty string.",
        }

    try:
        with _connect() as conn:
            _ensure_operation_table(conn)

            existing = conn.execute(
                """
                SELECT command, result_json
                FROM mt5_operation_results
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()

            if existing is not None:
                if existing["command"] != command:
                    raise ValueError(
                        "execution_id already exists for another command."
                    )

                return json.loads(existing["result_json"])

            try:
                result = handler(payload, conn=conn)

                response = {
                    "success": True,
                    "command": command,
                    "result": result,
                }

            except (ValueError, sqlite3.Error) as exc:
                response = {
                    "success": False,
                    "command": command,
                    "error": str(exc),
                }

            _record_operation(
                conn,
                execution_id,
                command,
                response,
            )

            return response

    except (ValueError, sqlite3.Error) as exc:
        return {
            "success": False,
            "command": command,
            "error": str(exc),
        }
