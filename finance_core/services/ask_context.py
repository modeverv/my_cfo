from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from finance_core.services.snapshots import get_latest_snapshot


_CARD_PAYMENT_MONTH_EXPR = "COALESCE(payment_month, substr(used_on, 1, 7))"


def current_month(today: date | None = None) -> str:
    target = today or date.today()
    return target.strftime("%Y-%m")


def card_billing_month(today: date | None = None) -> str:
    """今月利用分の引き落とし月（翌月）を返す"""
    target = today or date.today()
    year = target.year
    month = target.month + 1
    if month == 13:
        year += 1
        month = 1
    return f"{year:04d}-{month:02d}"


def get_card_month_summary(conn: sqlite3.Connection, month: str) -> dict[str, Any]:
    agg = conn.execute(
        f"""
        SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total
        FROM card_transactions
        WHERE {_CARD_PAYMENT_MONTH_EXPR} = ?
        """,
        (month,),
    ).fetchone()

    by_merchant = conn.execute(
        f"""
        SELECT merchant, SUM(amount) AS total
        FROM card_transactions
        WHERE {_CARD_PAYMENT_MONTH_EXPR} = ?
        GROUP BY merchant
        ORDER BY total DESC
        LIMIT 10
        """,
        (month,),
    ).fetchall()

    large_transactions = conn.execute(
        f"""
        SELECT used_on, merchant, amount
        FROM card_transactions
        WHERE {_CARD_PAYMENT_MONTH_EXPR} = ?
        ORDER BY amount DESC, used_on DESC
        LIMIT 10
        """,
        (month,),
    ).fetchall()

    return {
        "month": month,
        "count": int(agg["count"]),
        "total": int(agg["total"]),
        "by_merchant": [
            {"merchant": row["merchant"], "total": int(row["total"])}
            for row in by_merchant
        ],
        "large_transactions": [
            {
                "used_on": row["used_on"],
                "merchant": row["merchant"],
                "amount": int(row["amount"]),
            }
            for row in large_transactions
        ],
    }


def get_wallet_month_summary(conn: sqlite3.Connection, month: str) -> dict[str, Any]:
    cash_out_total = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM wallet_transactions
        WHERE direction = 'out'
          AND substr(occurred_on, 1, 7) = ?
        """,
        (month,),
    ).fetchone()["total"]

    large_cash_out = conn.execute(
        """
        SELECT occurred_on, amount, description
        FROM wallet_transactions
        WHERE direction = 'out'
          AND substr(occurred_on, 1, 7) = ?
        ORDER BY amount DESC, occurred_on DESC
        LIMIT 10
        """,
        (month,),
    ).fetchall()

    return {
        "month": month,
        "cash_out_total": int(cash_out_total),
        "large_cash_out": [
            {
                "occurred_on": row["occurred_on"],
                "amount": int(row["amount"]),
                "description": row["description"] or "",
            }
            for row in large_cash_out
        ],
    }


def get_recent_transfers(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT occurred_on, from_account, to_account, amount, memo
        FROM transfers
        ORDER BY occurred_on DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    return [
        {
            "occurred_on": row["occurred_on"],
            "from_account": row["from_account"],
            "to_account": row["to_account"],
            "amount": int(row["amount"]),
            "memo": row["memo"] or "",
        }
        for row in rows
    ]


def refresh_card_unbilled(conn: sqlite3.Connection, month: str | None = None) -> dict:
    from finance_core.services.snapshots import insert_snapshot
    target = month or current_month()
    total = conn.execute(
        f"""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM card_transactions
        WHERE {_CARD_PAYMENT_MONTH_EXPR} = ?
        """,
        (target,),
    ).fetchone()["total"]
    return insert_snapshot(conn, credit_card_unbilled=int(total), memo=f"card refresh {target}")


def build_finance_context(conn: sqlite3.Connection, question: str) -> str:
    latest_snapshot = get_latest_snapshot(conn)
    usage_month = current_month()        # 今月の利用月（財布支出集計に使う）
    billing_month = card_billing_month() # 今月利用分の引き落とし月（翌月）
    prev_billing = usage_month           # 前月利用分の引き落とし月（今月）
    usage_month_wallet_summary = get_wallet_month_summary(conn, usage_month)
    usage_month_card_summary = get_card_month_summary(conn, billing_month)
    previous_billing_card_summary = get_card_month_summary(conn, prev_billing)
    transfers = get_recent_transfers(conn)

    return f"""## 現在の資産状況
総資産: {latest_snapshot['total_assets']}円
銀行残高: {latest_snapshot['bank_total']}円
証券評価額: {latest_snapshot['securities_total']}円
財布残高: {latest_snapshot['wallet_total']}円
カード未払い/今月利用: {latest_snapshot['credit_card_unbilled']}円

## 今月のカード利用（利用月: {usage_month} / 支払月: {billing_month}）
合計: {usage_month_card_summary['total']}円
加盟店別: {usage_month_card_summary['by_merchant']}
高額決済: {usage_month_card_summary['large_transactions']}

## 前月比較（支払月: {prev_billing}）
前月カード合計: {previous_billing_card_summary['total']}円
差額: {int(usage_month_card_summary['total']) - int(previous_billing_card_summary['total'])}円

## 今月の現金支出（{usage_month}）
財布支出合計: {usage_month_wallet_summary['cash_out_total']}円
主な現金支出: {usage_month_wallet_summary['large_cash_out']}

## 最近の振替
{transfers}

## 質問
{question}
"""


def build_ask_prompt(context: str, question: str) -> str:
    return f"""あなたは個人の財務管理を補助するアシスタントです。
以下のデータだけを根拠に回答してください。
推測する場合は、推測であることを明示してください。

{context}

---
質問: {question}

回答方針:
- まず結論を短く述べる
- 数値根拠を出す
- 支出・振替・資産変動を混同しない
- 増加要因・注意点を箇条書きにする
- 不明な点は不明と言う
"""
