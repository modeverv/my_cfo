from __future__ import annotations

import sqlite3
from typing import Any

from finance_core.services.snapshots import get_latest_snapshot


def get_current_position(conn: sqlite3.Connection) -> dict[str, Any]:
    return get_latest_snapshot(conn)


def format_current_position(position: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"総資産:        {position['total_assets']:,}円",
            f"銀行残高:       {position['bank_total']:,}円",
            f"証券評価額:    {position['securities_total']:,}円",
            f"財布残高:          {position['wallet_total']:,}円",
            f"カード利用:      -{position['credit_card_unbilled']:,}円",
        ]
    )


def show_now(conn: sqlite3.Connection) -> str:
    return format_current_position(get_current_position(conn))


def show_wallet(conn: sqlite3.Connection, limit: int = 10) -> str:
    snapshot = get_latest_snapshot(conn)
    rows = conn.execute(
        """
        SELECT occurred_on, direction, amount, description
        FROM wallet_transactions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    lines = [f"財布残高: {snapshot['wallet_total']:,}円", ""]
    if rows:
        lines.append("最近の取引:")
        direction_label = {"in": "入金", "out": "支出", "set": "補正"}
        for row in rows:
            label = direction_label.get(row["direction"], row["direction"])
            desc = row["description"] or ""
            lines.append(f"  {row['occurred_on']}  {label}  {row['amount']:>10,}円  {desc}")
    else:
        lines.append("取引履歴がありません")

    return "\n".join(lines)
