from __future__ import annotations

import sqlite3
from typing import Any

from finance_core.services.snapshots import insert_snapshot


def set_bank_total(conn: sqlite3.Connection, amount: int) -> dict[str, Any]:
    return insert_snapshot(conn, bank_total=amount, memo="set-bank")


def set_securities_total(conn: sqlite3.Connection, amount: int) -> dict[str, Any]:
    return insert_snapshot(conn, securities_total=amount, memo="set-securities")


def set_wallet_total(conn: sqlite3.Connection, amount: int) -> dict[str, Any]:
    conn.execute(
        """
        INSERT INTO wallet_transactions (occurred_on, direction, amount, description)
        VALUES (date('now', 'localtime'), 'set', ?, ?)
        """,
        (amount, "cash-set"),
    )
    return insert_snapshot(conn, wallet_total=amount, memo="cash-set")
