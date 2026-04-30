from __future__ import annotations

import sqlite3
from typing import Any

from finance_core.display import fit
from finance_core.services.ask_context import current_month, get_card_month_summary
from finance_core.services.snapshots import get_latest_snapshot

_LABEL_COLS   = 13  # ラベル列の表示幅（最長「証券評価額:」= 11 + 余白2）
_AMOUNT_COLS  = 13  # 金額列の表示幅（右揃え）
_MERCHANT_COLS = 30 # 加盟店名列の表示幅


def get_current_position(conn: sqlite3.Connection) -> dict[str, Any]:
    return get_latest_snapshot(conn)


def format_current_position(position: dict[str, Any]) -> str:
    def row(label: str, amount: int) -> str:
        return f"{fit(label, _LABEL_COLS)}{amount:>{_AMOUNT_COLS},}円"

    return "\n".join([
        row("総資産:",      position["total_assets"]),
        row("銀行残高:",     position["bank_total"]),
        row("証券評価額:",   position["securities_total"]),
        row("財布残高:",     position["wallet_total"]),
        row("カード利用:",   -position["credit_card_unbilled"]),
    ])


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


def show_card(conn: sqlite3.Connection, month: str | None = None) -> str:
    target = month or current_month()
    summary = get_card_month_summary(conn, target)

    lines = [
        f"カード利用 {target} — {summary['count']}件  計 {summary['total']:,}円",
        "",
        "加盟店別TOP10:",
    ]
    for r in summary["by_merchant"]:
        lines.append(f"  {fit(str(r['merchant']), _MERCHANT_COLS)}  {r['total']:>10,}円")

    lines += ["", "高額TOP10:"]
    for r in summary["large_transactions"]:
        lines.append(f"  {r['used_on']}  {fit(str(r['merchant']), _MERCHANT_COLS)}  {r['amount']:>10,}円")

    return "\n".join(lines)
