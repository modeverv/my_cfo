from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any


SNAPSHOT_COLUMNS = (
    "id",
    "as_of_date",
    "bank_total",
    "securities_total",
    "wallet_total",
    "credit_card_unbilled",
    "total_assets",
    "memo",
)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def empty_snapshot() -> dict[str, Any]:
    return {
        "id": None,
        "as_of_date": date.today().isoformat(),
        "bank_total": 0,
        "securities_total": 0,
        "wallet_total": 0,
        "credit_card_unbilled": 0,
        "total_assets": 0,
        "memo": None,
    }


def calculate_total(
    bank_total: int,
    securities_total: int,
    wallet_total: int,
    credit_card_unbilled: int,
) -> int:
    return bank_total + securities_total + wallet_total - credit_card_unbilled


def get_latest_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, as_of_date, bank_total, securities_total, wallet_total,
               credit_card_unbilled, total_assets, memo
        FROM asset_snapshots
        ORDER BY as_of_date DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return row_to_dict(row) or empty_snapshot()


def insert_snapshot(
    conn: sqlite3.Connection,
    *,
    bank_total: int | None = None,
    securities_total: int | None = None,
    wallet_total: int | None = None,
    credit_card_unbilled: int | None = None,
    memo: str | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    latest = get_latest_snapshot(conn)
    new_snapshot = latest.copy()

    if bank_total is not None:
        new_snapshot["bank_total"] = bank_total
    if securities_total is not None:
        new_snapshot["securities_total"] = securities_total
    if wallet_total is not None:
        new_snapshot["wallet_total"] = wallet_total
    if credit_card_unbilled is not None:
        new_snapshot["credit_card_unbilled"] = credit_card_unbilled

    new_snapshot["as_of_date"] = as_of_date or date.today().isoformat()
    new_snapshot["memo"] = memo
    new_snapshot["total_assets"] = calculate_total(
        new_snapshot["bank_total"],
        new_snapshot["securities_total"],
        new_snapshot["wallet_total"],
        new_snapshot["credit_card_unbilled"],
    )

    cur = conn.execute(
        """
        INSERT INTO asset_snapshots (
          as_of_date, bank_total, securities_total, wallet_total,
          credit_card_unbilled, total_assets, memo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_snapshot["as_of_date"],
            new_snapshot["bank_total"],
            new_snapshot["securities_total"],
            new_snapshot["wallet_total"],
            new_snapshot["credit_card_unbilled"],
            new_snapshot["total_assets"],
            new_snapshot["memo"],
        ),
    )
    new_snapshot["id"] = cur.lastrowid
    return new_snapshot


def format_snapshot(snapshot: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"総資産:        {snapshot['total_assets']:,}円",
            f"銀行残高:       {snapshot['bank_total']:,}円",
            f"証券評価額:    {snapshot['securities_total']:,}円",
            f"財布残高:          {snapshot['wallet_total']:,}円",
            f"カード利用:      -{snapshot['credit_card_unbilled']:,}円",
        ]
    )
