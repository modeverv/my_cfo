from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "finance.sqlite3"
MIGRATION_PATH = PROJECT_ROOT / "migrations" / "001_init.sql"


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    with connect(db_path) as conn:
        conn.executescript(migration_sql)
