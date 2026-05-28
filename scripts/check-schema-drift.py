#!/usr/bin/env python3
"""Detect schema drift between SQLite schema file, runtime migrations, live DB, and MySQL mirror."""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQLITE_SCHEMA = ROOT / "backend" / "schema.sql"
MYSQL_SCHEMA = ROOT / "deploy" / "mysql" / "schema.sql"
SERVER_FILE = ROOT / "backend" / "server.py"
LIVE_DB = ROOT / "backend" / "data" / "device_safety.db"

TABLE_RE = re.compile(
    r"CREATE TABLE IF NOT EXISTS\s+([`a-zA-Z_][`a-zA-Z0-9_]*)\s*\((.*?)\)\s*[^;]*;",
    re.S,
)
ENSURE_RE = re.compile(
    r"ensure_column\(connection,\s*\"([a-zA-Z_][a-zA-Z0-9_]*)\",\s*\"([a-zA-Z_][a-zA-Z0-9_]*)\""
)


def parse_tables_with_columns(sql_text: str) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for table_name, body in TABLE_RE.findall(sql_text):
        table_name = table_name.strip("`")
        columns: list[str] = []
        for raw in body.splitlines():
            line = raw.strip().rstrip(",")
            if not line:
                continue
            upper = line.upper()
            if upper.startswith(("PRIMARY KEY", "FOREIGN KEY", "CONSTRAINT", "UNIQUE KEY", "UNIQUE ", "INDEX ")):
                continue
            if upper.startswith("KEY ") and "(" in line:
                continue
            col_name = line.split()[0].strip("`")
            if col_name.upper() in {"PRIMARY", "FOREIGN", "CONSTRAINT", "UNIQUE", "INDEX"}:
                continue
            columns.append(col_name)
        tables[table_name] = columns
    return tables


def parse_ensure_columns(py_text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for table_name, column_name in ENSURE_RE.findall(py_text):
        out.setdefault(table_name, set()).add(column_name)
    return out


def live_db_columns(db_path: Path) -> dict[str, list[str]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in cur.fetchall()]
        result: dict[str, list[str]] = {}
        for table in tables:
            cur.execute(f"PRAGMA table_info({table})")
            result[table] = [row[1] for row in cur.fetchall()]
        return result
    finally:
        conn.close()


def main() -> int:
    sqlite_schema = parse_tables_with_columns(SQLITE_SCHEMA.read_text(encoding="utf-8"))
    mysql_schema = parse_tables_with_columns(MYSQL_SCHEMA.read_text(encoding="utf-8"))
    ensure_columns = parse_ensure_columns(SERVER_FILE.read_text(encoding="utf-8"))
    live = live_db_columns(LIVE_DB)

    failures: list[str] = []

    for table_name, columns in ensure_columns.items():
        known = set(sqlite_schema.get(table_name, []))
        missing = sorted(col for col in columns if col not in known)
        if missing:
            failures.append(
                f"backend/schema.sql missing ensure_column fields for {table_name}: {', '.join(missing)}"
            )

    if live:
        for table_name, live_cols in sorted(live.items()):
            schema_cols = sqlite_schema.get(table_name)
            if schema_cols is None:
                failures.append(f"Live DB has table not defined in backend/schema.sql: {table_name}")
                continue
            schema_set = set(schema_cols)
            db_only = sorted(col for col in live_cols if col not in schema_set)
            if db_only:
                failures.append(
                    f"Live DB has extra columns not in backend/schema.sql for {table_name}: {', '.join(db_only)}"
                )

    sqlite_tables = set(sqlite_schema.keys())
    mysql_tables = set(mysql_schema.keys())
    mysql_missing_tables = sorted(sqlite_tables - mysql_tables)
    if mysql_missing_tables:
        failures.append(
            "deploy/mysql/schema.sql missing tables: " + ", ".join(mysql_missing_tables)
        )

    if failures:
        print("SCHEMA DRIFT FOUND:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Schema drift check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
