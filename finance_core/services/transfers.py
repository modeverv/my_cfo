from __future__ import annotations

import sqlite3
from typing import Any

from finance_core.services.snapshots import get_latest_snapshot, insert_snapshot


ACCOUNT_ALIASES: dict[str, str] = {
    "bank": "bank",
    "wallet": "wallet",
    "securities": "securities",
    "card": "card",
    # フルキーも受け付ける
    "bank_main": "bank",
    "wallet_main": "wallet",
    "sbi_main": "securities",
    "card_main": "card",
}


def resolve_account(key: str) -> str:
    normalized = ACCOUNT_ALIASES.get(key.lower())
    if normalized is None:
        raise ValueError(
            f"不明な口座キー: {key}  (使用可能: bank, wallet, securities, card)"
        )
    return normalized


def transfer(
    conn: sqlite3.Connection,
    from_key: str,
    to_key: str,
    amount: int,
    memo: str | None = None,
) -> dict[str, Any]:
    from_account = resolve_account(from_key)
    to_account = resolve_account(to_key)

    if amount <= 0:
        raise ValueError("振替金額は1円以上で指定してください")
    if from_account == to_account:
        raise ValueError("振替元と振替先が同じ口座です")

    latest = get_latest_snapshot(conn)
    snapshot_kwargs: dict[str, int] = {}

    if from_account == "bank" and to_account == "wallet":
        _ensure_sufficient_balance(latest["bank_total"], amount, "銀行残高")
        snapshot_kwargs["bank_total"] = latest["bank_total"] - amount
        snapshot_kwargs["wallet_total"] = latest["wallet_total"] + amount

    elif from_account == "wallet" and to_account == "bank":
        new_wallet = latest["wallet_total"] - amount
        _ensure_sufficient_balance(latest["wallet_total"], amount, "財布残高")
        snapshot_kwargs["wallet_total"] = new_wallet
        snapshot_kwargs["bank_total"] = latest["bank_total"] + amount

    elif from_account == "bank" and to_account == "securities":
        _ensure_sufficient_balance(latest["bank_total"], amount, "銀行残高")
        snapshot_kwargs["bank_total"] = latest["bank_total"] - amount
        snapshot_kwargs["securities_total"] = latest["securities_total"] + amount

    elif from_account == "securities" and to_account == "bank":
        _ensure_sufficient_balance(latest["securities_total"], amount, "証券評価額")
        snapshot_kwargs["securities_total"] = latest["securities_total"] - amount
        snapshot_kwargs["bank_total"] = latest["bank_total"] + amount

    else:
        raise ValueError(
            f"未対応の振替組み合わせです: {from_account} → {to_account}"
        )

    cur = conn.execute(
        """
        INSERT INTO transfers (occurred_on, from_account, to_account, amount, memo)
        VALUES (date('now', 'localtime'), ?, ?, ?, ?)
        """,
        (from_account, to_account, amount, memo),
    )
    transfer_id = cur.lastrowid
    transfer_memo = f"transfer {from_account}→{to_account}" + (f": {memo}" if memo else "")
    snapshot = insert_snapshot(conn, memo=transfer_memo, **snapshot_kwargs)
    return {"transfer_id": transfer_id, "snapshot": snapshot}


def _ensure_sufficient_balance(current: int, amount: int, label: str) -> None:
    if current - amount < 0:
        raise ValueError(f"{label}が不足しています (現在: {current:,}円)")
