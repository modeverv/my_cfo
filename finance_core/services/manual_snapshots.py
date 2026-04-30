from __future__ import annotations

import sqlite3
from typing import Any

from finance_core.services.snapshots import get_latest_snapshot, insert_snapshot


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


def cash_in(conn: sqlite3.Connection, amount: int, memo: str) -> dict[str, Any]:
    latest = get_latest_snapshot(conn)
    new_wallet = latest["wallet_total"] + amount
    conn.execute(
        """
        INSERT INTO wallet_transactions (occurred_on, direction, amount, description)
        VALUES (date('now', 'localtime'), 'in', ?, ?)
        """,
        (amount, memo),
    )
    return insert_snapshot(conn, wallet_total=new_wallet, memo=f"cash-in: {memo}")


def cash_out(conn: sqlite3.Connection, amount: int, memo: str) -> dict[str, Any]:
    latest = get_latest_snapshot(conn)
    new_wallet = latest["wallet_total"] - amount
    if new_wallet < 0:
        raise ValueError(f"財布残高が不足しています (現在: {latest['wallet_total']:,}円)")
    conn.execute(
        """
        INSERT INTO wallet_transactions (occurred_on, direction, amount, description)
        VALUES (date('now', 'localtime'), 'out', ?, ?)
        """,
        (amount, memo),
    )
    return insert_snapshot(conn, wallet_total=new_wallet, memo=f"cash-out: {memo}")
