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
