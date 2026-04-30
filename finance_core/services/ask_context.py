from __future__ import annotations

import sqlite3
from datetime import date

from finance_core.services.snapshots import get_latest_snapshot


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


def previous_month(today: date | None = None) -> str:
    target = today or date.today()
    year = target.year
    month = target.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}-{month:02d}"


def get_card_month_summary(conn: sqlite3.Connection, month: str) -> dict[str, object]:
    total = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM card_transactions
        WHERE COALESCE(payment_month, substr(used_on, 1, 7)) = ?
        """,
        (month,),
    ).fetchone()["total"]

    by_merchant = conn.execute(
        """
        SELECT merchant, SUM(amount) AS total
        FROM card_transactions
        WHERE COALESCE(payment_month, substr(used_on, 1, 7)) = ?
        GROUP BY merchant
        ORDER BY total DESC
        LIMIT 10
        """,
        (month,),
    ).fetchall()

    large_transactions = conn.execute(
        """
        SELECT used_on, merchant, amount
        FROM card_transactions
        WHERE COALESCE(payment_month, substr(used_on, 1, 7)) = ?
        ORDER BY amount DESC, used_on DESC
        LIMIT 10
        """,
        (month,),
    ).fetchall()

    return {
        "month": month,
        "total": int(total),
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


def get_wallet_month_summary(conn: sqlite3.Connection, month: str) -> dict[str, object]:
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


def get_recent_transfers(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, object]]:
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
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM card_transactions
        WHERE COALESCE(payment_month, substr(used_on, 1, 7)) = ?
        """,
        (target,),
    ).fetchone()["total"]
    return insert_snapshot(conn, credit_card_unbilled=int(total), memo=f"card refresh {target}")


def build_finance_context(conn: sqlite3.Connection, question: str) -> str:
    now = get_latest_snapshot(conn)
    this_month = current_month()
    prev_month = previous_month()
    card_this = get_card_month_summary(conn, this_month)
    card_prev = get_card_month_summary(conn, prev_month)
    wallet = get_wallet_month_summary(conn, this_month)
    transfers = get_recent_transfers(conn)

    return f"""## 現在の資産状況
総資産: {now['total_assets']}円
銀行残高: {now['bank_total']}円
証券評価額: {now['securities_total']}円
財布残高: {now['wallet_total']}円
カード未払い/今月利用: {now['credit_card_unbilled']}円

## 今月のカード利用
対象月: {this_month}
合計: {card_this['total']}円
加盟店別: {card_this['by_merchant']}
高額決済: {card_this['large_transactions']}

## 前月比較
対象月: {prev_month}
前月カード合計: {card_prev['total']}円
差額: {int(card_this['total']) - int(card_prev['total'])}円

## 今月の現金支出
財布支出合計: {wallet['cash_out_total']}円
主な現金支出: {wallet['large_cash_out']}

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
