from __future__ import annotations

import sqlite3
from typing import Any

from finance_core.services.snapshots import get_latest_snapshot, insert_snapshot


def set_bank_total(conn: sqlite3.Connection, amount: int) -> dict[str, Any]:
    return insert_snapshot(conn, bank_total=amount, memo="set-bank")


def set_securities_total(conn: sqlite3.Connection, amount: int) -> dict[str, Any]:
    return insert_snapshot(conn, securities_total=amount, memo="set-securities")


def set_wallet_total(conn: sqlite3.Connection, amount: int) -> dict[str, Any]:
    latest = get_latest_snapshot(conn)
    description = f"cash-set: {latest['wallet_total']:,}円 -> {amount:,}円"
    conn.execute(
        """
        INSERT INTO wallet_transactions (occurred_on, direction, amount, balance_after, description)
        VALUES (date('now', 'localtime'), 'set', ?, ?, ?)
        """,
        (amount, amount, description),
    )
    return insert_snapshot(conn, wallet_total=amount, memo="cash-set")


def cash_add(conn: sqlite3.Connection, amount: int, memo: str) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("現金追加額は1円以上で指定してください")
    latest = get_latest_snapshot(conn)
    new_wallet = latest["wallet_total"] + amount
    conn.execute(
        """
        INSERT INTO wallet_transactions (occurred_on, direction, amount, balance_after, description)
        VALUES (date('now', 'localtime'), 'in', ?, ?, ?)
        """,
        (amount, new_wallet, memo),
    )
    return insert_snapshot(conn, wallet_total=new_wallet, memo=f"cash-in: {memo}")


def cash_in(conn: sqlite3.Connection, amount: int, memo: str) -> dict[str, Any]:
    return cash_add(conn, amount, memo)


def cash_out(conn: sqlite3.Connection, amount: int, memo: str) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("支出額は1円以上で指定してください")
    latest = get_latest_snapshot(conn)
    new_wallet = latest["wallet_total"] - amount
    if new_wallet < 0:
        raise ValueError(f"財布残高が不足しています (現在: {latest['wallet_total']:,}円)")
    conn.execute(
        """
        INSERT INTO wallet_transactions (occurred_on, direction, amount, balance_after, description)
        VALUES (date('now', 'localtime'), 'out', ?, ?, ?)
        """,
        (amount, new_wallet, memo),
    )
    return insert_snapshot(conn, wallet_total=new_wallet, memo=f"cash-out: {memo}")
